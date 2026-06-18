from __future__ import annotations

import argparse
import html
import io
import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pdfplumber
from PIL import Image
from pypdf import PdfReader


@dataclass
class Field:
    name: str
    label: str
    type: str
    page: int
    x: float
    y: float
    width: float
    height: float
    source: str = "inferred"
    required: bool = False


def n(value: float) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def css_color(value: Any, default: str = "#111") -> str:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        channel = max(0, min(255, round(float(value) * 255)))
        return f"rgb({channel},{channel},{channel})"
    if isinstance(value, (list, tuple)):
        values = [float(v) for v in value]
        if len(values) == 3:
            return "rgb(" + ",".join(str(max(0, min(255, round(v * 255)))) for v in values) + ")"
        if len(values) == 4:  # Basic CMYK to RGB conversion.
            c, m, y, k = values
            return f"rgb({round(255*(1-c)*(1-k))},{round(255*(1-m)*(1-k))},{round(255*(1-y)*(1-k))})"
    return default


def slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return value[:64] or "campo"


def infer_type(label: str, width: float, height: float) -> str:
    text = label.lower()
    rules = [
        (r"e-?mail", "email"),
        (r"telefone|celular|fone|whats", "tel"),
        (r"data|nascimento|emiss[aã]o|validade", "date"),
        (r"cpf|cnpj|cep|rg|n[uú]mero|valor|quantidade", "number"),
        (r"senha", "password"),
    ]
    for pattern, kind in rules:
        if re.search(pattern, text):
            return kind
    if height > 34 or (height > 20 and width > 260):
        return "textarea"
    return "text"


def nearby_label(words: list[dict[str, Any]], x: float, top: float, max_dist: float = 110, allow_right: bool = False) -> str:
    candidates = []
    for word in words:
        gap = x - float(word["x1"])
        same_line = abs(float(word["bottom"]) - top) < 12 and -5 <= gap <= max_dist
        right = allow_right and abs(float(word["bottom"]) - top) < 12 and 0 <= float(word["x0"]) - x <= max_dist
        above = 0 <= top - float(word["bottom"]) < 24 and abs(float(word["x0"]) - x) < max_dist
        if same_line or right or above:
            dist = abs(x - float(word["x1"])) + abs(top - float(word["bottom"])) * 2
            candidates.append((dist, float(word["x0"]), word["text"]))
    candidates.sort()
    selected = sorted(candidates[:4], key=lambda item: item[1])
    return " ".join(item[2] for item in selected).strip(" :.-")


def acro_fields(reader: PdfReader) -> dict[int, list[Field]]:
    result: dict[int, list[Field]] = {}
    for page_no, page in enumerate(reader.pages, 1):
        page_height = float(page.mediabox.height)
        annotations = page.get("/Annots") or []
        for ref in annotations:
            annotation = ref.get_object()
            if annotation.get("/Subtype") != "/Widget":
                continue
            parent = annotation.get("/Parent")
            parent = parent.get_object() if parent else annotation
            raw_name = str(parent.get("/T") or annotation.get("/T") or f"campo_{page_no}")
            ft = str(parent.get("/FT") or annotation.get("/FT") or "/Tx")
            flags = int(parent.get("/Ff", 0))
            rect = [float(v) for v in annotation.get("/Rect", [0, 0, 100, 18])]
            x, bottom, x2, top_pdf = rect
            top = page_height - top_pdf
            kind = "checkbox" if ft == "/Btn" else "select" if ft == "/Ch" else "textarea" if flags & 4096 else infer_type(raw_name, x2-x, top_pdf-bottom)
            result.setdefault(page_no, []).append(Field(raw_name, raw_name.replace("_", " ").title(), kind, page_no, x, top, x2-x, top_pdf-bottom, "acroform", bool(flags & 2)))
    return result


def inferred_fields(page: pdfplumber.page.Page, page_no: int, words: list[dict[str, Any]], existing: list[Field]) -> list[Field]:
    fields: list[Field] = []
    seen: set[tuple[int, int]] = set()

    def overlaps(x: float, y: float, w: float, h: float) -> bool:
        return any(not (x+w < f.x or f.x+f.width < x or y+h < f.y or f.y+f.height < y) for f in existing + fields)

    # Horizontal writing lines are the most common non-AcroForm field representation.
    for line in page.lines:
        x0, x1 = sorted((float(line["x0"]), float(line["x1"])))
        top = float(line.get("top", page.height - line["y0"]))
        width = x1 - x0
        if width < 45 or abs(float(line["y1"]) - float(line["y0"])) > 1.5 or overlaps(x0, top-18, width, 20):
            continue
        label = nearby_label(words, x0, top) or f"Campo {len(existing)+len(fields)+1}"
        key = (round(x0), round(top))
        if key in seen:
            continue
        seen.add(key)
        fields.append(Field(slug(label), label, infer_type(label, width, 20), page_no, x0, max(0, top-20), width, 20))

    # Empty small rectangles usually represent checkboxes; larger ones are inputs/areas.
    for rect in page.rects:
        x, top = float(rect["x0"]), float(rect["top"])
        width, height = float(rect["width"]), float(rect["height"])
        if width < 8 or height < 8 or width > page.width * .9 or height > page.height * .8 or overlaps(x, top, width, height):
            continue
        is_checkbox = width <= 24 and height <= 24
        label = nearby_label(words, x + width, top + height, allow_right=is_checkbox) or f"Campo {len(existing)+len(fields)+1}"
        kind = "checkbox" if width <= 24 and height <= 24 else infer_type(label, width, height)
        fields.append(Field(slug(label), label, kind, page_no, x, top, width, height))
    return fields


def extract_images(pdf_path: Path, output: Path) -> dict[int, list[Path]]:
    assets = output / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(pdf_path))
    extracted: dict[int, list[Path]] = {}
    for page_no, page in enumerate(reader.pages, 1):
        for index, image in enumerate(page.images, 1):
            suffix = Path(image.name).suffix or ".png"
            target = assets / f"page-{page_no}-image-{index}{suffix}"
            target.write_bytes(image.data)
            extracted.setdefault(page_no, []).append(target)
    return extracted


def render_field(field: Field) -> str:
    style = f"left:{n(field.x)}px;top:{n(field.y)}px;width:{n(field.width)}px;height:{n(field.height)}px"
    common = f'class="form-field" style="{style}" name="{html.escape(field.name)}" aria-label="{html.escape(field.label)}"'
    if field.type == "textarea":
        return f"<textarea {common}></textarea>"
    if field.type == "select":
        return f"<select {common}><option value=\"\">Selecione</option></select>"
    if field.type == "checkbox":
        return f"<input {common} type=\"checkbox\">"
    return f"<input {common} type=\"{field.type}\">"


def convert(pdf_path: str | Path, output_dir: str | Path) -> Path:
    pdf_path, output = Path(pdf_path), Path(output_dir)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    reader = PdfReader(str(pdf_path))
    native = acro_fields(reader)
    images = extract_images(pdf_path, output)
    all_fields: list[Field] = []
    pages_html: list[str] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            words = page.extract_words(extra_attrs=["fontname", "size"], keep_blank_chars=False)
            fields = native.get(page_no, [])
            fields += inferred_fields(page, page_no, words, fields)
            # Keep names unique across repeated labels.
            used = {f.name for f in all_fields}
            for field in fields:
                base, counter = field.name, 2
                while field.name in used:
                    field.name = f"{base}_{counter}"; counter += 1
                used.add(field.name)
            all_fields.extend(fields)

            elements: list[str] = []
            for word in words:
                font = html.escape(str(word.get("fontname", "Arial")).split("+")[-1])
                style = f"left:{n(word['x0'])}px;top:{n(word['top'])}px;font-size:{n(word.get('size', 10))}px;font-family:'{font}',Arial,sans-serif"
                elements.append(f'<span class="pdf-text" style="{style}">{html.escape(word["text"])}</span>')
            for line in page.lines:
                x, top = float(line["x0"]), float(line["top"])
                w = max(1, float(line["x1"])-x)
                h = max(1, float(line["bottom"])-top)
                color = css_color(line.get("stroking_color"))
                elements.append(f'<div class="pdf-line" style="left:{n(x)}px;top:{n(top)}px;width:{n(w)}px;height:{n(h)}px;border-color:{color}"></div>')
            for rect in page.rects:
                stroke = css_color(rect.get("stroking_color"), "transparent")
                fill = css_color(rect.get("non_stroking_color"), "transparent") if rect.get("fill") else "transparent"
                elements.append(f'<div class="pdf-rect" style="left:{n(rect["x0"])}px;top:{n(rect["top"])}px;width:{n(rect["width"])}px;height:{n(rect["height"])}px;border-color:{stroke};background:{fill}"></div>')
            # Curves and arbitrary vector paths remain editable browser vectors (SVG),
            # never a rasterized page fallback.
            for curve in page.curves:
                points = curve.get("pts") or []
                if len(points) < 2:
                    continue
                coords = " ".join(f'{n(p[0])},{n(page.height-p[1])}' for p in points)
                stroke = css_color(curve.get("stroking_color"), "#111")
                fill = css_color(curve.get("non_stroking_color"), "transparent") if curve.get("fill") else "none"
                elements.append(f'<svg class="pdf-vector" viewBox="0 0 {n(page.width)} {n(page.height)}" aria-hidden="true"><polyline points="{coords}" stroke="{stroke}" fill="{fill}" stroke-width="{n(curve.get("linewidth", 1) or 1)}"/></svg>')
            # Map extracted images to placement objects in content-stream order.
            for idx, image_obj in enumerate(page.images):
                page_assets = images.get(page_no, [])
                if idx >= len(page_assets):
                    continue
                rel = page_assets[idx].relative_to(output).as_posix()
                elements.append(f'<img class="pdf-image" src="{html.escape(rel)}" alt="Imagem extraida do PDF" style="left:{n(image_obj["x0"])}px;top:{n(image_obj["top"])}px;width:{n(image_obj["width"])}px;height:{n(image_obj["height"])}px">')
            elements.extend(render_field(field) for field in fields)
            pages_html.append(f'<section class="pdf-page" data-page="{page_no}" style="width:{n(page.width)}px;height:{n(page.height)}px">{"".join(elements)}</section>')

    title = html.escape(pdf_path.stem)
    document = f'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
:root{{--page-shadow:0 2px 18px #0002}}*{{box-sizing:border-box}}body{{margin:0;background:#e8ebef;font-family:Arial,sans-serif}}
.document{{padding:24px;display:flex;flex-direction:column;align-items:center;gap:24px}}.pdf-page{{position:relative;overflow:hidden;background:white;box-shadow:var(--page-shadow)}}
.pdf-text,.pdf-image,.pdf-line,.pdf-rect,.pdf-vector,.form-field{{position:absolute}}.pdf-text{{white-space:pre;line-height:1;transform-origin:top left;color:#111}}.pdf-vector{{inset:0;width:100%;height:100%;pointer-events:none}}
.pdf-line{{border-top:1px solid #111;pointer-events:none}}.pdf-rect{{border:1px solid #111;pointer-events:none}}.pdf-image{{object-fit:fill}}
.form-field{{z-index:5;border:1px solid #3979d6;background:#fff8;padding:1px 3px;font:inherit;min-width:12px;min-height:12px}}input[type=checkbox].form-field{{padding:0}}
@media print{{body{{background:#fff}}.document{{padding:0;gap:0}}.pdf-page{{box-shadow:none;break-after:page}}.form-field{{border-color:transparent;background:transparent}}}}
</style></head><body><main class="document">{"".join(pages_html)}</main></body></html>'''
    (output / "index.html").write_text(document, encoding="utf-8")
    (output / "fields.json").write_text(json.dumps([asdict(f) for f in all_fields], ensure_ascii=False, indent=2), encoding="utf-8")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Converte PDF de formulario em HTML editavel")
    parser.add_argument("pdf")
    parser.add_argument("-o", "--output", default="output/pdf-html")
    args = parser.parse_args()
    result = convert(args.pdf, args.output)
    print(result / "index.html")
