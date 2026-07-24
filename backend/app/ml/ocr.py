"""Reconhecimento de texto (OCR) para paginas de PDF sem camada de texto.

O conversor so reproduz — e so consegue rotular campos a partir de — o texto que
o PDF declara. Em documentos digitalizados a pagina inteira e uma imagem e
``page.extract_words()`` devolve uma lista vazia: nao ha texto, nao ha rotulos e
o HTML sai apenas com o scan. Este modulo reconhece o texto dessas paginas e
devolve palavras no mesmo formato do pdfplumber, ja convertidas para pontos, de
modo que o restante do pipeline (rotulos, tabelas, heuristicas de campo e
renderizacao) funcione sem alteracao.

Motores suportados, testados nesta ordem quando ``OCR_ENGINE=auto``:

- ``tesseract`` (``pip install pytesseract`` + binario ``tesseract`` no sistema);
- ``rapidocr`` (``pip install rapidocr-onnxruntime``, sem binario externo).

Sem nenhum dos dois instalados a conversao segue normalmente: o extrator nao e
criado e nada muda no resultado.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("pdf-neural.ocr")

DEFAULT_DPI = 300
DEFAULT_LANG = "por"
DEFAULT_MIN_CONFIDENCE = 0.45
DEFAULT_MIN_WORDS = 5
DEFAULT_MODE = "auto"
OCR_FONTNAME = "OCR"
OCR_SOURCE = "ocr"
# Proporcao entre a altura da caixa reconhecida e o corpo da fonte: a caixa
# inclui ascendentes e descendentes, entao o tamanho fica um pouco menor.
FONT_SIZE_RATIO = 0.86


class OcrUnavailable(RuntimeError):
    """Nenhum motor de OCR utilizavel esta instalado."""


@dataclass
class OcrWord:
    """Palavra reconhecida, em pixels da imagem renderizada."""

    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    confidence: float


def split_line_into_words(
    text: str,
    x0: float,
    top: float,
    x1: float,
    bottom: float,
    confidence: float,
) -> list[OcrWord]:
    """Divide uma linha reconhecida em palavras.

    Motores que devolvem a linha inteira (RapidOCR) nao informam a caixa de cada
    palavra. A largura e distribuida proporcionalmente a posicao dos caracteres,
    aproximacao suficiente para associar rotulos a campos.
    """
    if not text.strip():
        return []
    width = max(0.0, float(x1) - float(x0))
    total = len(text) or 1
    return [
        OcrWord(
            match.group(),
            x0 + width * match.start() / total,
            top,
            x0 + width * match.end() / total,
            bottom,
            confidence,
        )
        for match in re.finditer(r"\S+", text)
    ]


class TesseractEngine:
    """Motor baseado no Tesseract, que ja devolve a caixa de cada palavra."""

    name = "tesseract"

    def __init__(self, lang: str = DEFAULT_LANG):
        import pytesseract

        self._pytesseract = pytesseract
        self.lang = lang
        # Falha aqui, na criacao, quando o binario nao esta instalado.
        pytesseract.get_tesseract_version()

    def recognize(self, image: Any) -> list[OcrWord]:
        data = self._pytesseract.image_to_data(
            image, lang=self.lang, output_type=self._pytesseract.Output.DICT
        )
        words: list[OcrWord] = []
        for index, raw_text in enumerate(data.get("text", [])):
            text = str(raw_text).strip()
            if not text:
                continue
            try:
                confidence = float(data["conf"][index])
                left = float(data["left"][index])
                top = float(data["top"][index])
                width = float(data["width"][index])
                height = float(data["height"][index])
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            # conf -1 marca blocos, paragrafos e linhas: nao sao palavras.
            if confidence < 0:
                continue
            words.append(OcrWord(text, left, top, left + width, top + height, confidence / 100))
        return words


class RapidOcrEngine:
    """Motor ONNX instalavel apenas por pip, util onde nao ha binario externo."""

    name = "rapidocr"

    def __init__(self, lang: str = DEFAULT_LANG):
        from rapidocr_onnxruntime import RapidOCR

        self.lang = lang
        self._engine = RapidOCR()

    @staticmethod
    def _lines(raw: Any) -> list[tuple[Any, str, float]]:
        """Normaliza os formatos ja usados pelas versoes do rapidocr."""
        if raw is None:
            return []
        if isinstance(raw, tuple):  # (resultado, tempos)
            raw = raw[0]
        if raw is None:
            return []
        boxes = getattr(raw, "boxes", None)
        if boxes is not None:  # API baseada em objeto
            texts = getattr(raw, "txts", []) or []
            scores = getattr(raw, "scores", []) or []
            return [
                (boxes[index], str(texts[index]), float(scores[index]) if index < len(scores) else 1.0)
                for index in range(min(len(boxes), len(texts)))
            ]
        lines: list[tuple[Any, str, float]] = []
        for item in raw:
            if len(item) < 2:
                continue
            box, text = item[0], str(item[1])
            score = float(item[2]) if len(item) > 2 else 1.0
            lines.append((box, text, score))
        return lines

    def recognize(self, image: Any) -> list[OcrWord]:
        import numpy

        raw = self._engine(numpy.asarray(image.convert("RGB")))
        words: list[OcrWord] = []
        for box, text, score in self._lines(raw):
            try:
                xs = [float(point[0]) for point in box]
                ys = [float(point[1]) for point in box]
            except (TypeError, ValueError, IndexError):
                continue
            if not xs or not ys:
                continue
            words.extend(split_line_into_words(text, min(xs), min(ys), max(xs), max(ys), score))
        return words


ENGINES: dict[str, type] = {
    engine.name: engine for engine in (TesseractEngine, RapidOcrEngine)
}


def load_engine(name: str = "auto", lang: str = DEFAULT_LANG) -> Any:
    """Cria o primeiro motor disponivel, do melhor para o mais simples."""
    requested = (name or "auto").strip().lower()
    if requested in {"", "auto"}:
        candidates = list(ENGINES.values())
    elif requested in ENGINES:
        candidates = [ENGINES[requested]]
    else:
        raise OcrUnavailable(f"Motor de OCR desconhecido: {name}")

    failures: list[str] = []
    for factory in candidates:
        try:
            return factory(lang)
        except Exception as exc:  # ImportError, binario ausente, modelo ausente
            failures.append(f"{factory.name}: {exc}")
    raise OcrUnavailable(
        "Nenhum motor de OCR disponivel ("
        + "; ".join(failures)
        + "). Execute: pip install -r requirements-ocr.txt"
    )


def render_page_image(pdf_path: str | Path, page_number: int, dpi: int = DEFAULT_DPI) -> Any:
    """Rasteriza uma pagina (1-based) para uma imagem PIL em memoria."""
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise OcrUnavailable("PyMuPDF nao esta instalado. Execute: pip install PyMuPDF") from exc
    from PIL import Image

    document = fitz.open(str(pdf_path))
    try:
        page = document[page_number - 1]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
        return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    finally:
        document.close()


def merge_ocr_words(
    native: list[dict[str, Any]],
    recognized: list[dict[str, Any]],
    overlap_ratio: float = 0.3,
) -> list[dict[str, Any]]:
    """Acrescenta palavras do OCR sem duplicar o que o PDF ja declara."""
    if not recognized:
        return native
    if not native:
        return list(recognized)
    boxes = [
        (float(word["x0"]), float(word["top"]), float(word["x1"]), float(word["bottom"]))
        for word in native
    ]
    merged = list(native)
    for word in recognized:
        wx0, wtop = float(word["x0"]), float(word["top"])
        wx1, wbottom = float(word["x1"]), float(word["bottom"])
        area = max(0.0, wx1 - wx0) * max(0.0, wbottom - wtop)
        if area <= 0:
            continue
        covered = any(
            max(0.0, min(wx1, bx1) - max(wx0, bx0)) * max(0.0, min(wbottom, bbottom) - max(wtop, btop))
            >= area * overlap_ratio
            for (bx0, btop, bx1, bbottom) in boxes
        )
        if not covered:
            merged.append(word)
    return sorted(merged, key=lambda item: (round(float(item["top"]), 1), float(item["x0"])))


class OcrExtractor:
    """Reconhece o texto de paginas digitalizadas e o devolve como palavras."""

    def __init__(
        self,
        engine: Any,
        mode: str = DEFAULT_MODE,
        dpi: int = DEFAULT_DPI,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        min_words: int = DEFAULT_MIN_WORDS,
    ):
        self.engine = engine
        self.mode = (mode or DEFAULT_MODE).strip().lower()
        self.dpi = max(72, int(dpi))
        self.min_confidence = float(min_confidence)
        self.min_words = max(0, int(min_words))

    @property
    def engine_name(self) -> str:
        return str(getattr(self.engine, "name", "desconhecido"))

    def should_run(self, words: list[dict[str, Any]], page: Any) -> bool:
        """No modo ``auto``, so paginas com imagem e praticamente sem texto."""
        if self.mode == "always":
            return True
        if len(words) >= self.min_words:
            return False
        return bool(getattr(page, "images", None))

    def page_words(
        self,
        pdf_path: str | Path,
        page_number: int,
        page_width: float,
        page_height: float,
    ) -> list[dict[str, Any]]:
        """Palavras reconhecidas na pagina, em pontos, no formato do pdfplumber."""
        image = render_page_image(pdf_path, page_number, self.dpi)
        recognized = self.engine.recognize(image)
        image_width = float(getattr(image, "width", 0) or 0)
        image_height = float(getattr(image, "height", 0) or 0)
        scale_x = float(page_width) / image_width if image_width else 72 / self.dpi
        scale_y = float(page_height) / image_height if image_height else 72 / self.dpi

        words: list[dict[str, Any]] = []
        for word in recognized:
            text = str(word.text).strip()
            if not text or float(word.confidence) < self.min_confidence:
                continue
            x0 = max(0.0, float(word.x0) * scale_x)
            x1 = min(float(page_width), float(word.x1) * scale_x)
            top = max(0.0, float(word.top) * scale_y)
            bottom = min(float(page_height), float(word.bottom) * scale_y)
            if x1 - x0 <= 0 or bottom - top <= 0:
                continue
            words.append({
                "text": text,
                "x0": x0,
                "x1": x1,
                "top": top,
                "bottom": bottom,
                "doctop": top,
                "upright": True,
                "size": round((bottom - top) * FONT_SIZE_RATIO, 2),
                "fontname": OCR_FONTNAME,
                "non_stroking_color": (0, 0, 0),
                "source": OCR_SOURCE,
                "confidence": round(float(word.confidence), 3),
            })
        words.sort(key=lambda item: (round(item["top"], 1), item["x0"]))
        LOGGER.info(
            "OCR (%s) reconheceu %d palavras na pagina %d", self.engine_name, len(words), page_number
        )
        return words


def create_extractor(
    engine: str = "auto",
    lang: str = DEFAULT_LANG,
    mode: str = DEFAULT_MODE,
    dpi: int = DEFAULT_DPI,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    min_words: int = DEFAULT_MIN_WORDS,
) -> OcrExtractor:
    """Atalho que resolve o motor e devolve o extrator pronto."""
    return OcrExtractor(
        load_engine(engine, lang),
        mode=mode,
        dpi=dpi,
        min_confidence=min_confidence,
        min_words=min_words,
    )
