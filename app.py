from __future__ import annotations

import json
import html
import hashlib
import ipaddress
import logging
import mimetypes
import math
import os
import re
import socket
import shutil
import threading
import tempfile
import time
import urllib.parse
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import load_dotenv

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

from converter import ConversionResult, convert
from database import db
from neural_table_detector import DEFAULT_THRESHOLD, TableDetector
from neural_field_detector import FieldDetector

ROOT = Path(__file__).parent.resolve()
JOBS = ROOT / "output" / "jobs"
STATIC = ROOT / "static"
MAX_PDF_SIZE = 30 * 1024 * 1024
MAX_JSON_SIZE = 64 * 1024
TIMEOUT = int(os.environ.get("TIMEOUT", "60"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
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
_TABLE_DETECTOR: TableDetector | None = None
_FIELD_DETECTOR: FieldDetector | None = None
_DETECTOR_LOCK = threading.Lock()


def json_safe(value: object) -> object:
    """Converte valores MongoDB/datetime recursivamente para JSON."""
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if value.__class__.__name__ == "ObjectId":
        return str(value)
    return value


def write_json(path: Path, value: object) -> None:
    """Write state atomically so status readers never see partial JSON."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def get_detectors() -> tuple[TableDetector | None, FieldDetector | None]:
    """Carrega os modelos uma única vez."""
    global _TABLE_DETECTOR, _FIELD_DETECTOR
    if not NEURAL_ENABLED:
        return None, None
    if _TABLE_DETECTOR is None or _FIELD_DETECTOR is None:
        with _DETECTOR_LOCK:
            if _TABLE_DETECTOR is None and TABLE_MODEL.is_file():
                try:
                    _TABLE_DETECTOR = TableDetector(TABLE_MODEL, NEURAL_THRESHOLD, NEURAL_MIN_CONFIDENCE)
                    LOGGER.info("Modelo neural de tabelas carregado: %s", TABLE_MODEL)
                except Exception:
                    LOGGER.exception("Erro ao carregar detector de tabelas")

            if _FIELD_DETECTOR is None and FIELD_MODEL.is_file():
                try:
                    _FIELD_DETECTOR = FieldDetector(FIELD_MODEL)
                    LOGGER.info("Modelo neural de campos carregado: %s", FIELD_MODEL)
                except Exception:
                    LOGGER.exception("Erro ao carregar detector de campos")
    return _TABLE_DETECTOR, _FIELD_DETECTOR


def render_neural_tables(result: Path, tables: list[dict]) -> None:
    """Projeta a grade detectada nas paginas HTML usando as cores de origem."""
    if not tables:
        return
    index_file = result / "index.html"
    if not index_file.is_file():
        return
    
    pages_with_tables: dict[int, list[dict]] = {}
    for table in tables:
        try:
            p = int(table["page"])
            if p >= 1:
                pages_with_tables.setdefault(p, []).append(table)
        except (KeyError, ValueError, TypeError):
            continue

    if not pages_with_tables:
        return

    import re
    import html
    import math

    document = index_file.read_text(encoding="utf-8")
    
    for p, p_tables in pages_with_tables.items():
        overlays = []
        for table in p_tables:
            confidence = float(table.get("confidence", 0))
            rows = int(table.get("row_count", 0))
            cols = int(table.get("column_count", 0))
            label = f"Tabela neural {confidence:.0%}, {rows} linhas, {cols} colunas"
            table_id = html.escape(str(table.get("id", "neural-table")), quote=True)
            rendered_lines = []
            for line_index, line in enumerate(table.get("lines", []), 1):
                try:
                    lx, ly = float(line["x"]), float(line["y"])
                    lw, lh = float(line.get("width", 0)), float(line.get("height", 0))
                    line_thickness = max(.25, float(line.get("line_width", .5)))
                except (KeyError, TypeError, ValueError):
                    continue
                color = str(line.get("color", "#000000"))
                if not re.fullmatch(r"#[0-9a-fA-F]{6}", color) or not all(math.isfinite(v) for v in (lx, ly, lw, lh, line_thickness)):
                    continue
                css_w = lw if lw > 0 else line_thickness
                css_h = lh if lh > 0 else line_thickness
                rendered_lines.append(
                    f'<div class="neural-table-line" data-neural-line="{line_index}" '
                    f'style="left:{lx:.2f}px;top:{ly:.2f}px;width:{css_w:.2f}px;'
                    f'height:{css_h:.2f}px;background:{color}"></div>'
                )
            overlays.append(
                f'<div class="neural-table-structure" data-neural-table="{table_id}" '
                f'aria-label="{html.escape(label, quote=True)}" title="{html.escape(label, quote=True)}">'
                f'{"".join(rendered_lines)}</div>'
            )
        
        # Inserir no final da seção da página
        pattern = f'data-page="{p}"[^>]*>(.*?)</section>'
        match = re.search(pattern, document, re.DOTALL)
        if match:
            old_section = match.group(0)
            if "</section>" in old_section:
                new_section = old_section.replace("</section>", "".join(overlays) + "</section>")
                document = document.replace(old_section, new_section)

    index_file.write_text(document, encoding="utf-8")


def run_neural_detection(source: Path, result: Path) -> list[dict]:
    """Detecta tabelas e garante que neural-tables.json exista para o ZIP."""
    LOGGER.info("Iniciando detecção neural de tabelas: %s", source.name)
    table_detector, _ = get_detectors()
    if table_detector:
        try:
            tables = table_detector.detect(source, result / "neural-tables.json")
            LOGGER.info("Detecção neural concluída: %d tabelas encontradas", len(tables))
            return tables
        except Exception:
            LOGGER.exception("Falha na detecção neural para %s", source.name)
    
    output = result / "neural-tables.json"
    if output.is_file():
        try:
            return json.loads(output.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def job_urls(job: str, base_url: str) -> dict[str, str]:
    base = (PUBLIC_BASE_URL or base_url).rstrip("/")
    return {
        "preview_url": f"{base}/jobs/{job}/html/index.html",
    }


def convert_pdf_bytes(data: bytes, filename: str, job_id: str) -> ConversionResult:
    """Executa ferramentas que exigem um path em area temporaria e nao gera artefatos persistentes."""
    safe_name = Path(filename).name or "documento.pdf"
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"
    with tempfile.TemporaryDirectory(prefix="pdf-neural-") as temporary:
        source = Path(temporary) / safe_name
        source.write_bytes(data)
        table_detector, field_detector = get_detectors()
        result = convert(source, table_detector=table_detector, field_detector=field_detector, job_id=job_id)
        if not isinstance(result, ConversionResult):
            raise RuntimeError("A conversao nao retornou os artefatos em memoria")
        return result


def multipart_data(content_type: str, body: bytes) -> tuple[str, bytes, str, str, str]:
    marker = "boundary="
    if marker not in content_type:
        raise ValueError("Requisicao multipart invalida")
    boundary = content_type.split(marker, 1)[1].strip().strip('"').encode()
    pdf_name, pdf_data, url, tenant_id, group_id = "", b"", "", "", ""
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
        elif b'name="tenant_id"' in head:
            tenant_id = data.decode("utf-8", "replace").strip()
        elif b'name="group_id"' in head:
            group_id = data.decode("utf-8", "replace").strip()
    return pdf_name, pdf_data, url, tenant_id, group_id


def validate_context_id(value: object, label: str) -> str:
    identifier = str(value or "").strip()
    if not re.fullmatch(r"[0-9a-f]{32}", identifier):
        raise ValueError(f"{label} invalido")
    return identifier


def validate_resource_name(value: object, label: str) -> str:
    name = str(value or "").strip()
    if not 1 <= len(name) <= 120:
        raise ValueError(f"{label} deve possuir entre 1 e 120 caracteres")
    return name


def validate_search_context(query: dict[str, list[str]]) -> tuple[str, str | None]:
    tenant_id = validate_context_id(query.get("tenant_id", [""])[0], "tenant_id")
    group_value = query.get("group_id", [""])[0]
    group_id = validate_context_id(group_value, "group_id") if group_value else None
    return tenant_id, group_id


FIELD_TYPES = {"text", "date", "time", "email", "tel", "number", "password", "checkbox", "select", "textarea"}


def validate_fields_payload(value: object) -> list[dict]:
    """Valida e normaliza campos editados pela interface."""
    if not isinstance(value, list) or len(value) > 1000:
        raise ValueError("fields deve ser uma lista com no maximo 1000 itens")
    fields = []
    used_names = set()
    for index, raw in enumerate(value, 1):
        if not isinstance(raw, dict):
            raise ValueError(f"Campo {index} invalido")
        name = str(raw.get("name", "")).strip()[:64]
        label = str(raw.get("label", "")).strip()[:160]
        kind = str(raw.get("type", "text"))
        if not name or not re.fullmatch(r"[a-zA-Z0-9_\-]+", name) or name in used_names:
            raise ValueError(f"Nome invalido ou duplicado no campo {index}")
        if not label or kind not in FIELD_TYPES:
            raise ValueError(f"Rotulo ou tipo invalido no campo {index}")
        try:
            page = int(raw.get("page"))
            x, y = float(raw.get("x")), float(raw.get("y"))
            width, height = float(raw.get("width")), float(raw.get("height"))
        except (TypeError, ValueError):
            raise ValueError(f"Coordenadas invalidas no campo {index}") from None
        if page < 1 or not all(math.isfinite(v) for v in (x, y, width, height)):
            raise ValueError(f"Coordenadas invalidas no campo {index}")
        if x < 0 or y < 0 or width <= 0 or height <= 0 or width > 10000 or height > 10000:
            raise ValueError(f"Dimensoes invalidas no campo {index}")
        used_names.add(name)
        fields.append({
            "name": name, "label": label, "type": kind, "page": page,
            "x": x, "y": y, "width": width, "height": height,
            "source": str(raw.get("source", "manual"))[:32],
            "required": bool(raw.get("required", False)),
            "href": f"index.html#{name}",
        })
    return fields


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
    LOGGER.debug("Validando URL para download: %s", raw_url)
    url = validate_public_url(raw_url)
    opener = urllib.request.build_opener(NoRedirect)
    headers = {"User-Agent": "PDF-Neural/1.0", "Accept": "application/pdf"}
    for attempt in range(6):
        try:
            LOGGER.info("Baixando PDF (tentativa %d): %s", attempt + 1, url)
            response = opener.open(urllib.request.Request(url, headers=headers), timeout=20)
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308) and exc.headers.get("Location"):
                url = validate_public_url(urllib.parse.urljoin(url, exc.headers["Location"]))
                LOGGER.debug("Redirecionando para: %s", url)
                continue
            LOGGER.error("Erro HTTP ao baixar PDF: %d", exc.code)
            raise ValueError(f"O servidor respondeu HTTP {exc.code}") from exc
        except Exception as exc:
            LOGGER.error("Erro ao baixar PDF: %s", str(exc))
            raise
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_PDF_SIZE:
            response.close()
            LOGGER.error("PDF remoto muito grande: %s bytes", length)
            raise ValueError("O PDF remoto excede o limite de 30 MB")
        chunks, total = [], 0
        with response:
            while chunk := response.read(64 * 1024):
                total += len(chunk)
                if total > MAX_PDF_SIZE:
                    LOGGER.error("PDF remoto excedeu limite durante leitura: %d bytes", total)
                    raise ValueError("O PDF remoto excede o limite de 30 MB")
                chunks.append(chunk)
        data = b"".join(chunks)
        name = Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).name or "documento.pdf"
        filename = (name if name.lower().endswith(".pdf") else name + ".pdf")
        LOGGER.info("Download concluído: %s (%d bytes)", filename, len(data))
        return filename, data
    raise ValueError("A URL possui redirecionamentos demais")


def deliver_callback(callback_url: str, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    error: Exception | None = None
    for attempt in range(3):
        try:
            LOGGER.info("Enviando callback (tentativa %d): %s", attempt + 1, callback_url)
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
            LOGGER.info("Callback entregue com sucesso")
            return
        except Exception as exc:
            error = exc
            LOGGER.warning("Falha na tentativa %d de callback: %s", attempt + 1, str(exc))
            if attempt < 2:
                time.sleep(2 ** attempt)
    LOGGER.error("Falha definitiva ao enviar callback após 3 tentativas")
    raise RuntimeError(f"Falha ao enviar callback: {error}")


def run_api_job(job: str, pdf_url: str, callback_url: str, reference: object, base_url: str, tenant_id: str | None = None, group_id: str | None = None) -> None:
    LOGGER.info("Iniciando background job: %s", job)
    common = {"job_id": job, "reference": reference, "tenant_id": tenant_id, "group_id": group_id}

    def update_job_status(payload: dict):
        if not db or not db.is_available():
            LOGGER.error("Tentativa de atualizar status do job %s mas banco de dados está indisponível", job)
            raise RuntimeError("Servico de banco de dados indisponivel")
        db.save_job(job, payload)

    try:
        update_job_status({**common, "status": "processing"})
        name, data = download_pdf(pdf_url)
        if not data.startswith(b"%PDF"):
            raise ValueError("O conteudo recebido nao e um PDF valido")
        if NEURAL_REQUIRED:
            table_detector, field_detector = get_detectors()
            if not table_detector or not field_detector:
                raise RuntimeError("Detectores neurais obrigatorios nao disponiveis")

        LOGGER.info("Iniciando conversão do PDF para job %s", job)
        result = convert_pdf_bytes(data, name, job)
        content_hash = hashlib.sha256(data).hexdigest()
        identity = db.save_document(
            job_id=job,
            html_content=result.html_content,
            fields=result.fields,
            tables=result.tables,
            pages=result.pages,
            neural_tables=result.neural_tables,
            metadata={"filename": name, "pdf_url": pdf_url, "reference": reference, "content_hash": content_hash},
            content_hash=content_hash,
            tenant_id=tenant_id,
            group_id=group_id,
        )
        LOGGER.info("Documento salvo no MongoDB para job %s", job)

        identity = identity or {"document_id": content_hash, "version": 1, "job_id": job, "is_current": True}
        payload = {**common, "document_id": identity["document_id"], "version": identity["version"], "status": "completed", "result": {"document_id": identity["document_id"], "version": identity["version"], "fields": result.fields, "tables": result.tables, "neural_tables": result.neural_tables, **job_urls(job, base_url)}}
        update_job_status(payload)
        LOGGER.info("Background job %s concluído com sucesso", job)
    except Exception as exc:
        LOGGER.exception("Falha no background job %s", job)
        payload = {**common, "status": "failed", "error": str(exc)}
        update_job_status(payload)

    try:
        deliver_callback(callback_url, payload)
        update_job_status({**payload, "callback_status": "delivered"})
    except Exception as exc:
        LOGGER.exception("Callback do job %s falhou", job)
        update_job_status({**payload, "callback_status": "failed", "callback_error": str(exc)})


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
        parsed_request = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed_request.path)
        query = urllib.parse.parse_qs(parsed_request.query)
        if path == "/":
            return self.send_file(STATIC / "index.html")
        if path in ("/docs", "/docs/"):
            return self.send_file(STATIC / "swagger.html")
        if path == "/openapi.json":
            return self.send_file(STATIC / "openapi.json")
        if path == "/api/documents":
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query)
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
            docs = db.list_documents(tenant_id=tenant_id, group_id=group_id)
            return self.send_json(200, json_safe(docs))

        if path == "/api/tenants":
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            return self.send_json(200, json_safe(db.list_tenants()))
        
        if path == "/api/jobs":
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query)
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
            jobs = db.list_jobs(tenant_id=tenant_id, group_id=group_id)
            for j in jobs:
                j["_id"] = str(j["_id"])
                if "created_at" in j: j["created_at"] = j["created_at"].isoformat()
                if "updated_at" in j: j["updated_at"] = j["updated_at"].isoformat()
            return self.send_json(200, jobs)

        parts = Path(path.lstrip("/")).parts
        if len(parts) == 4 and parts[:2] == ("api", "tenants") and re.fullmatch(r"[0-9a-f]{32}", parts[2]) and parts[3] == "groups":
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            return self.send_json(200, json_safe(db.list_groups(parts[2])))
        document_id_pattern = r"(?:[0-9a-f]{32}|[0-9a-f]{64})"
        if len(parts) == 4 and parts[:2] == ("api", "documents") and re.fullmatch(r"[0-9a-f]{64}", parts[2]) and parts[3] == "versions":
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query)
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
            return self.send_json(200, json_safe(db.list_document_versions(parts[2], tenant_id, group_id)))

        if len(parts) == 5 and parts[:2] == ("api", "documents") and re.fullmatch(r"[0-9a-f]{64}", parts[2]) and parts[3] == "versions" and parts[4].isdigit():
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query)
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
            doc = db.get_document_summary(parts[2], int(parts[4]), tenant_id, group_id)
            return self.send_json(200, json_safe(doc)) if doc else self.send_json(404, {"error": "Versao nao encontrada"})

        if len(parts) == 3 and parts[:2] == ("api", "documents") and re.fullmatch(document_id_pattern, parts[2]):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query)
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
            doc = db.get_document_summary(parts[2], tenant_id=tenant_id, group_id=group_id)
            if doc:
                return self.send_json(200, json_safe(doc))
            return self.send_json(404, {"error": "Documento nao encontrado"})

        if len(parts) == 3 and parts[:2] == ("api", "jobs") and re.fullmatch(r"[0-9a-f]{32}", parts[2]):
            job_id = parts[2]
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query)
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
            job_data = db.get_job(job_id, tenant_id, group_id)
            if job_data:
                job_data["_id"] = str(job_data["_id"])
                if "created_at" in job_data: job_data["created_at"] = job_data["created_at"].isoformat()
                if "updated_at" in job_data: job_data["updated_at"] = job_data["updated_at"].isoformat()
                return self.send_json(200, job_data)
            return self.send_json(404, {"error": "Job nao encontrado"})
        if len(parts) >= 3 and parts[0] == "jobs" and all(p not in ("..", ".") for p in parts):
            job_id = parts[1]
            if len(parts) == 4 and parts[2] == "html" and parts[3] == "index.html":
                if not db or not db.is_available():
                    return self.send_error(503, "Servico de banco de dados indisponivel")
                doc = db.get_document(job_id)
                if not doc or "html_content" not in doc:
                    return self.send_error(404, "Documento nao encontrado")
                content = doc["html_content"].encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            return self.send_error(404)
        self.send_error(404)

    def do_PUT(self) -> None:
        path = urllib.parse.unquote(self.path.split("?", 1)[0])
        parts = Path(path.lstrip("/")).parts
        if (
            len(parts) == 6 and parts[:2] == ("api", "documents")
            and re.fullmatch(r"[0-9a-f]{64}", parts[2]) and parts[3] == "versions"
            and parts[4].isdigit() and parts[5] == "current"
        ):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            selected = db.set_current_version(parts[2], int(parts[4]))
            if not selected:
                return self.send_json(404, {"error": "Versao nao encontrada"})
            return self.send_json(200, json_safe(selected))
        if not (
            len(parts) == 4 and parts[:2] == ("api", "documents")
            and re.fullmatch(r"[0-9a-f]{32}", parts[2]) and parts[3] == "fields"
        ):
            return self.send_error(404)
        if not db or not db.is_available():
            return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > MAX_JSON_SIZE:
                raise ValueError("Corpo JSON ausente ou maior que 64 KB")
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Content-Type deve ser application/json")
            request = json.loads(self.rfile.read(length))
            fields = validate_fields_payload(request.get("fields") if isinstance(request, dict) else None)
            result = db.update_document_fields(parts[2], fields)
            if result is None or getattr(result, "matched_count", 1) == 0:
                return self.send_json(404, {"error": "Documento nao encontrado"})
            job_data = db.get_job(parts[2])
            if job_data and isinstance(job_data.get("result"), dict):
                updated = dict(job_data)
                updated.pop("_id", None)
                updated["result"] = {**job_data["result"], "fields": fields}
                db.save_job(parts[2], updated)
            return self.send_json(200, {"job_id": parts[2], "fields": fields})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self.send_json(400, {"error": str(exc)})

    def do_DELETE(self) -> None:
        path = urllib.parse.unquote(self.path.split("?", 1)[0])
        parts = Path(path.lstrip("/")).parts
        if not (
            len(parts) == 3 and parts[:2] == ("api", "documents")
            and re.fullmatch(r"(?:[0-9a-f]{32}|[0-9a-f]{64})", parts[2])
        ):
            return self.send_error(404)
        if not db or not db.is_available():
            return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
        try:
            if not db.delete_document(parts[2]):
                return self.send_json(404, {"error": "Documento nao encontrado"})
            return self.send_json(200, {"job_id": parts[2], "deleted": True})
        except Exception:
            LOGGER.exception("Erro ao excluir documento %s", parts[2])
            return self.send_json(500, {"error": "Erro interno ao excluir documento"})

    def do_POST(self) -> None:
        if self.path == "/api/tenants" or re.fullmatch(r"/api/tenants/[0-9a-f]{32}/groups", self.path):
            try:
                if not db or not db.is_available():
                    return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > MAX_JSON_SIZE or self.headers.get_content_type() != "application/json":
                    raise ValueError("Envie um corpo JSON valido de ate 64 KB")
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError("O corpo JSON deve ser um objeto")
                name = validate_resource_name(request.get("name"), "name")
                metadata = request.get("metadata", {})
                if not isinstance(metadata, dict):
                    raise ValueError("metadata deve ser um objeto")
                if self.path == "/api/tenants":
                    return self.send_json(201, json_safe(db.create_tenant(name, metadata)))
                tenant_id = self.path.split("/")[3]
                group = db.create_group(tenant_id, name, metadata)
                return self.send_json(201, json_safe(group)) if group else self.send_json(404, {"error": "Tenant nao encontrado"})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.send_json(400, {"error": str(exc)})
        if self.path == "/api/jobs":
            try:
                LOGGER.info("Recebida requisição POST /api/jobs")
                if not db or not db.is_available():
                    return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
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
                tenant_id = validate_context_id(request.get("tenant_id"), "tenant_id")
                group_id = validate_context_id(request.get("group_id"), "group_id") if request.get("group_id") else None
                if not db.group_belongs_to_tenant(tenant_id, group_id):
                    raise ValueError("tenant_id deve existir e group_id, quando informado, deve pertencer ao tenant")
                job = uuid.uuid4().hex
                LOGGER.info("Criando background job %s para URL: %s", job, pdf_url)
                initial = {"job_id": job, "reference": reference, "status": "queued", "tenant_id": tenant_id, "group_id": group_id}
                db.save_job(job, initial)
                EXECUTOR.submit(run_api_job, job, pdf_url, callback_url, reference, self.base_url(), tenant_id, group_id)
                status_query = urllib.parse.urlencode({key: value for key, value in {"tenant_id": tenant_id, "group_id": group_id}.items() if value})
                return self.send_json(202, {**initial, "status_url": f"{self.base_url()}/api/jobs/{job}?{status_query}"})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                LOGGER.warning("Requisição inválida para /api/jobs: %s", str(exc))
                return self.send_json(400, {"error": str(exc)})
            except Exception:
                LOGGER.exception("Erro ao criar job")
                return self.send_json(500, {"error": "Erro interno ao criar job"})
        if self.path != "/api/convert":
            self.send_error(404); return
        try:
            LOGGER.info("Iniciando requisicao /api/convert")
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_PDF_SIZE + 1024 * 1024:
                raise ValueError("O limite e 30 MB")
            body = self.rfile.read(length)
            name, data, url, tenant_id, group_id = multipart_data(self.headers.get("Content-Type", ""), body)
            tenant_id = validate_context_id(tenant_id, "tenant_id") if tenant_id else None
            group_id = validate_context_id(group_id, "group_id") if group_id else None
            if (tenant_id or group_id) and not db.group_belongs_to_tenant(tenant_id, group_id):
                raise ValueError("tenant_id deve existir e group_id, quando informado, deve pertencer ao tenant")
            if not data and url:
                LOGGER.info("Baixando PDF remoto: %s", url)
                name, data = download_pdf(url)
            if not data:
                raise ValueError("Envie um arquivo PDF ou informe uma URL")
            if not data.startswith(b"%PDF"):
                raise ValueError("O conteudo recebido nao e um PDF valido")
            
            job = uuid.uuid4().hex
            LOGGER.info("Iniciando job síncrono: %s", job)
            result = convert_pdf_bytes(data, name, job)
            content_hash = hashlib.sha256(data).hexdigest()
            identity = db.save_document(
                job_id=job,
                html_content=result.html_content,
                fields=result.fields,
                tables=result.tables,
                pages=result.pages,
                neural_tables=result.neural_tables,
                metadata={"filename": name, "sync": True, "content_hash": content_hash},
                content_hash=content_hash,
                tenant_id=tenant_id,
                group_id=group_id,
            )
            identity = identity or {"document_id": content_hash, "version": 1, "job_id": job, "is_current": True}
            db.save_job(job, {
                "job_id": job,
                "status": "completed",
                "result": {
                    "fields": result.fields,
                    "tables": result.tables,
                    "neural_tables": result.neural_tables,
                    "preview": f"/jobs/{job}/html/index.html",
                    "document_id": identity["document_id"],
                    "version": identity["version"],
                },
                "sync": True,
                "tenant_id": tenant_id,
                "group_id": group_id,
            })
            LOGGER.info("Documento e job salvos no MongoDB para job síncrono %s", job)
            
            payload = json.dumps({
                "job_id": job,
                "document_id": identity["document_id"],
                "version": identity["version"],
                "preview": f"/jobs/{job}/html/index.html",
                "fields": result.fields,
                "tables": result.tables,
                "neural_tables": result.neural_tables,
                "tenant_id": tenant_id,
                "group_id": group_id,
            }, ensure_ascii=False).encode("utf-8")
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            LOGGER.info("Job síncrono concluído: %s", job)
        except ValueError as exc:
            payload = json.dumps({"error": str(exc)}).encode()
            self.send_response(400); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(payload)
        except Exception as exc:
            LOGGER.exception("Erro ao processar /api/convert")
            payload = json.dumps({"error": str(exc)}).encode()
            self.send_response(500); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(payload)


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"PDF Neural em http://{host}:{port}")
    server = ThreadingHTTPServer((host, port), Handler)
    server.timeout = TIMEOUT
    server.serve_forever()
