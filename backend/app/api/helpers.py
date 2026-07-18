from __future__ import annotations

import re
import urllib.request
import uuid
from datetime import datetime
from json import JSONDecodeError

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from backend.app.core.config import GOTENBERG_URL, MAX_JSON_SIZE, MAX_PDF_SIZE, STATIC
from backend.app.utils.validation import validate_context_id, validate_resource_name


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "no-referrer",
}
PREVIEW_CSP = (
    "default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; "
    "font-src data:; script-src 'unsafe-inline'; connect-src 'none'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
)


async def json_body(
    request: Request,
    max_size: int = MAX_JSON_SIZE,
    message: str = "Envie um corpo JSON valido de ate 64 KB",
) -> dict:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    length = int(request.headers.get("content-length", "0") or "0")
    if length <= 0 or length > max_size or content_type != "application/json":
        raise HTTPException(status_code=400, detail={"error": message})
    try:
        payload = await request.json()
    except JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail={"error": "O corpo JSON deve ser um objeto"})
    return payload


def preview_html_response(content: str) -> HTMLResponse:
    return HTMLResponse(
        content=content,
        headers={**SECURITY_HEADERS, "Content-Security-Policy": PREVIEW_CSP},
    )


def base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", "http").split(",", 1)[0].strip()
    if proto not in ("http", "https"):
        proto = "http"
    return f"{proto}://{request.headers.get('host', '127.0.0.1:8000')}"


def safe_static_response(path: str) -> FileResponse:
    candidate = (STATIC / path.lstrip("/")).resolve()
    if STATIC.resolve() not in candidate.parents and candidate != STATIC.resolve():
        raise HTTPException(status_code=404, detail={"error": "Arquivo nao encontrado"})
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail={"error": "Arquivo nao encontrado"})
    return FileResponse(candidate)


def gotenberg_page_options(html_content: str) -> dict[str, str]:
    match = re.search(
        r'data-page-width="([0-9.]+)"[^>]*data-page-height="([0-9.]+)"',
        html_content,
        re.IGNORECASE,
    )
    options = {
        "marginTop": "0",
        "marginBottom": "0",
        "marginLeft": "0",
        "marginRight": "0",
        "scale": "1",
        "printBackground": "true",
        "preferCssPageSize": "true",
        "emulatedMediaType": "print",
        "waitDelay": "500ms",
    }
    if match:
        width_pt, height_pt = float(match.group(1)), float(match.group(2))
        options["paperWidth"] = f"{width_pt / 72:.6f}in"
        options["paperHeight"] = f"{height_pt / 72:.6f}in"
    return options


def multipart_html(html_content: str) -> tuple[str, bytes]:
    boundary = f"----pdf-neural-{uuid.uuid4().hex}"
    payload = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="files"; filename="index.html"\r\n'
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
    ).encode("utf-8") + html_content.encode("utf-8")
    for name, value in gotenberg_page_options(html_content).items():
        payload += (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}"
        ).encode("utf-8")
    payload += f"\r\n--{boundary}--\r\n".encode("utf-8")
    return f"multipart/form-data; boundary={boundary}", payload


def pdf_filename(value: object) -> str:
    filename = str(value or "documento.pdf").strip().replace("\\", "_").replace("/", "_")
    filename = re.sub(r"[^a-zA-Z0-9_.-]+", "_", filename).strip("._")
    if not filename:
        filename = "documento.pdf"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    return filename[:180]


def html_for_pdf_payload(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("html_content deve ser uma string")
    html_content = value.strip()
    if not html_content:
        raise ValueError("html_content nao pode ser vazio")
    if len(html_content.encode("utf-8")) > MAX_PDF_SIZE:
        raise ValueError("html_content excede o limite de 30 MB")
    if not re.search(r"<html[\s>]", html_content, re.IGNORECASE) or not re.search(r"</html\s*>", html_content, re.IGNORECASE):
        raise ValueError("html_content deve conter um documento HTML completo")
    if re.search(r"<\s*(?:iframe|object|embed|base|link)\b", html_content, re.IGNORECASE):
        raise ValueError("html_content contem elementos nao permitidos")
    if re.search(r"<\s*meta\b[^>]*\bhttp-equiv\b", html_content, re.IGNORECASE):
        raise ValueError("html_content contem elementos nao permitidos")
    if re.search(r"<[^>]*?\son[a-z]+\s*=", html_content, re.IGNORECASE):
        raise ValueError("html_content contem manipuladores de evento nao permitidos")
    if re.search(r"(?:javascript|vbscript)\s*:", html_content, re.IGNORECASE):
        raise ValueError("html_content contem URIs de script nao permitidos")
    if re.search(r"data\s*:\s*text\s*/\s*html", html_content, re.IGNORECASE):
        raise ValueError("html_content contem URIs de dados nao permitidos")
    for match in re.finditer(r"<script\b([^>]*)>(.*?)</script\s*>", html_content, re.IGNORECASE | re.DOTALL):
        attributes, script_body = match.group(1), match.group(2)
        normalized_script = re.sub(r"\s+", " ", script_body).strip()
        if attributes.strip() or "const resizePages=()" not in normalized_script or "ResizeObserver(resizePages)" not in normalized_script:
            raise ValueError("html_content contem scripts nao permitidos")
    return html_content


def convert_html_with_gotenberg(html_content: str, filename: str = "documento.pdf") -> bytes:
    content_type, body = multipart_html(html_content)
    request = urllib.request.Request(
        f"{GOTENBERG_URL}/forms/chromium/convert/html",
        data=body,
        headers={
            "Content-Type": content_type,
            "Accept": "application/pdf",
            "Gotenberg-Output-Filename": filename,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        pdf = response.read()
    if not pdf.startswith(b"%PDF"):
        raise ValueError("Gotenberg nao retornou um PDF valido")
    return pdf


def parse_query_date(value: str, label: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{label} deve estar no formato YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"{label} invalido") from None


def body_context_id(payload: dict, key: str, label: str | None = None, required: bool = True) -> str | None:
    value = payload.get(key)
    if not value and not required:
        return None
    try:
        return validate_context_id(value, label or key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc


def body_resource_name(payload: dict, key: str, label: str | None = None) -> str:
    try:
        return validate_resource_name(payload.get(key), label or key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
