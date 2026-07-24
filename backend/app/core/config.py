from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from backend.app.ml.ocr import (
    DEFAULT_DPI as OCR_DEFAULT_DPI,
    DEFAULT_LANG as OCR_DEFAULT_LANG,
    DEFAULT_MIN_CONFIDENCE as OCR_DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MIN_WORDS as OCR_DEFAULT_MIN_WORDS,
    DEFAULT_MODE as OCR_DEFAULT_MODE,
)
from backend.app.ml.tables import DEFAULT_THRESHOLD

load_dotenv()

ROOT = Path(os.environ.get("APP_ROOT", Path(__file__).resolve().parents[3])).resolve()
JOBS = ROOT / "output" / "jobs"
STATIC = ROOT / "static"
MAX_PDF_SIZE = 30 * 1024 * 1024
MAX_JSON_SIZE = 64 * 1024
MAX_HTML_JSON_SIZE = 8 * 1024 * 1024
TIMEOUT = int(os.environ.get("TIMEOUT", "60"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
GOTENBERG_URL = os.environ.get(
    "GOTENBERG_URL",
    "http://yjcd2rmuvgkjyjo6odj5fuy4.2.25.177.136.sslip.io:3010/",
).rstrip("/")
WORKERS = int(os.environ.get("PDF_WORKERS", "2"))
TABLE_MODEL = Path(os.environ.get("TABLE_MODEL", ROOT / "models" / "table_detector.pt"))
FIELD_MODEL = Path(os.environ.get("FIELD_MODEL", ROOT / "models" / "field_detector.pt"))
FIELD_MODELS = [
    Path(item.strip())
    for item in os.environ.get("FIELD_MODELS", "").split(",")
    if item.strip()
] or [FIELD_MODEL]
NEURAL_THRESHOLD = float(os.environ.get("NEURAL_THRESHOLD", str(DEFAULT_THRESHOLD)))
NEURAL_MIN_CONFIDENCE = float(os.environ.get("NEURAL_MIN_CONFIDENCE", "0.65"))
NEURAL_ENABLED = os.environ.get("NEURAL_ENABLED", "true").lower() not in ("0", "false", "no")
NEURAL_REQUIRED = os.environ.get("NEURAL_REQUIRED", "false").lower() in ("1", "true", "yes")
# OCR: ligado por padrao, mas so entra em acao quando ha um motor instalado e a
# pagina nao traz camada de texto (modo "auto"). Use "always" para reconhecer
# tambem paginas que ja tem texto proprio.
OCR_ENABLED = os.environ.get("OCR_ENABLED", "true").lower() not in ("0", "false", "no")
OCR_ENGINE = os.environ.get("OCR_ENGINE", "auto").strip().lower()
OCR_MODE = os.environ.get("OCR_MODE", OCR_DEFAULT_MODE).strip().lower()
OCR_LANG = os.environ.get("OCR_LANG", OCR_DEFAULT_LANG).strip()
OCR_DPI = int(os.environ.get("OCR_DPI", str(OCR_DEFAULT_DPI)))
OCR_MIN_CONFIDENCE = float(os.environ.get("OCR_MIN_CONFIDENCE", str(OCR_DEFAULT_MIN_CONFIDENCE)))
OCR_MIN_WORDS = int(os.environ.get("OCR_MIN_WORDS", str(OCR_DEFAULT_MIN_WORDS)))
EXECUTOR = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="pdf-job")
LOGGER = logging.getLogger("pdf-neural")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
