from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from neural_table_detector import DEFAULT_THRESHOLD

load_dotenv()

ROOT = Path(__file__).parent.resolve()
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
TABLE_MODEL = Path(os.environ.get("TABLE_MODEL", ROOT / "models" / "uepg_table_detector.pt"))
FIELD_MODEL = Path(os.environ.get("FIELD_MODEL", ROOT / "models" / "field_detector.pt"))
NEURAL_THRESHOLD = float(os.environ.get("NEURAL_THRESHOLD", str(DEFAULT_THRESHOLD)))
NEURAL_MIN_CONFIDENCE = float(os.environ.get("NEURAL_MIN_CONFIDENCE", "0.65"))
NEURAL_ENABLED = os.environ.get("NEURAL_ENABLED", "true").lower() not in ("0", "false", "no")
NEURAL_REQUIRED = os.environ.get("NEURAL_REQUIRED", "false").lower() in ("1", "true", "yes")
EXECUTOR = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="pdf-job")
LOGGER = logging.getLogger("pdf-neural")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
