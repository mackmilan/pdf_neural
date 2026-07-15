from __future__ import annotations

import http.client
import json
import ipaddress
import shutil
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from config import LOGGER, MAX_PDF_SIZE, PUBLIC_BASE_URL

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


def multipart_data(content_type: str, body: bytes) -> tuple[str, bytes, str, str, str, str, str, str]:
    marker = "boundary="
    if marker not in content_type:
        raise ValueError("Requisicao multipart invalida")
    boundary = content_type.split(marker, 1)[1].strip().strip('"').encode()
    pdf_name, pdf_data, url = "", b"", ""
    tenant_id, group_id, category_id = "", "", ""
    single_submission_per_user, allow_document_page_submission = "", ""
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
        elif b'name="category_id"' in head:
            category_id = data.decode("utf-8", "replace").strip()
        elif b'name="single_submission_per_user"' in head:
            single_submission_per_user = data.decode("utf-8", "replace").strip()
        elif b'name="allow_document_page_submission"' in head:
            allow_document_page_submission = data.decode("utf-8", "replace").strip()
    return (
        pdf_name, pdf_data, url, tenant_id, group_id, category_id,
        single_submission_per_user, allow_document_page_submission,
    )
def _resolve_public_url(raw_url: str) -> tuple[str, str, int]:
    """Valida a URL, resolve o DNS uma unica vez e retorna (url, ip_seguro, porta).

    Todos os enderecos retornados precisam ser globais; o IP devolvido e usado
    para fixar a conexao (evita DNS rebinding/TOCTOU entre validacao e request)."""
    parsed = urllib.parse.urlsplit(raw_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Informe uma URL HTTP ou HTTPS valida")
    if parsed.username or parsed.password:
        raise ValueError("URLs com credenciais nao sao permitidas")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Nao foi possivel localizar o servidor da URL") from exc
    safe_ip = None
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("URLs locais ou de rede privada nao sao permitidas")
        if safe_ip is None:
            safe_ip = address[4][0]
    if safe_ip is None:
        raise ValueError("Nao foi possivel localizar o servidor da URL")
    return urllib.parse.urlunsplit(parsed), safe_ip, port


def validate_public_url(raw_url: str) -> str:
    url, _ip, _port = _resolve_public_url(raw_url)
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Conecta ao IP previamente validado, mantendo o Host original nos headers."""

    def __init__(self, host, *args, pinned_ip=None, **kwargs):
        super().__init__(host, *args, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self):
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Igual a _PinnedHTTPConnection, mas preserva SNI e validacao de certificado
    contra o hostname original ao aplicar o TLS sobre o IP fixado."""

    def __init__(self, host, *args, pinned_ip=None, **kwargs):
        super().__init__(host, *args, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self):
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
            sock = self.sock
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, pinned_ip, **kwargs):
        super().__init__(**kwargs)
        self._pinned_ip = pinned_ip

    def http_open(self, req):
        return self.do_open(self._connection, req)

    def _connection(self, host, **kwargs):
        return _PinnedHTTPConnection(host, pinned_ip=self._pinned_ip, **kwargs)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, pinned_ip, **kwargs):
        super().__init__(**kwargs)
        self._pinned_ip = pinned_ip

    def https_open(self, req):
        return self.do_open(self._connection, req, context=self._context)

    def _connection(self, host, **kwargs):
        return _PinnedHTTPSConnection(host, pinned_ip=self._pinned_ip, **kwargs)


def _pinned_opener(pinned_ip: str) -> urllib.request.OpenerDirector:
    """Opener que recusa redirects e conecta apenas ao IP validado."""
    return urllib.request.build_opener(
        NoRedirect, _PinnedHTTPHandler(pinned_ip), _PinnedHTTPSHandler(pinned_ip),
    )


def download_pdf(raw_url: str) -> tuple[str, bytes]:
    LOGGER.debug("Validando URL para download: %s", raw_url)
    url = validate_public_url(raw_url)
    headers = {"User-Agent": "PDF-Neural/1.0", "Accept": "application/pdf"}
    for attempt in range(6):
        try:
            LOGGER.info("Baixando PDF (tentativa %d): %s", attempt + 1, url)
            # Revalida e fixa o IP a cada tentativa/redirect, inclusive resolvendo o DNS.
            url, safe_ip, _port = _resolve_public_url(url)
            response = _pinned_opener(safe_ip).open(urllib.request.Request(url, headers=headers), timeout=20)
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
            # Revalida e fixa o IP a cada tentativa, inclusive resolvendo o DNS.
            url, safe_ip, _port = _resolve_public_url(callback_url)
            request = urllib.request.Request(
                url, data=body, method="POST",
                headers={"Content-Type": "application/json", "User-Agent": "PDF-Neural/1.0"},
            )
            # Redirects sao recusados e a conexao fica presa ao IP validado, para
            # que uma URL publica nao redirecione a requisicao para a rede interna.
            with _pinned_opener(safe_ip).open(request, timeout=20) as response:
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
