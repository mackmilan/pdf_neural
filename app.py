from __future__ import annotations

import os
from http.server import ThreadingHTTPServer

from auth import Identity, authenticator
from config import (
    EXECUTOR, FIELD_MODEL, JOBS, LOGGER, MAX_HTML_JSON_SIZE, MAX_JSON_SIZE,
    MAX_PDF_SIZE, NEURAL_ENABLED, NEURAL_MIN_CONFIDENCE, NEURAL_REQUIRED,
    NEURAL_THRESHOLD, PUBLIC_BASE_URL, ROOT, STATIC, TABLE_MODEL, TIMEOUT, WORKERS,
)
from database import db
from handler import Handler
import jobs as _jobs
from services import convert_pdf_bytes, get_detectors, render_neural_tables, run_neural_detection
from utils import (
    NoRedirect, deliver_callback, download_pdf, job_urls, json_safe, multipart_data,
    validate_public_url, write_json,
)
from validators import (
    FIELD_ALIGNS, FIELD_TYPES, optional_number, validate_category_query,
    validate_context_id, validate_fields_payload, validate_html_payload,
    validate_resource_name, validate_search_context, validate_submission_values, validate_boolean,
)

__all__ = [
    "EXECUTOR", "FIELD_MODEL", "Handler", "Identity", "JOBS", "LOGGER",
    "MAX_HTML_JSON_SIZE", "MAX_JSON_SIZE", "MAX_PDF_SIZE", "NEURAL_ENABLED",
    "NEURAL_MIN_CONFIDENCE", "NEURAL_REQUIRED", "NEURAL_THRESHOLD", "NoRedirect",
    "PUBLIC_BASE_URL", "ROOT", "STATIC", "TABLE_MODEL", "TIMEOUT", "WORKERS",
    "authenticator", "convert_pdf_bytes", "deliver_callback", "download_pdf",
    "db",
    "get_detectors", "job_urls", "json_safe", "multipart_data", "optional_number",
    "render_neural_tables", "run_api_job", "run_neural_detection",
    "validate_category_query", "validate_context_id", "validate_fields_payload",
    "validate_html_payload", "validate_public_url", "validate_resource_name",
    "validate_search_context", "validate_submission_values", "validate_boolean", "write_json",
]


def run_api_job(
    job: str,
    pdf_url: str,
    callback_url: str,
    reference: object,
    base_url: str,
    tenant_id: str | None = None,
    group_id: str | None = None,
    category_id: str | None = None,
    single_submission_per_user: bool = False,
    allow_document_page_submission: bool = False,
) -> None:
    _jobs.db = db
    _jobs.download_pdf = download_pdf
    _jobs.convert_pdf_bytes = convert_pdf_bytes
    _jobs.deliver_callback = deliver_callback
    _jobs.get_detectors = get_detectors
    _jobs.NEURAL_REQUIRED = NEURAL_REQUIRED
    _jobs.run_api_job(
        job, pdf_url, callback_url, reference, base_url,
        tenant_id, group_id, category_id, single_submission_per_user,
        allow_document_page_submission,
    )


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"PDF Neural em http://{host}:{port}")
    server = ThreadingHTTPServer((host, port), Handler)
    server.timeout = TIMEOUT
    server.serve_forever()


if __name__ == "__main__":
    main()
