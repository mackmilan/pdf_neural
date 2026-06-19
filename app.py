from __future__ import annotations

import json
import html
import ipaddress
import logging
import mimetypes
import math
import os
import re
import socket
import shutil
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from converter import convert
from neural_table_detector import DEFAULT_THRESHOLD, TableDetector

ROOT = Path(__file__).parent.resolve()
JOBS = ROOT / "output" / "jobs"
STATIC = ROOT / "static"
MAX_PDF_SIZE = 30 * 1024 * 1024
MAX_JSON_SIZE = 64 * 1024
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
WORKERS = int(os.environ.get("PDF_WORKERS", "2"))
TABLE_MODEL = Path(os.environ.get("TABLE_MODEL", ROOT / "models" / "uepg_table_detector.pt"))
NEURAL_THRESHOLD = float(os.environ.get("NEURAL_THRESHOLD", str(DEFAULT_THRESHOLD)))
NEURAL_MIN_CONFIDENCE = float(os.environ.get("NEURAL_MIN_CONFIDENCE", "0.65"))
NEURAL_ENABLED = os.environ.get("NEURAL_ENABLED", "true").lower() not in ("0", "false", "no")
NEURAL_REQUIRED = os.environ.get("NEURAL_REQUIRED", "false").lower() in ("1", "true", "yes")
EXECUTOR = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="pdf-job")
LOGGER = logging.getLogger("pdf-neural")
JOBS.mkdir(parents=True, exist_ok=True)
_TABLE_DETECTOR: TableDetector | None = None
_TABLE_DETECTOR_LOCK = threading.Lock()


def write_json(path: Path, value: object) -> None:
    """Write state atomically so status readers never see partial JSON."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def get_table_detector() -> TableDetector | None:
    """Carrega o checkpoint uma unica vez, na primeira conversao."""
    global _TABLE_DETECTOR
    if not NEURAL_ENABLED:
        return None
    if _TABLE_DETECTOR is None:
        with _TABLE_DETECTOR_LOCK:
            if _TABLE_DETECTOR is None:
                if not TABLE_MODEL.is_file():
                    raise FileNotFoundError(f"Modelo neural nao encontrado: {TABLE_MODEL}")
                _TABLE_DETECTOR = TableDetector(TABLE_MODEL, NEURAL_THRESHOLD, NEURAL_MIN_CONFIDENCE)
                LOGGER.info("Modelo neural carregado: %s", TABLE_MODEL)
    return _TABLE_DETECTOR


def render_neural_tables(result: Path, tables: list[dict]) -> None:
    """Projeta a grade detectada nas paginas HTML usando as cores de origem.
    
    Nota: Esta funcao agora e um no-op pois a renderizacao foi movida para converter.py.
    Mantida para compatibilidade se chamada externamente.
    """
    pass


def run_neural_detection(source: Path, result: Path) -> list[dict]:
    """Detecta tabelas e garante que neural-tables.json exista para o ZIP."""
    output = result / "neural-tables.json"
    if output.is_file():
        try:
            return json.loads(output.read_text(encoding="utf-8"))
        except Exception:
            pass
    write_json(output, [])
    return []


def job_urls(job: str, base_url: str) -> dict[str, str]:
    base = (PUBLIC_BASE_URL or base_url).rstrip("/")
    return {
        "preview_url": f"{base}/jobs/{job}/html/index.html",
        "download_url": f"{base}/jobs/{job}/resultado.zip",
    }


def multipart_data(content_type: str, body: bytes) -> tuple[str, bytes, str]:
    marker = "boundary="
    if marker not in content_type:
        raise ValueError("Requisicao multipart invalida")
    boundary = content_type.split(marker, 1)[1].strip().strip('"').encode()
    pdf_name, pdf_data, url = "", b"", ""
    for part in body.split(b"--" + boundary):
        head, sep, data = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        data = data.rstrip(b"\r\n-")
        if b'name="pdf"' in head and b"filename=" in head:
            filename = head.split(b"filename=", 1)[-1].split(b"\r\n", 1)[0].strip(b'"').decode("utf-8", "replace")
            if filename:
                pdf_name, pdf_data = Path(filename).name, data
        elif b'name="url"' in head:
            url = data.decode("utf-8", "replace").strip()
    return pdf_name, pdf_data, url


def validate_public_url(raw_url: str) -> str:
    parsed = urllib.parse.urlsplit(raw_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Informe uma URL HTTP ou HTTPS valida")
    if parsed.username or parsed.password:
        raise ValueError("URLs com credenciais nao sao permitidas")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Nao foi possivel localizar o servidor da URL") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("URLs locais ou de rede privada nao sao permitidas")
    return urllib.parse.urlunsplit(parsed)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def download_pdf(raw_url: str) -> tuple[str, bytes]:
    url = validate_public_url(raw_url)
    opener = urllib.request.build_opener(NoRedirect)
    headers = {"User-Agent": "PDF-Neural/1.0", "Accept": "application/pdf"}
    for _ in range(6):
        try:
            response = opener.open(urllib.request.Request(url, headers=headers), timeout=20)
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308) and exc.headers.get("Location"):
                url = validate_public_url(urllib.parse.urljoin(url, exc.headers["Location"]))
                continue
            raise ValueError(f"O servidor respondeu HTTP {exc.code}") from exc
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_PDF_SIZE:
            response.close()
            raise ValueError("O PDF remoto excede o limite de 30 MB")
        chunks, total = [], 0
        with response:
            while chunk := response.read(64 * 1024):
                total += len(chunk)
                if total > MAX_PDF_SIZE:
                    raise ValueError("O PDF remoto excede o limite de 30 MB")
                chunks.append(chunk)
        data = b"".join(chunks)
        name = Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).name or "documento.pdf"
        return (name if name.lower().endswith(".pdf") else name + ".pdf"), data
    raise ValueError("A URL possui redirecionamentos demais")


def deliver_callback(callback_url: str, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    error: Exception | None = None
    for attempt in range(3):
        try:
            # Revalidate on every attempt, including DNS resolution.
            url = validate_public_url(callback_url)
            request = urllib.request.Request(
                url, data=body, method="POST",
                headers={"Content-Type": "application/json", "User-Agent": "PDF-Neural/1.0"},
            )
            # Redirects are rejected to prevent a public callback URL from
            # redirecting the request into the local network.
            with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
                if not 200 <= response.status < 300:
                    raise ValueError(f"Callback respondeu HTTP {response.status}")
            return
        except Exception as exc:
            error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Falha ao enviar callback: {error}")


def run_api_job(job: str, pdf_url: str, callback_url: str, reference: object, base_url: str) -> None:
    work = JOBS / job
    status_file = work / "status.json"
    common = {"job_id": job, "reference": reference}
    try:
        write_json(status_file, {**common, "status": "processing"})
        name, data = download_pdf(pdf_url)
        if not data.startswith(b"%PDF"):
            raise ValueError("O conteudo recebido nao e um PDF valido")
        source = work / (Path(name).stem + ".pdf")
        source.write_bytes(data)
        result = convert(source, work / "html", table_detector=get_table_detector())
        neural_tables = run_neural_detection(source, result)
        archive = work / "resultado.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in result.rglob("*"):
                if file.is_file():
                    zf.write(file, file.relative_to(result))
        fields = json.loads((result / "fields.json").read_text(encoding="utf-8"))
        tables = json.loads((result / "tables.json").read_text(encoding="utf-8"))
        payload = {**common, "status": "completed", "result": {"fields": fields, "tables": tables, "neural_tables": neural_tables, **job_urls(job, base_url)}}
        write_json(status_file, payload)
    except Exception as exc:
        payload = {**common, "status": "failed", "error": str(exc)}
        write_json(status_file, payload)

    try:
        deliver_callback(callback_url, payload)
        write_json(status_file, {**payload, "callback_status": "delivered"})
    except Exception as exc:
        LOGGER.exception("Callback do job %s falhou", job)
        write_json(status_file, {**payload, "callback_status": "failed", "callback_error": str(exc)})


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, value: object) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def base_url(self) -> str:
        proto = self.headers.get("X-Forwarded-Proto", "http").split(",", 1)[0].strip()
        if proto not in ("http", "https"):
            proto = "http"
        return f"{proto}://{self.headers.get('Host', '127.0.0.1:8000')}"

    def send_file(self, path: Path, disposition: str | None = None) -> None:
        if not path.is_file():
            self.send_error(404); return
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.send_header("Content-Length", str(path.stat().st_size)); self.end_headers()
        with path.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile)

    def do_GET(self) -> None:
        path = urllib.parse.unquote(self.path.split("?", 1)[0])
        if path == "/":
            return self.send_file(STATIC / "index.html")
        if path in ("/docs", "/docs/"):
            return self.send_file(STATIC / "swagger.html")
        if path == "/openapi.json":
            return self.send_file(STATIC / "openapi.json")
        parts = Path(path.lstrip("/")).parts
        if len(parts) == 3 and parts[:2] == ("api", "jobs") and re.fullmatch(r"[0-9a-f]{32}", parts[2]):
            status = JOBS / parts[2] / "status.json"
            if status.is_file():
                return self.send_json(200, json.loads(status.read_text(encoding="utf-8")))
            return self.send_json(404, {"error": "Job nao encontrado"})
        if len(parts) >= 3 and parts[0] == "jobs" and all(p not in ("..", ".") for p in parts):
            return self.send_file(JOBS.joinpath(*parts[1:]))
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/api/jobs":
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > MAX_JSON_SIZE:
                    raise ValueError("Corpo JSON ausente ou maior que 64 KB")
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("Content-Type deve ser application/json")
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError("O corpo JSON deve ser um objeto")
                pdf_url = validate_public_url(str(request.get("pdf_url", "")))
                callback_url = validate_public_url(str(request.get("callback_url", "")))
                reference = request.get("reference")
                job = uuid.uuid4().hex
                work = JOBS / job
                work.mkdir()
                initial = {"job_id": job, "reference": reference, "status": "queued"}
                write_json(work / "status.json", initial)
                EXECUTOR.submit(run_api_job, job, pdf_url, callback_url, reference, self.base_url())
                return self.send_json(202, {**initial, "status_url": f"{self.base_url()}/api/jobs/{job}"})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.send_json(400, {"error": str(exc)})
            except Exception:
                LOGGER.exception("Erro ao criar job")
                return self.send_json(500, {"error": "Erro interno ao criar job"})
        if self.path != "/api/convert":
            self.send_error(404); return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_PDF_SIZE + 1024 * 1024:
                raise ValueError("O limite e 30 MB")
            name, data, url = multipart_data(self.headers.get("Content-Type", ""), self.rfile.read(length))
            if not data and url:
                name, data = download_pdf(url)
            if not data:
                raise ValueError("Envie um arquivo PDF ou informe uma URL")
            if not data.startswith(b"%PDF"):
                raise ValueError("O conteudo recebido nao e um PDF valido")
            job = uuid.uuid4().hex
            work = JOBS / job; work.mkdir()
            source = work / (Path(name).stem + ".pdf"); source.write_bytes(data)
            result = convert(source, work / "html", table_detector=get_table_detector())
            neural_tables = run_neural_detection(source, result)
            archive = work / "resultado.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                for file in result.rglob("*"):
                    if file.is_file(): zf.write(file, file.relative_to(result))
            fields = json.loads((result / "fields.json").read_text(encoding="utf-8"))
            tables = json.loads((result / "tables.json").read_text(encoding="utf-8"))
            payload = json.dumps({"preview": f"/jobs/{job}/html/index.html", "download": f"/jobs/{job}/resultado.zip", "fields": fields, "tables": tables, "neural_tables": neural_tables}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)
        except Exception as exc:
            payload = json.dumps({"error": str(exc)}).encode()
            self.send_response(400); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(payload)


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"PDF Neural em http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
