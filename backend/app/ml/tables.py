"""Treino e inferencia de um detector neural de tabelas em PDFs.

Os rotulos de treino sao criados automaticamente com o detector vetorial do
pdfplumber. O modelo aprende uma mascara semantica e, depois de treinado, pode
detectar tabelas em PDFs vetoriais ou digitalizados.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Iterable

import pdfplumber
from PIL import Image, ImageDraw, ImageEnhance

LOGGER = logging.getLogger("pdf-neural.detector")


IMAGE_SIZE = 256
DEFAULT_THRESHOLD = .7


def require_torch():
    try:
        import torch
        import torch.nn as nn
    except ImportError as exc:
        raise RuntimeError(
            "PyTorch nao esta instalado. Execute: pip install -r requirements-ml.txt"
        ) from exc
    return torch, nn


def build_model():
    """Cria uma U-Net compacta, apropriada para treino local em CPU ou GPU."""
    torch, nn = require_torch()

    def block(in_channels: int, out_channels: int):
        return nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, padding=1),
            nn.BatchNorm2d(out_channels), nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, 3, padding=1),
            nn.BatchNorm2d(out_channels), nn.ReLU(inplace=True),
        )

    class TableUNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.e1, self.e2, self.e3 = block(1, 16), block(16, 32), block(32, 64)
            self.pool = nn.MaxPool2d(2)
            self.middle = block(64, 128)
            self.u3 = nn.ConvTranspose2d(128, 64, 2, 2)
            self.d3 = block(128, 64)
            self.u2 = nn.ConvTranspose2d(64, 32, 2, 2)
            self.d2 = block(64, 32)
            self.u1 = nn.ConvTranspose2d(32, 16, 2, 2)
            self.d1 = block(32, 16)
            self.out = nn.Conv2d(16, 1, 1)

        def forward(self, x):
            e1 = self.e1(x)
            e2 = self.e2(self.pool(e1))
            e3 = self.e3(self.pool(e2))
            x = self.middle(self.pool(e3))
            x = self.d3(torch.cat((self.u3(x), e3), dim=1))
            x = self.d2(torch.cat((self.u2(x), e2), dim=1))
            x = self.d1(torch.cat((self.u1(x), e1), dim=1))
            return self.out(x)

    return TableUNet()


def render_pdf(pdf_path: Path, output_dir: Path, dpi: int = 120) -> list[Path]:
    prefix = output_dir / pdf_path.stem
    LOGGER.info("Renderizando PDF %s para imagens (DPI=%d)", pdf_path.name, dpi)
    try:
        subprocess.run(
            ["pdftoppm", "-r", str(dpi), "-png", str(pdf_path), str(prefix)],
            check=True, capture_output=True,
        )
    except FileNotFoundError as exc:
        LOGGER.error("pdftoppm nao encontrado")
        raise SystemExit("pdftoppm nao encontrado. Instale o Poppler para renderizar PDFs.") from exc
    except subprocess.CalledProcessError as exc:
        err = exc.stderr.decode("utf-8", "replace")
        LOGGER.error("Erro no pdftoppm: %s", err)
        raise RuntimeError(err) from exc
    images = sorted(output_dir.glob(f"{pdf_path.stem}-*.png"))
    LOGGER.debug("Renderizadas %d páginas", len(images))
    return images


def pdf_color(value: Any) -> str:
    """Converte cores PDF (gray/RGB/CMYK) para uma cor CSS opaca."""
    if isinstance(value, (int, float)):
        channel = max(0, min(255, round(float(value) * 255)))
        return f"#{channel:02x}{channel:02x}{channel:02x}"
    if isinstance(value, (list, tuple)):
        channels = [float(channel) for channel in value]
        if len(channels) == 3:
            rgb = [max(0, min(255, round(channel * 255))) for channel in channels]
            return "#" + "".join(f"{channel:02x}" for channel in rgb)
        if len(channels) == 4:
            c, m, y, k = channels
            rgb = [round(255 * (1-c) * (1-k)), round(255 * (1-m) * (1-k)), round(255 * (1-y) * (1-k))]
            return "#" + "".join(f"{max(0, min(255, channel)):02x}" for channel in rgb)
    return "#000000"


def table_structures(pdf_path: Path) -> list[tuple[float, float, list[dict[str, Any]]]]:
    """Extrai os rotulos estruturais usados no treino e na cabeca de grade."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            structures = []
            for table in page.find_tables(table_settings={"intersection_tolerance": 15}):
                x0, top, x1, bottom = (float(value) for value in table.bbox)
                lines = []
                seen = set()
                # Consider edges from lines
                for edge in page.edges:
                    orientation = edge.get("orientation")
                    if orientation == "h":
                        position = float(edge["top"])
                        start, end = max(x0, float(edge["x0"])), min(x1, float(edge["x1"]))
                        if not (top - 1 <= position <= bottom + 1) or end - start < (x1 - x0) * .2:
                            continue
                        line = {"orientation": "h", "x": start, "y": position, "width": end-start, "height": 0.0}
                    elif orientation == "v":
                        position = float(edge["x0"])
                        start, end = max(top, float(edge["top"])), min(bottom, float(edge["bottom"]))
                        if not (x0 - 1 <= position <= x1 + 1) or end - start < (bottom - top) * .1:
                            continue
                        line = {"orientation": "v", "x": position, "y": start, "width": 0.0, "height": end-start}
                    else:
                        continue
                    key = (orientation, round(line["x"], 2), round(line["y"], 2), round(line["width"], 2), round(line["height"], 2))
                    if key in seen:
                        continue
                    seen.add(key)
                    line["color"] = pdf_color(edge.get("stroking_color"))
                    line["line_width"] = max(.25, float(edge.get("linewidth") or .5))
                    lines.append(line)

                # Consider edges from colored rects (headers)
                for rect in page.rects:
                    rx0, rtop, rx1, rbottom = (float(rect[k]) for k in ("x0", "top", "x1", "bottom"))
                    # Only if it's inside or overlapping the table
                    if rx1 < x0 - 1 or rx0 > x1 + 1 or rbottom < top - 1 or rtop > bottom + 1:
                        continue
                    
                    # If it's a colored background (not white)
                    color = rect.get("non_stroking_color")
                    if color is not None and color != 1 and color != (1, 1, 1):
                        # Add horizontal and vertical boundaries of the rect as virtual lines
                        # for the grid detection
                        rect_lines = [
                            {"orientation": "h", "x": rx0, "y": rtop, "width": rx1-rx0, "height": 0.0, "color": "#000000", "line_width": 0.5},
                            {"orientation": "h", "x": rx0, "y": rbottom, "width": rx1-rx0, "height": 0.0, "color": "#000000", "line_width": 0.5},
                            {"orientation": "v", "x": rx0, "y": rtop, "width": 0.0, "height": rbottom-rtop, "color": "#000000", "line_width": 0.5},
                            {"orientation": "v", "x": rx1, "y": rtop, "width": 0.0, "height": rbottom-rtop, "color": "#000000", "line_width": 0.5},
                        ]
                        for rl in rect_lines:
                            # Clip line to table bbox
                            if rl["orientation"] == "h":
                                rl["x"] = max(x0, rl["x"])
                                rl["width"] = min(x1, rl["x"] + rl["width"]) - rl["x"]
                                if rl["width"] <= 0: continue
                            else:
                                rl["y"] = max(top, rl["y"])
                                rl["height"] = min(bottom, rl["y"] + rl["height"]) - rl["y"]
                                if rl["height"] <= 0: continue

                            key = (rl["orientation"], round(rl["x"], 2), round(rl["y"], 2), round(rl["width"], 2), round(rl["height"], 2))
                            if key not in seen:
                                seen.add(key)
                                lines.append(rl)

                horizontal = {round(line["y"], 1) for line in lines if line["orientation"] == "h"}
                vertical = {round(line["x"], 1) for line in lines if line["orientation"] == "v"}
                structures.append({
                    "bbox": (x0, top, x1, bottom), "lines": lines,
                    "row_count": max(0, len(horizontal) - 1),
                    "column_count": max(0, len(vertical) - 1),
                })
            pages.append((float(page.width), float(page.height), structures))
    return pages


def table_boxes(pdf_path: Path) -> list[tuple[float, float, list[tuple[float, float, float, float]]]]:
    return [
        (width, height, [structure["bbox"] for structure in structures])
        for width, height, structures in table_structures(pdf_path)
    ]


def create_dataset(pdf_paths: Iterable[Path], output_dir: Path) -> dict[str, Any]:
    """Renderiza paginas e cria mascaras automaticamente a partir das tabelas."""
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir, masks_dir, grids_dir = output_dir / "images", output_dir / "masks", output_dir / "grid-masks"
    images_dir.mkdir(exist_ok=True); masks_dir.mkdir(exist_ok=True); grids_dir.mkdir(exist_ok=True)
    samples = []
    with tempfile.TemporaryDirectory() as temporary:
        render_dir = Path(temporary)
        for pdf_index, pdf_path in enumerate(pdf_paths, 1):
            rendered = render_pdf(pdf_path, render_dir)
            geometry = table_structures(pdf_path)
            if len(rendered) != len(geometry):
                raise RuntimeError(f"Numero de paginas inconsistente em {pdf_path}")
            for page_index, (image_path, (page_w, page_h, structures)) in enumerate(zip(rendered, geometry), 1):
                image = Image.open(image_path).convert("L")
                sx, sy = image.width / page_w, image.height / page_h
                mask = Image.new("L", image.size, 0)
                grid_mask = Image.new("L", image.size, 0)
                grid_draw = ImageDraw.Draw(grid_mask)
                pixels = mask.load()
                for structure in structures:
                    x0, top, x1, bottom = structure["bbox"]
                    left, right = max(0, int(x0*sx)), min(image.width, int(x1*sx)+1)
                    upper, lower = max(0, int(top*sy)), min(image.height, int(bottom*sy)+1)
                    for y in range(upper, lower):
                        for x in range(left, right):
                            pixels[x, y] = 255
                    for line in structure["lines"]:
                        start = (round(line["x"] * sx), round(line["y"] * sy))
                        end = (round((line["x"] + line["width"]) * sx), round((line["y"] + line["height"]) * sy))
                        grid_draw.line((start, end), fill=255, width=max(2, round(line["line_width"] * max(sx, sy))))
                name = f"pdf-{pdf_index:03d}-page-{page_index:04d}.png"
                image.save(images_dir / name); mask.save(masks_dir / name); grid_mask.save(grids_dir / name)
                samples.append({
                    "image": f"images/{name}", "mask": f"masks/{name}",
                    "grid_mask": f"grid-masks/{name}", "tables": len(structures),
                })
    manifest = {"image_size": IMAGE_SIZE, "samples": samples}
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def image_tensor(image: Image.Image, augment: bool = False):
    torch, _ = require_torch()
    image = image.convert("L").resize((IMAGE_SIZE, IMAGE_SIZE))
    if augment:
        image = ImageEnhance.Contrast(image).enhance(random.uniform(.75, 1.25))
    # frombuffer avoids building a Python list with one object per pixel.
    data = torch.frombuffer(bytearray(image.tobytes()), dtype=torch.uint8)
    return data.reshape(1, IMAGE_SIZE, IMAGE_SIZE).float().div_(255.0)


def train(
    dataset_dir: Path,
    model_path: Path,
    epochs: int = 30,
    learning_rate: float = 1e-3,
    resume_path: Path | None = None,
) -> None:
    torch, nn = require_torch()
    import torch.nn.functional as functional
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    samples = manifest["samples"]
    if not samples:
        raise ValueError("O conjunto de treino esta vazio")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_model().to(device)
    if resume_path is not None:
        checkpoint = torch.load(resume_path, map_location=device, weights_only=True)
        model.load_state_dict(checkpoint["state_dict"])
        LOGGER.info("Ajuste fino a partir de %s", resume_path)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)
    # Table pixels are much rarer than background pixels. Weighting by page count
    # made the network learn only the darkest text inside a table; pixel balance
    # teaches it to fill the complete annotated region.
    target_pixels = [image_tensor(Image.open(dataset_dir / sample["mask"])) for sample in samples]
    positives = sum(float(mask.sum()) for mask in target_pixels)
    total_pixels = len(target_pixels) * IMAGE_SIZE * IMAGE_SIZE
    pos_weight = torch.tensor([min(20.0, max(1.0, (total_pixels - positives) / max(1.0, positives)))], device=device)
    model.train()
    for epoch in range(1, epochs + 1):
        random.shuffle(samples); total = 0.0
        for sample in samples:
            image = image_tensor(Image.open(dataset_dir / sample["image"]), augment=True).unsqueeze(0).to(device)
            mask = image_tensor(Image.open(dataset_dir / sample["mask"])).unsqueeze(0).to(device)
            grid_path = sample.get("grid_mask")
            grid_mask = (
                image_tensor(Image.open(dataset_dir / grid_path)).unsqueeze(0).to(device)
                if grid_path else torch.zeros_like(mask)
            )
            optimizer.zero_grad()
            logits = model(image)
            probabilities = torch.sigmoid(logits)
            # Penaliza especialmente os falsos positivos logo apos as bordas,
            # onde campos como "Data" podem ficar visualmente proximos da tabela.
            halo = (functional.max_pool2d(mask, kernel_size=17, stride=1, padding=8) - mask).clamp_(0, 1)
            pixel_loss = functional.binary_cross_entropy_with_logits(
                logits, mask, pos_weight=pos_weight, reduction="none",
            )
            # A mascara de grade faz a rede dar peso extra aos tracos que
            # caracterizam linhas e colunas, sem deixar de segmentar a regiao.
            boundary_loss = (pixel_loss * (1.0 + 4.0 * halo + 2.0 * grid_mask)).mean()
            intersection = (probabilities * mask).sum()
            dice_loss = 1.0 - (2.0 * intersection + 1.0) / (probabilities.sum() + mask.sum() + 1.0)
            loss = boundary_loss + dice_loss
            loss.backward(); optimizer.step(); total += float(loss.item())
        LOGGER.debug("Epoca %d/%d concluída. Perda média: %.5f", epoch, epochs, total/len(samples))
    model_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "image_size": IMAGE_SIZE}, model_path)
    LOGGER.info("Modelo salvo em %s", model_path)


def mask_components(probabilities, threshold: float = DEFAULT_THRESHOLD, min_area: int = 30) -> list[dict[str, float]]:
    """Transforma a mascara neural em caixas, sem depender de OpenCV/SciPy."""
    height, width = len(probabilities), len(probabilities[0]) if probabilities else 0
    active = {(x, y) for y, row in enumerate(probabilities) for x, value in enumerate(row) if value >= threshold}
    components = []
    while active:
        seed = active.pop(); stack = [seed]; points = [seed]
        while stack:
            x, y = stack.pop()
            for neighbor in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
                if neighbor in active:
                    active.remove(neighbor); stack.append(neighbor); points.append(neighbor)
        if len(points) < min_area:
            continue
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        components.append({
            "x": min(xs), "y": min(ys), "width": max(xs)-min(xs)+1, "height": max(ys)-min(ys)+1,
            "confidence": sum(probabilities[y][x] for x, y in points) / len(points),
        })
    return sorted(components, key=lambda box: (box["y"], box["x"]))


def box_iou(box: dict[str, float], bbox: tuple[float, float, float, float]) -> float:
    x0, top, x1, bottom = bbox
    right, lower = box["x"] + box["width"], box["y"] + box["height"]
    intersection = max(0.0, min(right, x1) - max(box["x"], x0)) * max(0.0, min(lower, bottom) - max(box["y"], top))
    union = box["width"] * box["height"] + (x1-x0) * (bottom-top) - intersection
    return intersection / union if union else 0.0


def _group_positions(values: list[int], tolerance: int = 2) -> list[int]:
    groups: list[list[int]] = []
    for value in sorted(values):
        if not groups or value - groups[-1][-1] > tolerance:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [round(sum(group) / len(group)) for group in groups]


def raster_grid_lines(
    image: Image.Image,
    box: dict[str, float],
    page_width: float,
    page_height: float,
) -> list[dict[str, Any]]:
    """Recupera uma grade de uma pagina raster quando nao ha vetores PDF."""
    rgb = image.convert("RGB")
    sx, sy = rgb.width / page_width, rgb.height / page_height
    left = max(0, round(box["x"] * sx)); right = min(rgb.width - 1, round((box["x"] + box["width"]) * sx))
    upper = max(0, round(box["y"] * sy)); lower = min(rgb.height - 1, round((box["y"] + box["height"]) * sy))
    if right - left < 10 or lower - upper < 10:
        return []
    pixels = rgb.load()

    def dark(x: int, y: int) -> bool:
        r, g, b = pixels[x, y]
        return (r + g + b) / 3 < 190

    horizontal = _group_positions([
        y for y in range(upper, lower + 1)
        if sum(dark(x, y) for x in range(left, right + 1)) / (right-left+1) >= .55
    ])
    vertical = _group_positions([
        x for x in range(left, right + 1)
        if sum(dark(x, y) for y in range(upper, lower + 1)) / (lower-upper+1) >= .45
    ])

    def sampled_color(points: list[tuple[int, int]]) -> str:
        samples = [pixels[x, y] for x, y in points]
        samples.sort(key=lambda color: sum(color))
        selected = samples[:max(1, len(samples)//4)]
        channels = [sorted(color[index] for color in selected)[len(selected)//2] for index in range(3)]
        return "#" + "".join(f"{channel:02x}" for channel in channels)

    lines = []
    for y in horizontal:
        lines.append({
            "orientation": "h", "x": left/sx, "y": y/sy,
            "width": (right-left)/sx, "height": 0.0,
            "line_width": max(.5, 1/sy),
            "color": sampled_color([(x, y) for x in range(left, right+1)]),
        })
    for x in vertical:
        lines.append({
            "orientation": "v", "x": x/sx, "y": upper/sy,
            "width": 0.0, "height": (lower-upper)/sy,
            "line_width": max(.5, 1/sx),
            "color": sampled_color([(x, y) for y in range(upper, lower+1)]),
        })
    return lines


def add_grid_structure(
    box: dict[str, Any],
    structures: list[dict[str, Any]],
    image: Image.Image,
    page_width: float,
    page_height: float,
) -> None:
    matches = [(box_iou(box, structure["bbox"]), structure) for structure in structures]
    score, structure = max(matches, default=(0.0, None), key=lambda item: item[0])
    if structure is not None and score >= .25:
        box["neural_bbox"] = {key: box[key] for key in ("x", "y", "width", "height")}
        x0, top, x1, bottom = structure["bbox"]
        box.update({"x": x0, "y": top, "width": x1-x0, "height": bottom-top})
        box["lines"] = structure["lines"]
        box["row_count"] = structure["row_count"]
        box["column_count"] = structure["column_count"]
        box["structure_source"] = "vector"
        return
    lines = raster_grid_lines(image, box, page_width, page_height)
    box["lines"] = lines
    box["row_count"] = max(0, len({round(line["y"], 1) for line in lines if line["orientation"] == "h"}) - 1)
    box["column_count"] = max(0, len({round(line["x"], 1) for line in lines if line["orientation"] == "v"}) - 1)
    box["structure_source"] = "raster"


def consolidate_detections(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Une fragmentos neurais que apontam para a mesma grade estrutural."""
    vector_by_bbox: dict[tuple[float, float, float, float], dict[str, Any]] = {}
    raster = []
    for detection in detections:
        if detection.get("structure_source") == "vector":
            key = tuple(round(float(detection[name]), 2) for name in ("x", "y", "width", "height"))
            current = vector_by_bbox.get(key)
            if current is None or float(detection["confidence"]) > float(current["confidence"]):
                vector_by_bbox[key] = detection
        else:
            raster.append(detection)
    vectors = list(vector_by_bbox.values())

    def overlap_fraction(first: dict[str, Any], second: dict[str, Any]) -> float:
        right = min(first["x"] + first["width"], second["x"] + second["width"])
        bottom = min(first["y"] + first["height"], second["y"] + second["height"])
        area = max(0.0, right - max(first["x"], second["x"])) * max(0.0, bottom - max(first["y"], second["y"]))
        smaller = min(first["width"] * first["height"], second["width"] * second["height"])
        return area / smaller if smaller else 0.0

    # Um componente raster quase todo contido numa tabela vetorial ja aceita e
    # apenas uma ilha da mesma mascara, nao uma segunda tabela.
    raster = [
        detection for detection in raster
        if detection.get("row_count", 0) > 0 and detection.get("column_count", 0) > 0
        and not any(overlap_fraction(detection, vector) >= .5 for vector in vectors)
    ]
    return sorted(vectors + raster, key=lambda item: (item["page"], item["y"], item["x"]))


class TableDetector:
    """Detector carregado uma vez e reutilizavel pela API web."""

    def __init__(self, model_path: Path, threshold: float = DEFAULT_THRESHOLD, min_confidence: float = .65):
        self.torch, _ = require_torch()
        self.device = self.torch.device("cuda" if self.torch.cuda.is_available() else "cpu")
        LOGGER.info("Carregando detector neural (%s) no dispositivo: %s", model_path.name, self.device)
        try:
            checkpoint = self.torch.load(model_path, map_location=self.device, weights_only=True)
            self.model = build_model().to(self.device)
            self.model.load_state_dict(checkpoint["state_dict"])
            self.model.eval()
            self.threshold = threshold
            self.min_confidence = min_confidence
            self._inference_lock = threading.Lock()
            LOGGER.info("Detector neural carregado com sucesso")
        except Exception:
            LOGGER.exception("Falha ao carregar modelo neural em %s", model_path)
            raise

    def detect(self, pdf_path: Path, output_json: Path | None = None) -> list[dict[str, Any]]:
        result = []
        LOGGER.info("Iniciando detecção em %s", pdf_path.name)
        with tempfile.TemporaryDirectory() as temporary:
            rendered = render_pdf(pdf_path, Path(temporary))
            geometry = table_structures(pdf_path)
            for page_number, (path, (page_w, page_h, structures)) in enumerate(zip(rendered, geometry), 1):
                LOGGER.debug("Processando página %d", page_number)
                image = Image.open(path).convert("L")
                # A mesma instancia pode atender jobs de varias threads. O forward
                # e serializado para evitar disputa no backend nativo do PyTorch.
                with self._inference_lock, self.torch.no_grad():
                    logits = self.model(image_tensor(image).unsqueeze(0).to(self.device))
                    probabilities = self.torch.sigmoid(logits)[0, 0].cpu().tolist()
                components = [
                    box for box in mask_components(probabilities, self.threshold)
                    if box["width"] >= IMAGE_SIZE * .25
                    and box["height"] >= IMAGE_SIZE * .025
                    and box["confidence"] >= self.min_confidence
                ]
                LOGGER.debug("Encontrados %d componentes na página %d", len(components), page_number)
                for index, box in enumerate(components, 1):
                    detected = {
                        "id": f"page-{page_number}-neural-table-{index}", "page": page_number,
                        "x": box["x"] * page_w / IMAGE_SIZE, "y": box["y"] * page_h / IMAGE_SIZE,
                        "width": box["width"] * page_w / IMAGE_SIZE,
                        "height": box["height"] * page_h / IMAGE_SIZE,
                        "confidence": round(box["confidence"], 4), "source": "neural",
                    }
                    add_grid_structure(detected, structures, Image.open(path), page_w, page_h)
                    result.append(detected)
        result = consolidate_detections(result)
        LOGGER.info("Detecção finalizada: %d tabelas encontradas em %s", len(result), pdf_path.name)
        for page_number in {item["page"] for item in result}:
            for index, item in enumerate((entry for entry in result if entry["page"] == page_number), 1):
                item["id"] = f"page-{page_number}-neural-table-{index}"
        if output_json is not None:
            output_json.parent.mkdir(parents=True, exist_ok=True)
            output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result


def detect(
    pdf_path: Path,
    model_path: Path,
    output_json: Path,
    threshold: float = DEFAULT_THRESHOLD,
    min_confidence: float = .65,
) -> list[dict[str, Any]]:
    return TableDetector(model_path, threshold, min_confidence).detect(pdf_path, output_json)


def pdf_files(inputs: list[str]) -> list[Path]:
    files = []
    for value in inputs:
        path = Path(value)
        files.extend(sorted(path.rglob("*.pdf")) if path.is_dir() else [path])
    return [path for path in files if path.is_file() and path.suffix.lower() == ".pdf"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Detector neural de tabelas em PDF")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="cria imagens e rotulos de treino")
    prepare.add_argument("pdf", nargs="+"); prepare.add_argument("-o", "--output", default="data/tables")
    training = commands.add_parser("train", help="treina o modelo")
    training.add_argument("dataset"); training.add_argument("-o", "--output", default="models/table_detector.pt")
    training.add_argument("--epochs", type=int, default=30); training.add_argument("--learning-rate", type=float, default=1e-3)
    training.add_argument("--resume", help="checkpoint usado como ponto de partida para ajuste fino")
    inference = commands.add_parser("detect", help="detecta tabelas em um PDF")
    inference.add_argument("pdf"); inference.add_argument("--model", default="models/table_detector.pt")
    inference.add_argument("-o", "--output", default="output/neural-tables.json")
    inference.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    inference.add_argument("--min-confidence", type=float, default=.65)
    args = parser.parse_args()
    if args.command == "prepare":
        files = pdf_files(args.pdf)
        if not files: raise SystemExit("Nenhum PDF foi encontrado")
        manifest = create_dataset(files, Path(args.output))
        print(f"{len(manifest['samples'])} paginas preparadas em {args.output}")
    elif args.command == "train":
        train(
            Path(args.dataset), Path(args.output), args.epochs, args.learning_rate,
            Path(args.resume) if args.resume else None,
        )
    else:
        boxes = detect(Path(args.pdf), Path(args.model), Path(args.output), args.threshold, args.min_confidence)
        print(f"{len(boxes)} tabelas detectadas; resultado em {args.output}")


if __name__ == "__main__":
    main()
