from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pdfplumber
from PIL import Image, ImageDraw
from pymongo import MongoClient

from backend.app.ml.fields import IMAGE_SIZE, render_pdf
from backend.app.utils.common import download_pdf


LOGGER = logging.getLogger("pdf-neural.prepare-fields-from-mongo")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_pdf_index(pdf_roots: list[Path]) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for root in pdf_roots:
        paths = root.rglob("*.pdf") if root.is_dir() else [root]
        for path in paths:
            if path.is_file():
                index.setdefault(file_sha256(path), path)
    return index


def normalized_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(text.lower().split())


def parse_pdf_overrides(values: list[str]) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--pdf-override deve usar o formato nome=/caminho/arquivo.pdf")
        name, path = value.split("=", 1)
        pdf_path = Path(path).expanduser()
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF informado em --pdf-override nao existe: {pdf_path}")
        overrides[normalized_key(name)] = pdf_path
    return overrides


def safe_name(value: object, fallback: str) -> str:
    text = str(value or fallback)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    safe = "".join(char if char.isalnum() else "-" for char in text.lower()).strip("-")
    return safe or fallback


def field_boxes(fields: list[dict[str, Any]], manual_only: bool) -> dict[int, list[tuple[float, float, float, float]]]:
    pages: dict[int, list[tuple[float, float, float, float]]] = {}
    for field in fields:
        if manual_only and field.get("source") != "manual":
            continue
        raw_boxes = field.get("option_boxes") if field.get("type") == "radio" else None
        boxes = raw_boxes if isinstance(raw_boxes, list) and raw_boxes else [field]
        for box in boxes:
            try:
                page = int(box["page"])
                x = float(box["x"])
                y = float(box["y"])
                width = float(box["width"])
                height = float(box["height"])
            except (KeyError, TypeError, ValueError):
                continue
            if page < 1 or x < 0 or y < 0 or width <= 0 or height <= 0:
                continue
            pages.setdefault(page, []).append((x, y, x + width, y + height))
    return pages


def resolve_pdf(
    document: dict[str, Any],
    pdf_index: dict[str, Path],
    pdf_overrides: dict[str, Path],
    download_dir: Path,
) -> Path | None:
    metadata = document.get("metadata") or {}
    filename = metadata.get("filename")
    if filename:
        direct = pdf_overrides.get(normalized_key(filename))
        if direct:
            return direct

    content_hash = metadata.get("content_hash") or document.get("content_hash")
    if content_hash and content_hash in pdf_index:
        return pdf_index[content_hash]

    pdf_url = metadata.get("pdf_url")
    if isinstance(pdf_url, str) and pdf_url.strip():
        name, data = download_pdf(pdf_url)
        target = download_dir / Path(name).name
        target.write_bytes(data)
        return target

    return None


def create_dataset_from_mongo(
    mongo_uri: str,
    output_dir: Path,
    pdf_roots: list[Path],
    pdf_overrides: dict[str, Path],
    database_name: str,
    collection_name: str,
    manual_only: bool,
    current_only: bool,
    filename_contains: str | None,
    limit: int | None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    masks_dir = output_dir / "masks"
    images_dir.mkdir(exist_ok=True)
    masks_dir.mkdir(exist_ok=True)

    pdf_index = build_pdf_index(pdf_roots)
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    db = client.get_database(database_name)

    query: dict[str, Any] = {"fields.0": {"$exists": True}}
    if current_only:
        query["is_current"] = True
    if filename_contains:
        query["metadata.filename"] = {"$regex": filename_contains, "$options": "i"}

    projection = {
        "_id": 0,
        "document_id": 1,
        "job_id": 1,
        "version": 1,
        "is_current": 1,
        "metadata": 1,
        "content_hash": 1,
        "fields": 1,
    }
    cursor = db[collection_name].find(query, projection).sort([("document_id", 1), ("version", -1)])
    if limit:
        cursor = cursor.limit(limit)

    samples: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    used_documents = 0

    with tempfile.TemporaryDirectory(prefix="pdf-neural-mongo-pdfs-") as temporary:
        download_dir = Path(temporary)
        for document_index, document in enumerate(cursor, 1):
            boxes_by_page = field_boxes(document.get("fields") or [], manual_only)
            if not boxes_by_page:
                skipped.append({
                    "document_id": document.get("document_id"),
                    "job_id": document.get("job_id"),
                    "reason": "sem campos manuais validos" if manual_only else "sem campos validos",
                })
                continue

            pdf_path = resolve_pdf(document, pdf_index, pdf_overrides, download_dir)
            if pdf_path is None:
                skipped.append({
                    "document_id": document.get("document_id"),
                    "job_id": document.get("job_id"),
                    "filename": (document.get("metadata") or {}).get("filename"),
                    "content_hash": (document.get("metadata") or {}).get("content_hash") or document.get("content_hash"),
                    "reason": "pdf nao encontrado localmente e metadata.pdf_url ausente",
                })
                continue

            document_label = safe_name(
                (document.get("metadata") or {}).get("filename") or document.get("document_id"),
                f"doc-{document_index:03d}",
            )
            with tempfile.TemporaryDirectory(prefix="pdf-neural-render-") as render_tmp:
                rendered = render_pdf(pdf_path, Path(render_tmp))
                with pdfplumber.open(pdf_path) as pdf:
                    for page_index, page in enumerate(pdf.pages, 1):
                        if page_index not in boxes_by_page or page_index > len(rendered):
                            continue
                        image = Image.open(rendered[page_index - 1]).convert("L")
                        page_width, page_height = float(page.width), float(page.height)
                        sx, sy = image.width / page_width, image.height / page_height
                        mask = Image.new("L", image.size, 0)
                        draw = ImageDraw.Draw(mask)
                        for x0, y0, x1, y1 in boxes_by_page[page_index]:
                            draw.rectangle([x0 * sx, y0 * sy, x1 * sx, y1 * sy], fill=255)

                        name = f"{document_label}-page-{page_index:04d}.png"
                        image.save(images_dir / name)
                        mask.save(masks_dir / name)
                        samples.append({
                            "image": f"images/{name}",
                            "mask": f"masks/{name}",
                            "fields": len(boxes_by_page[page_index]),
                            "document_id": document.get("document_id"),
                            "job_id": document.get("job_id"),
                            "version": document.get("version"),
                        })
                used_documents += 1

    manifest = {
        "image_size": IMAGE_SIZE,
        "source": "mongodb",
        "collection": collection_name,
        "manual_only": manual_only,
        "samples": samples,
        "skipped": skipped,
        "used_documents": used_documents,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Cria dataset de campos usando rotulos manuais salvos no MongoDB.")
    parser.add_argument("--mongo-uri", required=True)
    parser.add_argument("-o", "--output", default="data/fields_mongo")
    parser.add_argument("--pdf-root", action="append", type=Path, default=[Path("data")])
    parser.add_argument("--database", default="pdf_neural")
    parser.add_argument("--collection", default="documents")
    parser.add_argument("--filename-contains")
    parser.add_argument("--pdf-override", action="append", default=[])
    parser.add_argument("--include-non-manual", action="store_true")
    parser.add_argument("--include-versions", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s: %(message)s")
    manifest = create_dataset_from_mongo(
        mongo_uri=args.mongo_uri,
        output_dir=Path(args.output),
        pdf_roots=args.pdf_root,
        pdf_overrides=parse_pdf_overrides(args.pdf_override),
        database_name=args.database,
        collection_name=args.collection,
        manual_only=not args.include_non_manual,
        current_only=not args.include_versions,
        filename_contains=args.filename_contains,
        limit=args.limit,
    )
    print(json.dumps({
        "samples": len(manifest["samples"]),
        "used_documents": manifest["used_documents"],
        "skipped": len(manifest["skipped"]),
        "output": args.output,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
