"""Treino e inferencia de um detector neural de campos em PDFs.

Os rotulos de treino sao criados automaticamente a partir de AcroForms e da 
deteccao heuristica atual do converter.py.
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
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

LOGGER = logging.getLogger("pdf-neural.field-detector")

IMAGE_SIZE = 512  # Aumentado para detectar campos pequenos com mais precisao
DEFAULT_THRESHOLD = .5

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
    """Cria uma U-Net para segmentacao de campos."""
    torch, nn = require_torch()

    def block(in_channels: int, out_channels: int):
        return nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, padding=1),
            nn.BatchNorm2d(out_channels), nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, 3, padding=1),
            nn.BatchNorm2d(out_channels), nn.ReLU(inplace=True),
        )

    class FieldUNet(nn.Module):
        def __init__(self):
            super().__init__()
            # Arquitetura similar à TableUNet, mas com mais canais se necessario
            self.e1, self.e2, self.e3, self.e4 = block(1, 16), block(16, 32), block(32, 64), block(64, 128)
            self.pool = nn.MaxPool2d(2)
            self.middle = block(128, 256)
            self.u4 = nn.ConvTranspose2d(256, 128, 2, 2)
            self.d4 = block(256, 128)
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
            e4 = self.e4(self.pool(e3))
            x = self.middle(self.pool(e4))
            x = self.d4(torch.cat((self.u4(x), e4), dim=1))
            x = self.d3(torch.cat((self.u3(x), e3), dim=1))
            x = self.d2(torch.cat((self.u2(x), e2), dim=1))
            x = self.d1(torch.cat((self.u1(x), e1), dim=1))
            return self.out(x)

    return FieldUNet()

def render_pdf(pdf_path: Path, output_dir: Path, dpi: int = 150) -> list[Path]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF nao esta instalado. Execute: pip install PyMuPDF"
        ) from exc
    prefix = output_dir / pdf_path.stem
    paths = []
    doc = fitz.open(str(pdf_path))
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
        img_path = output_dir / f"{pdf_path.stem}-{i+1:03d}.png"
        pix.save(str(img_path))
        paths.append(img_path)
    doc.close()
    return paths

def field_boxes(pdf_path: Path) -> list[tuple[float, float, list[tuple[float, float, float, float]]]]:
    """Extrai campos (AcroForms e detectados pelo converter) para usar como rotulo."""
    from converter import acro_fields, inferred_fields
    from pypdf import PdfReader
    
    pages_data = []
    reader = PdfReader(str(pdf_path))
    acros = acro_fields(reader)
    
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            pno = i + 1
            # Campos do AcroForm
            current_acros = acros.get(pno, [])
            # Campos inferidos (heuristica atual)
            words = page.extract_words()
            # Precisamos de table_bboxes para inferred_fields
            tables = page.find_tables()
            table_bboxes = [table.bbox for table in tables]

            inferred = inferred_fields(page, pno, words, current_acros, table_bboxes)

            all_fields = current_acros + inferred

            # Filtro: não detectar campos se houver imagem, texto ou tabelas (cabeçalhos)
            image_bboxes = []
            for img in page.images:
                ix0, iy0, ix1, iy1 = float(img["x0"]), float(img["top"]), float(img["x1"]), float(img["bottom"])
                image_bboxes.append((ix0, iy0, ix1, iy1))

            text_bboxes = []
            for word in words:
                # Tracos/underscores sao a aparencia do campo, nao conteudo que
                # invalida o rotulo.
                if any(char.isalnum() for char in str(word.get("text", ""))):
                    text_bboxes.append((float(word["x0"]), float(word["top"]), float(word["x1"]), float(word["bottom"])))

            header_bboxes = []
            for table in tables:
                for row in table.rows:
                    for cell in row.cells:
                        if cell:
                            # Precisamos checar se tem texto
                            cell_text = page.within_bbox(cell).extract_text()
                            if cell_text and cell_text.strip():
                                header_bboxes.append(cell)

            def is_overlap(fx, fy, fw, fh, targets):
                fx1, fy1 = fx + fw, fy + fh
                for (tx0, ty0, tx1, ty1) in targets:
                    if not (fx1 <= tx0 or tx1 <= fx or fy1 <= ty0 or ty1 <= fy):
                        return True
                return False

            # Nao filtre por page.lines: campos de escrita sao normalmente
            # delimitados pela propria linha horizontal que devem sobrepor.
            # AcroForms sao fontes de verdade e nao devem ser descartados por
            # texto/arte vetorial contidos em sua aparencia.
            filtered_fields = list(current_acros) + [
                f for f in all_fields[len(current_acros):]
                if not is_overlap(f.x, f.y, f.width, f.height, image_bboxes)
                and (f.type in {"date", "time"} or not is_overlap(f.x, f.y, f.width, f.height, text_bboxes))
                and not is_overlap(f.x, f.y, f.width, f.height, header_bboxes)
            ]

            def normalize_bbox(bbox):
                x0, y0, x1, y1 = bbox
                height = y1 - y0
                # Se a altura estiver muito fora do padrão (ex: 20), ajustamos mantendo o centro ou a base?
                # Formulários costumam ter texto e o campo logo acima da linha.
                # Se fixarmos em 20 e o original era 2, expandimos para cima.
                target_h = 20.0
                if height < target_h:
                    y0 = y1 - target_h
                elif height > target_h:
                    # Se for muito grande (área de texto), talvez devêssemos manter,
                    # mas o pedido é para ser igual ao campo nome (que tem ~20).
                    # Vamos limitar a altura máxima também para campos de linha única.
                    if height < 40: # Provavelmente um campo de linha única um pouco mais alto
                        y0 = y1 - target_h
                return (x0, y0, x1, y1)

            bboxes = [normalize_bbox((f.x, f.y, f.x + f.width, f.y + f.height)) for f in filtered_fields]
            pages_data.append((float(page.width), float(page.height), bboxes))
            
    return pages_data

def create_dataset(pdf_paths: Iterable[Path], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir, masks_dir = output_dir / "images", output_dir / "masks"
    images_dir.mkdir(exist_ok=True); masks_dir.mkdir(exist_ok=True)
    samples = []
    
    with tempfile.TemporaryDirectory() as temporary:
        render_dir = Path(temporary)
        for pdf_index, pdf_path in enumerate(pdf_paths, 1):
            try:
                rendered = render_pdf(pdf_path, render_dir)
                geometry = field_boxes(pdf_path)
                if len(rendered) != len(geometry):
                    continue
                
                for page_index, (image_path, (page_w, page_h, bboxes)) in enumerate(zip(rendered, geometry), 1):
                    image = Image.open(image_path).convert("L")
                    sx, sy = image.width / page_w, image.height / page_h
                    mask = Image.new("L", image.size, 0)
                    draw = ImageDraw.Draw(mask)
                    
                    for (x0, y0, x1, y1) in bboxes:
                        draw.rectangle(
                            [x0 * sx, y0 * sy, x1 * sx, y1 * sy],
                            fill=255
                        )
                    
                    name = f"field-{pdf_index:03d}-page-{page_index:04d}.png"
                    image.save(images_dir / name)
                    mask.save(masks_dir / name)
                    samples.append({
                        "image": f"images/{name}", 
                        "mask": f"masks/{name}",
                        "fields": len(bboxes)
                    })
            except Exception as e:
                LOGGER.warning("Pulando %s devido a erro: %s", pdf_path, e)
                
    manifest = {"image_size": IMAGE_SIZE, "samples": samples}
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest

def image_tensor(image: Image.Image, augment: bool = False):
    torch, _ = require_torch()
    image = image.convert("L").resize((IMAGE_SIZE, IMAGE_SIZE))
    if augment:
        image = ImageEnhance.Contrast(image).enhance(random.uniform(.8, 1.2))
    data = torch.frombuffer(bytearray(image.tobytes()), dtype=torch.uint8)
    return data.reshape(1, IMAGE_SIZE, IMAGE_SIZE).float().div_(255.0)


def augment_date_field(image: Image.Image, mask: Image.Image, rng: random.Random = random) -> tuple[Image.Image, Image.Image]:
    """Insere um exemplo rotulado de ``Data: ____``, favorecendo o rodape.

    A maior parte do corpus e digitalizada e, sem OCR, nao produz rotulos
    automaticos. A sintese evita que esse caso importante fique sem exemplos.
    """
    image = image.convert("L").resize((IMAGE_SIZE, IMAGE_SIZE)).copy()
    mask = mask.convert("L").resize((IMAGE_SIZE, IMAGE_SIZE)).copy()
    draw, mask_draw = ImageDraw.Draw(image), ImageDraw.Draw(mask)
    font = ImageFont.load_default()
    y = rng.randint(round(IMAGE_SIZE * .70), round(IMAGE_SIZE * .94))
    x = rng.randint(18, round(IMAGE_SIZE * .35))
    label = rng.choice(("Data:", "DATA:", "Data: "))
    label_box = draw.textbbox((x, y), label, font=font)
    line_x = label_box[2] + rng.randint(4, 12)
    line_width = rng.randint(round(IMAGE_SIZE * .16), round(IMAGE_SIZE * .42))
    line_y = y + rng.randint(8, 12)
    tone = rng.randint(0, 55)
    draw.text((x, y), label, fill=tone, font=font)
    variant = rng.random()
    if variant < .34:
        draw.line((line_x, line_y, min(IMAGE_SIZE - 8, line_x + line_width), line_y), fill=tone, width=rng.randint(1, 2))
        right = min(IMAGE_SIZE - 8, line_x + line_width)
    elif variant < .67:
        underscores = "_" * max(5, line_width // 6)
        draw.text((line_x, y), underscores, fill=tone, font=font)
        right = min(IMAGE_SIZE - 8, line_x + line_width)
    else:
        # Formato usado pelo LibreOffice no formulario da UEPG.
        template = "___ de _____________ de 20___"
        draw.text((line_x, y), template, fill=tone, font=font)
        right = min(IMAGE_SIZE - 8, draw.textbbox((line_x, y), template, font=font)[2])
    if variant < .67:
        mask_draw.rectangle((line_x, max(0, line_y - 18), right, min(IMAGE_SIZE - 1, line_y + 2)), fill=255)
    else:
        # Mantem dia, mes e ano como componentes independentes na mascara.
        cursor = line_x
        for part in ("___", " de ", "_____________", " de 20", "___"):
            part_right = draw.textbbox((cursor, y), part, font=font)[2]
            if "_" in part:
                mask_draw.rectangle(
                    (cursor, max(0, line_y - 18), part_right, min(IMAGE_SIZE - 1, line_y + 2)),
                    fill=255,
                )
            cursor = part_right
    return image, mask

def train(
    dataset_dir: Path,
    model_path: Path,
    epochs: int = 40,
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
    
    if resume_path:
        checkpoint = torch.load(resume_path, map_location=device, weights_only=True)
        model.load_state_dict(checkpoint["state_dict"])
        
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)
    
    # Calcular pos_weight baseado no desequilibrio de pixels
    target_pixels = [image_tensor(Image.open(dataset_dir / sample["mask"])) for sample in samples]
    positives = sum(float(mask.sum()) for mask in target_pixels)
    total_pixels = len(target_pixels) * IMAGE_SIZE * IMAGE_SIZE
    pos_weight = torch.tensor([min(50.0, max(1.0, (total_pixels - positives) / max(1.0, positives)))], device=device)
    
    model.train()
    for epoch in range(1, epochs + 1):
        random.shuffle(samples)
        total_loss = 0.0
        for sample in samples:
            source_image = Image.open(dataset_dir / sample["image"])
            source_mask = Image.open(dataset_dir / sample["mask"])
            if random.random() < .65:
                source_image, source_mask = augment_date_field(source_image, source_mask)
            img = image_tensor(source_image, augment=True).unsqueeze(0).to(device)
            mask = image_tensor(source_mask).unsqueeze(0).to(device)
            
            optimizer.zero_grad()
            logits = model(img)
            
            bce = functional.binary_cross_entropy_with_logits(logits, mask, pos_weight=pos_weight)
            prediction = torch.sigmoid(logits)
            intersection = (prediction * mask).sum()
            dice_loss = 1 - (2 * intersection + 1) / (prediction.sum() + mask.sum() + 1)
            loss = bce + dice_loss
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
            
        LOGGER.info("Epoca %d/%d, Loss: %.5f", epoch, epochs, total_loss / len(samples))
        
    model_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "image_size": IMAGE_SIZE}, model_path)

def mask_components(probabilities, threshold: float = DEFAULT_THRESHOLD, min_area: int = 10) -> list[dict[str, float]]:
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

class FieldDetector:
    def __init__(self, model_path: Path, threshold: float = DEFAULT_THRESHOLD):
        self.torch, _ = require_torch()
        self.device = self.torch.device("cuda" if self.torch.cuda.is_available() else "cpu")
        checkpoint = self.torch.load(model_path, map_location=self.device, weights_only=True)
        self.model = build_model().to(self.device)
        self.model.load_state_dict(checkpoint["state_dict"])
        self.model.eval()
        self.threshold = threshold
        self._inference_lock = threading.Lock()

    def detect(self, pdf_path: Path) -> list[dict[str, Any]]:
        results = []
        with tempfile.TemporaryDirectory() as temp:
            rendered = render_pdf(pdf_path, Path(temp))
            with pdfplumber.open(pdf_path) as pdf:
                for page_no, (img_path, page) in enumerate(zip(rendered, pdf.pages), 1):
                    image = Image.open(img_path).convert("L")
                    pw, ph = float(page.width), float(page.height)
                    
                    with self._inference_lock, self.torch.no_grad():
                        logits = self.model(image_tensor(image).unsqueeze(0).to(self.device))
                        probs = self.torch.sigmoid(logits)[0, 0].cpu().tolist()
                    
                    components = mask_components(probs, self.threshold)
                    page_results = []
                    for i, comp in enumerate(components):
                        page_results.append({
                            "page": page_no,
                            "x": comp["x"] * pw / IMAGE_SIZE,
                            "y": comp["y"] * ph / IMAGE_SIZE,
                            "width": comp["width"] * pw / IMAGE_SIZE,
                            "height": comp["height"] * ph / IMAGE_SIZE,
                            "confidence": round(comp["confidence"], 4),
                            "source": "neural_field"
                        })
                    # O modelo costuma ativar separadamente dia, mes e ano no
                    # padrao "Data: ___ de ___ de 20___". Se houver evidencia
                    # neural sobre esses trechos, consolida-os em um unico campo.
                    from converter import textual_segmented_fields
                    words = page.extract_words()
                    raw_page_results = list(page_results)
                    matched_detections: set[int] = set()
                    segmented_results = []
                    for segmented in textual_segmented_fields(page, words):
                        x0, y0, x1, y1 = segmented["bbox"]
                        touching = [
                            detection for detection in raw_page_results
                            if not (
                                detection["x"] + detection["width"] < x0
                                or x1 < detection["x"]
                                or detection["y"] + detection["height"] < y0
                                or y1 < detection["y"]
                            )
                        ]
                        if not touching:
                            continue
                        matched_detections.update(id(detection) for detection in touching)
                        segmented_results.append({
                            "page": page_no, "x": x0, "y": y0,
                            "width": x1 - x0, "height": y1 - y0,
                            "confidence": round(max(d["confidence"] for d in touching), 4),
                            "label": segmented["label"],
                            "type": segmented["type"],
                            "source": "neural_field",
                        })
                    page_results = [
                        detection for detection in raw_page_results
                        if id(detection) not in matched_detections
                    ] + segmented_results
                    results.extend(sorted(page_results, key=lambda box: (box["y"], box["x"])))
        return results

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    
    prep = sub.add_parser("prepare")
    prep.add_argument("pdf", nargs="+")
    prep.add_argument("-o", "--output", default="data/fields")
    
    t = sub.add_parser("train")
    t.add_argument("dataset")
    t.add_argument("-o", "--output", default="models/field_detector.pt")
    t.add_argument("--epochs", type=int, default=40)
    t.add_argument("--learning-rate", type=float, default=1e-3)
    t.add_argument("--resume", type=Path)
    
    args = parser.parse_args()
    
    if args.command == "prepare":
        files = []
        for p in args.pdf:
            path = Path(p)
            files.extend(path.rglob("*.pdf") if path.is_dir() else [path])
        create_dataset(files, Path(args.output))
    elif args.command == "train":
        train(
            Path(args.dataset), Path(args.output), epochs=args.epochs,
            learning_rate=args.learning_rate, resume_path=args.resume,
        )

if __name__ == "__main__":
    main()
