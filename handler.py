from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from auth import AuthenticationError, Identity, authenticator
from config import EXECUTOR, GOTENBERG_URL, LOGGER, MAX_HTML_JSON_SIZE, MAX_JSON_SIZE, MAX_PDF_SIZE, STATIC
from database import db
from jobs import run_api_job
from services import convert_pdf_bytes
from utils import download_pdf, json_safe, multipart_data, validate_public_url
from validators import (
    validate_category_query, validate_context_id, validate_fields_payload,
    validate_format_norm, validate_html_payload, validate_resource_name, validate_search_context,
    validate_submission_values, validate_boolean,
)

class Handler(BaseHTTPRequestHandler):
    _identity: Identity | None = None

    SECURITY_HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Referrer-Policy": "no-referrer",
    }
    # Conteudo HTML derivado de PDF/edicao e servido na propria origem. Esta CSP
    # bloqueia canais de exfiltracao (fetch/XHR, imagens externas, formularios)
    # caso algum vetor de script escape da sanitizacao em validate_html_payload.
    PREVIEW_CSP = (
        "default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; "
        "font-src data:; script-src 'unsafe-inline'; connect-src 'none'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
    )

    def _emit_security_headers(self, csp: str | None = None) -> None:
        for header, value in self.SECURITY_HEADERS.items():
            self.send_header(header, value)
        if csp:
            self.send_header("Content-Security-Policy", csp)

    def send_json(self, status: int, value: object) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._emit_security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def authenticate(self) -> Identity | None:
        if self._identity is not None:
            return self._identity
        
        authorization = self.headers.get("Authorization")
        api_key = self.headers.get("X-API-Key")
        
        try:
            if api_key:
                self._identity = authenticator.authenticate_api_key(api_key)
            else:
                self._identity = authenticator.authenticate(authorization)
            return self._identity
        except AuthenticationError as exc:
            self.send_response(401)
            if not api_key:
                self.send_header("WWW-Authenticate", 'Bearer realm="pdf-neural"')
            payload = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return None

    def require_admin(self, identity: Identity) -> bool:
        if identity.has_role(authenticator.admin_role):
            return True
        self.send_json(403, {"error": "Role pdf-admin necessaria"})
        return False

    def authorize_context(
        self, identity: Identity, tenant_id: str | None, group_id: str | None = None,
        permission: str = "reader",
    ) -> bool:
        if identity.has_role(authenticator.admin_role):
            return True
        
        if not tenant_id:
            # Para usuários não-admin, exigimos tenant_id para validar o acesso específico.
            self.send_json(403, {"error": "Acesso negado: tenant_id obrigatorio para usuarios nao-admin"})
            return False

        # Se for autenticação via API Key, verificar restrições da chave
        key_tenant_id = identity.claims.get("tenant_id")
        key_group_id = identity.claims.get("group_id")
        
        if key_tenant_id:
            if key_tenant_id != tenant_id:
                self.send_json(403, {"error": "Esta API Key está restrita a outro tenant"})
                return False
            if key_group_id and key_group_id != group_id:
                self.send_json(403, {"error": "Esta API Key está restrita a outro grupo"})
                return False

        if db and db.is_available() and db.user_has_access(identity.subject, tenant_id, group_id, permission):
            return True
        self.send_json(403, {"error": "Usuario sem acesso ao tenant ou grupo solicitado"})
        return False

    def authorize_document_page_access(self, identity: Identity, document: dict) -> bool:
        """Exige vinculo exato ao tenant/grupo do documento no visualizador."""
        if identity.has_role(authenticator.admin_role):
            return True
        tenant_id = document.get("tenant_id")
        group_id = document.get("group_id")
        if not tenant_id:
            self.send_json(403, {"error": "Documento sem tenant vinculado"})
            return False
        if db and db.is_available():
            access_entries = db.list_user_access(identity.subject)
            for access in access_entries:
                if access.get("tenant_id") == tenant_id and access.get("group_id") == group_id:
                    return True
        self.send_json(403, {"error": "Usuario sem acesso ao tenant ou grupo do documento"})
        return False

    def base_url(self) -> str:
        proto = self.headers.get("X-Forwarded-Proto", "http").split(",", 1)[0].strip()
        if proto not in ("http", "https"):
            proto = "http"
        return f"{proto}://{self.headers.get('Host', '127.0.0.1:8000')}"

    @staticmethod
    def _parse_query_date(value: str, label: str) -> datetime | None:
        value = (value or "").strip()
        if not value:
            return None
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError(f"{label} deve estar no formato YYYY-MM-DD")
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"{label} invalido") from None

    def send_file(self, path: Path, disposition: str | None = None) -> None:
        if not path.is_file():
            self.send_error(404); return
        self.send_response(200)
        self._emit_security_headers()
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.send_header("Content-Length", str(path.stat().st_size)); self.end_headers()
        with path.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile)

    @staticmethod
    def _pdf_filename(value: object) -> str:
        filename = str(value or "documento.pdf").strip().replace("\\", "_").replace("/", "_")
        filename = re.sub(r"[^a-zA-Z0-9_.-]+", "_", filename).strip("._")
        if not filename:
            filename = "documento.pdf"
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        return filename[:180]

    @staticmethod
    def _gotenberg_page_options(html_content: str) -> dict[str, str]:
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

    @staticmethod
    def _multipart_html(html_content: str) -> tuple[str, bytes]:
        boundary = f"----pdf-neural-{uuid.uuid4().hex}"
        payload = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="files"; filename="index.html"\r\n'
            "Content-Type: text/html; charset=utf-8\r\n\r\n"
        ).encode("utf-8") + html_content.encode("utf-8")
        for name, value in Handler._gotenberg_page_options(html_content).items():
            payload += (
                f"\r\n--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}"
            ).encode("utf-8")
        payload += f"\r\n--{boundary}--\r\n".encode("utf-8")
        return f"multipart/form-data; boundary={boundary}", payload

    @staticmethod
    def _html_for_pdf_payload(value: object) -> str:
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

    def send_pdf_bytes(self, payload: bytes, filename: str) -> None:
        self.send_response(200)
        self._emit_security_headers()
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def convert_html_with_gotenberg(self, html_content: str, filename: str = "documento.pdf") -> bytes:
        content_type, body = self._multipart_html(html_content)
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

    def do_GET(self) -> None:
        parsed_request = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed_request.path)
        query = urllib.parse.parse_qs(parsed_request.query)
        if path == "/":
            return self.send_file(STATIC / "index.html")
        if path in (
            "/documentos", "/documentos/",
            "/documentos-disponiveis", "/documentos-disponiveis/",
            "/usuarios", "/usuarios/",
            "/submissoes", "/submissoes/",
            "/preenchidos", "/preenchidos/",
        ):
            return self.send_file(STATIC / "index.html")
        if re.fullmatch(r"/documento/(?:[0-9a-f]{32}|[0-9a-f]{64})/?", path):
            return self.send_file(STATIC / "index.html")
        if re.fullmatch(r"/submissao/[0-9a-f]{32}/?", path):
            return self.send_file(STATIC / "index.html")
        if path in ("/docs", "/docs/"):
            return self.send_file(STATIC / "swagger.html")
        if path == "/openapi.json":
            return self.send_file(STATIC / "openapi.json")
        if path == "/favicon.svg" or path == "/icons.svg" or path.startswith("/assets/"):
            candidate = (STATIC / path.lstrip("/")).resolve()
            if STATIC.resolve() in candidate.parents:
                return self.send_file(candidate)
            return self.send_error(404)
        if path == "/auth/config":
            return self.send_json(200, {
                "issuer": authenticator.issuer,
                "client_id": authenticator.audience,
            })
        public_document_match = re.fullmatch(r"/api/public/viewer/documents/([0-9a-f]{32}|[0-9a-f]{64})", path)
        if public_document_match:
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            document = db.get_document_summary(public_document_match.group(1))
            if not document or not document.get("allow_document_page_submission"):
                return self.send_json(404, {"error": "Documento nao encontrado"})
            metadata = document.get("metadata") or {}
            return self.send_json(200, json_safe({
                "document_id": document.get("document_id") or document.get("job_id"),
                "document_name": document.get("name") or metadata.get("filename") or "Documento",
            }))
        identity = self.authenticate()
        if identity is None:
            return
        if path == "/api/me":
            access = db.list_user_access(identity.subject) if db and db.is_available() else []
            return self.send_json(200, json_safe({
                "sub": identity.subject, "username": identity.username,
                "roles": sorted(identity.roles), "access": access,
            }))
        if path == "/api/users/access":
            if not self.require_admin(identity):
                return
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            return self.send_json(200, json_safe(db.list_all_user_access()))
        if path == "/api/admin/submissions":
            if not self.require_admin(identity):
                return
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query)
                category_id = validate_category_query(query)
                date_from = self._parse_query_date(query.get("date_from", [""])[0], "date_from")
                date_to = self._parse_query_date(query.get("date_to", [""])[0], "date_to")
                if date_to:
                    date_to = date_to + timedelta(days=1)
                user = query.get("user", [""])[0].strip()
                if len(user) > 255:
                    raise ValueError("user deve ter no maximo 255 caracteres")
                if category_id and tenant_id and (
                    not group_id or not db.category_belongs_to_group(tenant_id, group_id, category_id)
                ):
                    return self.send_json(400, {"error": "category_id deve pertencer ao group_id informado"})
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
            return self.send_json(200, json_safe(db.list_all_document_submissions(
                tenant_id=tenant_id,
                group_id=group_id,
                category_id=category_id,
                date_from=date_from,
                date_to=date_to,
                user=user or None,
            )))
        user_match = re.fullmatch(r"/api/users/([^/]+)/access", path)
        if user_match:
            if not self.require_admin(identity):
                return
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            return self.send_json(200, json_safe(db.list_user_access(urllib.parse.unquote(user_match.group(1)))))
        if path == "/api/documents":
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query, identity)
                category_id = validate_category_query(query)
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
            if category_id and tenant_id and (
                not group_id or not db.category_belongs_to_group(tenant_id, group_id, category_id)
            ):
                return self.send_json(400, {"error": "category_id deve pertencer ao group_id informado"})
            if not self.authorize_context(identity, tenant_id, group_id):
                return
            try:
                page = int(query.get("page", ["1"])[0])
                page_size = int(query.get("page_size", ["10"])[0])
            except (TypeError, ValueError):
                return self.send_json(400, {"error": "page e page_size devem ser numeros inteiros"})
            name = query.get("name", [""])[0].strip()
            if page < 1 or not 1 <= page_size <= 100:
                return self.send_json(400, {"error": "page deve ser maior que zero e page_size deve estar entre 1 e 100"})
            if len(name) > 255:
                return self.send_json(400, {"error": "name deve ter no maximo 255 caracteres"})
            result = db.list_documents(
                page=page, page_size=page_size, tenant_id=tenant_id,
                group_id=group_id, category_id=category_id, name=name or None,
            )
            return self.send_json(200, json_safe(result))

        if path == "/api/api-keys":
            if not self.require_admin(identity):
                return
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id = query.get("tenant_id", [None])[0]
                group_id = query.get("group_id", [None])[0]
                if not tenant_id:
                    return self.send_json(400, {"error": "tenant_id é obrigatório"})
                keys = db.list_api_keys(tenant_id, group_id)
                for k in keys:
                    if "created_at" in k: k["created_at"] = k["created_at"].isoformat()
                    if "revoked_at" in k: k["revoked_at"] = k["revoked_at"].isoformat()
                return self.send_json(200, keys)
            except Exception as exc:
                return self.send_json(400, {"error": str(exc)})

        if path == "/api/tenants":
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            tenants = db.list_tenants() if identity.has_role(authenticator.admin_role) else db.list_tenants_for_user(identity.subject)
            return self.send_json(200, json_safe(tenants))
        
        if path == "/api/jobs":
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query, identity)
                category_id = validate_category_query(query)
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
            if category_id and tenant_id and (
                not group_id or not db.category_belongs_to_group(tenant_id, group_id, category_id)
            ):
                return self.send_json(400, {"error": "category_id deve pertencer ao group_id informado"})
            if not self.authorize_context(identity, tenant_id, group_id):
                return
            jobs = db.list_jobs(tenant_id=tenant_id, group_id=group_id, category_id=category_id)
            for j in jobs:
                j["_id"] = str(j["_id"])
                if "created_at" in j: j["created_at"] = j["created_at"].isoformat()
                if "updated_at" in j: j["updated_at"] = j["updated_at"].isoformat()
            return self.send_json(200, jobs)

        parts = Path(path.lstrip("/")).parts
        if len(parts) == 4 and parts[:2] == ("api", "tenants") and re.fullmatch(r"[0-9a-f]{32}", parts[2]) and parts[3] == "groups":
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            if not identity.has_role(authenticator.admin_role) and not db.user_has_access(identity.subject, parts[2]):
                return self.send_json(403, {"error": "Acesso negado ao tenant"})
            groups = (
                db.list_groups(parts[2])
                if identity.has_role(authenticator.admin_role)
                else db.list_groups_for_user(identity.subject, parts[2])
            )
            return self.send_json(200, json_safe(groups))
        if (
            len(parts) == 6 and parts[:2] == ("api", "tenants")
            and re.fullmatch(r"[0-9a-f]{32}", parts[2]) and parts[3] == "groups"
            and re.fullmatch(r"[0-9a-f]{32}", parts[4]) and parts[5] == "categories"
        ):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            if not db.group_belongs_to_tenant(parts[2], parts[4]):
                return self.send_json(404, {"error": "Grupo nao encontrado no tenant"})
            if not self.authorize_context(identity, parts[2], parts[4]):
                return
            return self.send_json(200, json_safe(db.list_categories(parts[2], parts[4])))
        document_id_pattern = r"(?:[0-9a-f]{32}|[0-9a-f]{64})"
        if (
            len(parts) == 3 and parts[:3] == ("api", "viewer", "documents")
        ):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            subject = None if identity.has_role(authenticator.admin_role) else identity.subject
            return self.send_json(200, json_safe(db.list_submittable_documents_for_user(subject)))
        if (
            len(parts) in (4, 5) and parts[:3] == ("api", "viewer", "documents")
            and re.fullmatch(document_id_pattern, parts[3])
            and (len(parts) == 4 or parts[4] == "html")
        ):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            document = db.get_document(parts[3])
            if not document:
                return self.send_json(404, {"error": "Documento nao encontrado"})
            if not self.authorize_document_page_access(identity, document):
                return
            if not document.get("allow_document_page_submission"):
                return self.send_json(403, {"error": "Este documento nao permite preenchimento pela pagina de documento."})
            if len(parts) == 5:
                content = document.get("html_content")
                if not content:
                    return self.send_json(404, {"error": "Conteudo convertido nao encontrado"})
                payload = content.encode("utf-8")
                self.send_response(200)
                self._emit_security_headers(self.PREVIEW_CSP)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            summary = dict(document)
            summary.pop("_id", None)
            summary.pop("html_content", None)
            summary["preview"] = f"/api/viewer/documents/{parts[3]}/html"
            return self.send_json(200, json_safe(summary))
        if (
            len(parts) == 3 and parts[:3] == ("api", "viewer", "submissions")
        ):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            return self.send_json(200, json_safe(db.list_document_submissions_for_user(identity.subject)))
        if (
            len(parts) in (4, 5) and parts[:3] == ("api", "viewer", "submissions")
            and re.fullmatch(r"[0-9a-f]{32}", parts[3])
            and (len(parts) == 4 or parts[4] == "html")
        ):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            submission = db.get_document_submission(parts[3])
            if not submission:
                return self.send_json(404, {"error": "Submissao nao encontrada"})
            if not self.authorize_context(identity, submission.get("tenant_id"), submission.get("group_id")):
                return
            document = db.get_document(
                submission.get("document_id") or submission.get("job_id"),
                submission.get("version"),
                submission.get("tenant_id"),
                submission.get("group_id"),
            )
            if not document and submission.get("job_id"):
                document = db.get_document(
                    submission.get("job_id"),
                    tenant_id=submission.get("tenant_id"),
                    group_id=submission.get("group_id"),
                )
            if not document:
                return self.send_json(404, {"error": "Documento da submissao nao encontrado"})
            if len(parts) == 5:
                content = document.get("html_content")
                if not content:
                    return self.send_json(404, {"error": "Conteudo convertido nao encontrado"})
                payload = content.encode("utf-8")
                self.send_response(200)
                self._emit_security_headers(self.PREVIEW_CSP)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            summary = dict(document)
            summary.pop("_id", None)
            summary.pop("html_content", None)
            summary["preview"] = f"/api/viewer/submissions/{parts[3]}/html"
            summary["submission"] = {
                "submission_id": submission.get("submission_id"),
                "values": submission.get("values") or {},
                "created_at": submission.get("created_at"),
                "subject": submission.get("subject"),
                "email": submission.get("email"),
            }
            return self.send_json(200, json_safe(summary))
        if len(parts) == 4 and parts[:2] == ("api", "documents") and re.fullmatch(r"[0-9a-f]{64}", parts[2]) and parts[3] == "versions":
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query, identity)
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
            if not self.authorize_context(identity, tenant_id, group_id):
                return
            return self.send_json(200, json_safe(db.list_document_versions(parts[2], tenant_id, group_id)))

        if len(parts) == 5 and parts[:2] == ("api", "documents") and re.fullmatch(r"[0-9a-f]{64}", parts[2]) and parts[3] == "versions" and parts[4] == "current":
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query, identity)
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
            if not self.authorize_context(identity, tenant_id, group_id):
                return
            doc = db.get_current_document_version(parts[2], tenant_id, group_id)
            return self.send_json(200, json_safe(doc)) if doc else self.send_json(404, {"error": "Versao padrao nao encontrada"})

        if len(parts) == 5 and parts[:2] == ("api", "documents") and re.fullmatch(r"[0-9a-f]{64}", parts[2]) and parts[3] == "versions" and parts[4].isdigit():
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query)
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
            if not self.authorize_context(identity, tenant_id, group_id):
                return
            doc = db.get_document_summary(parts[2], int(parts[4]), tenant_id, group_id)
            return self.send_json(200, json_safe(doc)) if doc else self.send_json(404, {"error": "Versao nao encontrada"})

        if len(parts) == 3 and parts[:2] == ("api", "documents") and re.fullmatch(document_id_pattern, parts[2]):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query)
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
            if not self.authorize_context(identity, tenant_id, group_id):
                return
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
            if not self.authorize_context(identity, tenant_id, group_id):
                return
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
                job = db.get_job(job_id)
                doc = None
                tenant_id = job.get("tenant_id") if job else None
                group_id = job.get("group_id") if job else None
                if tenant_id:
                    if not self.authorize_context(identity, tenant_id, group_id):
                        return
                    doc = db.get_document(job_id, tenant_id=tenant_id, group_id=group_id)
                else:
                    doc = db.get_document(job_id)
                    if doc:
                        tenant_id = doc.get("tenant_id")
                        group_id = doc.get("group_id")
                    if not doc or not tenant_id:
                        return self.send_error(404, "Documento nao encontrado")
                    if not self.authorize_context(identity, tenant_id, group_id):
                        return
                if not doc and tenant_id:
                    doc = db.get_document(job_id, tenant_id=tenant_id, group_id=group_id)
                if not doc or "html_content" not in doc:
                    return self.send_error(404, "Documento nao encontrado")
                content = doc["html_content"].encode("utf-8")
                self.send_response(200)
                self._emit_security_headers(self.PREVIEW_CSP)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            return self.send_error(404)
        self.send_error(404)

    def do_PUT(self) -> None:
        identity = self.authenticate()
        if identity is None:
            return
        parsed_request = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed_request.path)
        query = urllib.parse.parse_qs(parsed_request.query)
        user_match = re.fullmatch(r"/api/users/([^/]+)/access", path)
        if user_match:
            if not self.require_admin(identity):
                return
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > MAX_JSON_SIZE or self.headers.get_content_type() != "application/json":
                    raise ValueError("Envie um corpo JSON valido de ate 64 KB")
                request = json.loads(self.rfile.read(length))
                tenant_id = validate_context_id(request.get("tenant_id"), "tenant_id")
                group_id = validate_context_id(request.get("group_id"), "group_id") if request.get("group_id") else None
                permission = str(request.get("permission", "reader"))
                access = db.grant_user_access(
                    urllib.parse.unquote(user_match.group(1)), tenant_id, group_id,
                    permission, request.get("username"),
                )
                if not access:
                    raise ValueError("Tenant/grupo inexistente ou permissao invalida")
                return self.send_json(200, json_safe(access))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.send_json(400, {"error": str(exc)})
        parts = Path(path.lstrip("/")).parts
        if (
            len(parts) == 4 and parts[:2] == ("api", "documents")
            and re.fullmatch(r"[0-9a-f]{64}", parts[2]) and parts[3] == "name"
        ):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query)
                if not self.authorize_context(identity, tenant_id, group_id, "editor"):
                    return
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > MAX_JSON_SIZE or self.headers.get_content_type() != "application/json":
                    raise ValueError("Envie um corpo JSON valido de ate 64 KB")
                request = json.loads(self.rfile.read(length))
                name = str(request.get("name") or "").strip()
                if not 1 <= len(name) <= 255 or any(ord(char) < 32 for char in name):
                    raise ValueError("name deve possuir entre 1 e 255 caracteres validos")
                if not db.rename_document(parts[2], name, tenant_id, group_id):
                    return self.send_json(404, {"error": "Documento nao encontrado"})
                return self.send_json(200, {"document_id": parts[2], "name": name})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.send_json(400, {"error": str(exc)})
        if (
            len(parts) == 4 and parts[:2] == ("api", "documents")
            and re.fullmatch(r"[0-9a-f]{64}", parts[2]) and parts[3] == "category"
        ):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query)
                if not self.authorize_context(identity, tenant_id, group_id, "editor"):
                    return
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > MAX_JSON_SIZE or self.headers.get_content_type() != "application/json":
                    raise ValueError("Envie um corpo JSON valido de ate 64 KB")
                request = json.loads(self.rfile.read(length))
                category_id = validate_context_id(request.get("category_id"), "category_id") if request.get("category_id") else None
                if category_id and not db.category_belongs_to_group(tenant_id, group_id, category_id):
                    raise ValueError("category_id deve pertencer ao grupo informado")
                if not db.update_document_category(parts[2], category_id, tenant_id, group_id):
                    return self.send_json(404, {"error": "Documento nao encontrado"})
                return self.send_json(200, {"document_id": parts[2], "category_id": category_id})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.send_json(400, {"error": str(exc)})
        if (
            len(parts) == 4 and parts[:2] == ("api", "documents")
            and re.fullmatch(r"[0-9a-f]{64}", parts[2]) and parts[3] == "format-norm"
        ):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query, identity)
                if not self.authorize_context(identity, tenant_id, group_id, "editor"):
                    return
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > MAX_JSON_SIZE or self.headers.get_content_type() != "application/json":
                    raise ValueError("Envie um corpo JSON valido de ate 64 KB")
                request = json.loads(self.rfile.read(length))
                format_norm = validate_format_norm(request.get("format_norm") if isinstance(request, dict) else None)
                updated = db.apply_format_norm(
                    parts[2], format_norm, tenant_id, group_id,
                    identity.username or identity.subject,
                )
                if not updated:
                    return self.send_json(404, {"error": "Documento nao encontrado"})
                db.save_job(updated["job_id"], {
                    "job_id": updated["job_id"],
                    "status": "completed",
                    "result": {
                        "fields": updated["fields"],
                        "tables": updated["tables"],
                        "neural_tables": updated["neural_tables"],
                        "preview": f"/jobs/{updated['job_id']}/html/index.html",
                        "document_id": updated["document_id"],
                        "version": updated["version"],
                    },
                    "format_norm": updated["format_norm"],
                    "tenant_id": updated["tenant_id"],
                    "group_id": updated["group_id"],
                    "category_id": updated["category_id"],
                })
                return self.send_json(200, json_safe({
                    **updated,
                    "preview": f"/jobs/{updated['job_id']}/html/index.html",
                }))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.send_json(400, {"error": str(exc)})
        if (
            len(parts) == 4 and parts[:2] == ("api", "documents")
            and re.fullmatch(r"[0-9a-f]{64}", parts[2]) and parts[3] == "single-submission"
        ):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query, identity)
                if not self.authorize_context(identity, tenant_id, group_id, "editor"):
                    return
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > MAX_JSON_SIZE or self.headers.get_content_type() != "application/json":
                    raise ValueError("Envie um corpo JSON valido de ate 64 KB")
                request = json.loads(self.rfile.read(length))
                enabled = validate_boolean(
                    request.get("single_submission_per_user") if isinstance(request, dict) else None,
                    "single_submission_per_user",
                )
                if not db.update_document_single_submission_per_user(parts[2], enabled, tenant_id, group_id):
                    return self.send_json(404, {"error": "Documento nao encontrado"})
                return self.send_json(200, {
                    "document_id": parts[2],
                    "single_submission_per_user": enabled,
                })
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.send_json(400, {"error": str(exc)})
        if (
            len(parts) == 4 and parts[:2] == ("api", "documents")
            and re.fullmatch(r"[0-9a-f]{64}", parts[2]) and parts[3] == "document-page-submission"
        ):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query, identity)
                if not self.authorize_context(identity, tenant_id, group_id, "editor"):
                    return
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > MAX_JSON_SIZE or self.headers.get_content_type() != "application/json":
                    raise ValueError("Envie um corpo JSON valido de ate 64 KB")
                request = json.loads(self.rfile.read(length))
                enabled = validate_boolean(
                    request.get("allow_document_page_submission") if isinstance(request, dict) else None,
                    "allow_document_page_submission",
                )
                if not db.update_document_page_submission_allowed(parts[2], enabled, tenant_id, group_id):
                    return self.send_json(404, {"error": "Documento nao encontrado"})
                return self.send_json(200, {
                    "document_id": parts[2],
                    "allow_document_page_submission": enabled,
                })
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.send_json(400, {"error": str(exc)})
        if (
            len(parts) == 4 and parts[:2] == ("api", "documents")
            and re.fullmatch(r"[0-9a-f]{64}", parts[2]) and parts[3] == "html"
        ):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query, identity)
                if not self.authorize_context(identity, tenant_id, group_id, "editor"):
                    return
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > MAX_HTML_JSON_SIZE + 1024:
                    raise ValueError("Corpo JSON ausente ou maior que 8 MB")
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("Content-Type deve ser application/json")
                request = json.loads(self.rfile.read(length))
                html_content = validate_html_payload(request.get("html_content") if isinstance(request, dict) else None)
                source_version = request.get("base_version") if isinstance(request, dict) else None
                source_version = int(source_version) if source_version is not None else None
                updated = db.create_edited_html_version(
                    parts[2], html_content, identity.username or identity.subject,
                    tenant_id, group_id, source_version,
                )
                if not updated:
                    return self.send_json(404, {"error": "Documento nao encontrado"})
                db.save_job(updated["job_id"], {
                    "job_id": updated["job_id"],
                    "status": "completed",
                    "result": {
                        "fields": updated["fields"],
                        "tables": updated["tables"],
                        "neural_tables": updated["neural_tables"],
                        "preview": f"/jobs/{updated['job_id']}/html/index.html",
                        "document_id": updated["document_id"],
                        "version": updated["version"],
                    },
                    "edited_html": True,
                    "tenant_id": updated["tenant_id"],
                    "group_id": updated["group_id"],
                    "category_id": updated["category_id"],
                })
                return self.send_json(200, json_safe({
                    **updated,
                    "preview": f"/jobs/{updated['job_id']}/html/index.html",
                }))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.send_json(400, {"error": str(exc)})
        if (
            len(parts) == 6 and parts[:2] == ("api", "documents")
            and re.fullmatch(r"[0-9a-f]{64}", parts[2]) and parts[3] == "versions"
            and parts[4].isdigit() and parts[5] == "deprecated"
        ):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query)
                if not self.authorize_context(identity, tenant_id, group_id, "editor"):
                    return
                updated = db.set_version_deprecated(parts[2], int(parts[4]), True, tenant_id, group_id)
                if not updated:
                    return self.send_json(404, {"error": "Versao nao encontrada"})
                return self.send_json(200, json_safe(updated))
            except ValueError as exc:
                return self.send_json(409, {"error": str(exc)})
        if (
            len(parts) == 6 and parts[:2] == ("api", "documents")
            and re.fullmatch(r"[0-9a-f]{64}", parts[2]) and parts[3] == "versions"
            and parts[4].isdigit() and parts[5] == "current"
        ):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query)
                if not self.authorize_context(identity, tenant_id, group_id, "editor"):
                    return
                selected = db.set_current_version(parts[2], int(parts[4]), tenant_id, group_id)
                if not selected:
                    return self.send_json(404, {"error": "Versao nao encontrada"})
                return self.send_json(200, json_safe(selected))
            except ValueError as exc:
                status_code = 409 if "deprecated" in str(exc) else 400
                return self.send_json(status_code, {"error": str(exc)})
        if not (
            len(parts) == 4 and parts[:2] == ("api", "documents")
            and re.fullmatch(r"[0-9a-f]{32}", parts[2]) and parts[3] == "fields"
        ):
            return self.send_error(404)
        if not db or not db.is_available():
            return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
        try:
            tenant_id, group_id = validate_search_context(query)
            if not self.authorize_context(identity, tenant_id, group_id, "editor"):
                return
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > MAX_JSON_SIZE:
                raise ValueError("Corpo JSON ausente ou maior que 64 KB")
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Content-Type deve ser application/json")
            request = json.loads(self.rfile.read(length))
            fields = validate_fields_payload(request.get("fields") if isinstance(request, dict) else None)
            result = db.update_document_fields(parts[2], fields, tenant_id, group_id)
            if result is None or getattr(result, "matched_count", 1) == 0:
                return self.send_json(404, {"error": "Documento nao encontrado"})
            job_data = db.get_job(parts[2], tenant_id, group_id)
            if job_data and isinstance(job_data.get("result"), dict):
                updated = dict(job_data)
                updated.pop("_id", None)
                updated["result"] = {**job_data["result"], "fields": fields}
                db.save_job(parts[2], updated)
            return self.send_json(200, {"job_id": parts[2], "fields": fields})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self.send_json(400, {"error": str(exc)})

    def do_DELETE(self) -> None:
        identity = self.authenticate()
        if identity is None:
            return
        parsed_request = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed_request.path)
        query = urllib.parse.parse_qs(parsed_request.query)
        delete_user_match = re.fullmatch(r"/api/users/([^/]+)", path)
        if delete_user_match:
            if not self.require_admin(identity):
                return
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            subject = urllib.parse.unquote(delete_user_match.group(1))
            deleted = db.delete_user_access(subject)
            return self.send_json(200, {"deleted": deleted}) if deleted else self.send_json(404, {"error": "Usuario nao encontrado"})
        user_match = re.fullmatch(r"/api/users/([^/]+)/access", path)
        if user_match:
            if not self.require_admin(identity):
                return
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query)
                deleted = db.revoke_user_access(urllib.parse.unquote(user_match.group(1)), tenant_id, group_id)
                return self.send_json(200, {"deleted": True}) if deleted else self.send_json(404, {"error": "Acesso nao encontrado"})
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
        parts = Path(path.lstrip("/")).parts
        if (
            len(parts) == 5 and parts[:2] == ("api", "documents")
            and re.fullmatch(r"[0-9a-f]{64}", parts[2]) and parts[3] == "versions"
            and parts[4].isdigit()
        ):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query)
                if not self.authorize_context(identity, tenant_id, group_id, "editor"):
                    return
                deleted = db.delete_document_version(parts[2], int(parts[4]), tenant_id, group_id)
                if not deleted:
                    return self.send_json(404, {"error": "Versao nao encontrada"})
                return self.send_json(200, json_safe(deleted))
            except ValueError as exc:
                return self.send_json(409, {"error": str(exc)})
        if (
            len(parts) == 6 and parts[:2] == ("api", "documents")
            and re.fullmatch(r"[0-9a-f]{64}", parts[2]) and parts[3] == "versions"
            and parts[4].isdigit() and parts[5] == "deprecated"
        ):
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                tenant_id, group_id = validate_search_context(query)
                if not self.authorize_context(identity, tenant_id, group_id, "editor"):
                    return
                updated = db.set_version_deprecated(parts[2], int(parts[4]), False, tenant_id, group_id)
                if not updated:
                    return self.send_json(404, {"error": "Versao nao encontrada"})
                return self.send_json(200, json_safe(updated))
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
        if not (
            len(parts) == 3 and parts[:2] == ("api", "documents")
            and re.fullmatch(r"(?:[0-9a-f]{32}|[0-9a-f]{64})", parts[2])
        ):
            return self.send_error(404)
        if not db or not db.is_available():
            return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
        try:
            tenant_id, group_id = validate_search_context(query)
            if not self.authorize_context(identity, tenant_id, group_id, "editor"):
                return
            if not db.delete_document(parts[2], tenant_id, group_id):
                return self.send_json(404, {"error": "Documento nao encontrado"})
            return self.send_json(200, {"job_id": parts[2], "deleted": True})
        except Exception:
            LOGGER.exception("Erro ao excluir documento %s", parts[2])
            return self.send_json(500, {"error": "Erro interno ao excluir documento"})

    def do_POST(self) -> None:
        identity = self.authenticate()
        if identity is None:
            return
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path == "/api/pdf/html":
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > MAX_PDF_SIZE + 4096:
                    raise ValueError("Corpo JSON ausente ou maior que 30 MB")
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("Content-Type deve ser application/json")
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError("O corpo JSON deve ser um objeto")
                html_content = self._html_for_pdf_payload(request.get("html_content"))
                filename = self._pdf_filename(request.get("filename"))
                pdf = self.convert_html_with_gotenberg(html_content, filename)
                return self.send_pdf_bytes(pdf, filename)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:500]
                LOGGER.warning("Gotenberg retornou erro HTTP %s: %s", exc.code, detail)
                return self.send_json(502, {"error": f"Gotenberg retornou erro HTTP {exc.code}"})
            except urllib.error.URLError as exc:
                LOGGER.warning("Erro ao acessar Gotenberg: %s", exc)
                return self.send_json(502, {"error": "Nao foi possivel acessar o Gotenberg"})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.send_json(400, {"error": str(exc)})
        if path == "/api/users":
            if not self.require_admin(identity):
                return
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > MAX_JSON_SIZE or self.headers.get_content_type() != "application/json":
                    raise ValueError("Envie um corpo JSON valido de ate 64 KB")
                request = json.loads(self.rfile.read(length))
                username = str(request.get("username") or "").strip()
                email = str(request.get("email") or "").strip() or None
                password = str(request.get("password") or "")
                if not 1 <= len(username) <= 120:
                    raise ValueError("username deve possuir entre 1 e 120 caracteres")
                if email and (len(email) > 254 or "@" not in email):
                    raise ValueError("email invalido")
                if not 8 <= len(password) <= 256:
                    raise ValueError("password deve possuir entre 8 e 256 caracteres")
                tenant_id = validate_context_id(request.get("tenant_id"), "tenant_id")
                group_id = validate_context_id(request.get("group_id"), "group_id") if request.get("group_id") else None
                permission = str(request.get("permission", "reader"))
                keycloak_user = authenticator.create_user(
                    username, email, password, bool(request.get("temporary_password", True)),
                )
                access = db.grant_user_access(
                    keycloak_user["id"], tenant_id, group_id, permission,
                    request.get("display_name") or username,
                )
                if not access:
                    raise ValueError("Tenant/grupo inexistente ou permissao invalida")
                return self.send_json(201, json_safe({"user": keycloak_user, "access": access}))
            except AuthenticationError as exc:
                return self.send_json(502, {"error": str(exc)})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.send_json(400, {"error": str(exc)})
            except Exception as exc:
                LOGGER.exception("Erro ao criar usuario no Keycloak")
                return self.send_json(502, {"error": f"Falha ao criar usuario no Keycloak: {exc}"})
        viewer_match = re.fullmatch(
            r"/api/viewer/documents/((?:[0-9a-f]{32}|[0-9a-f]{64}))/submissions", path
        )
        if viewer_match:
            try:
                if not db or not db.is_available():
                    return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
                document = db.get_document(viewer_match.group(1))
                if not document:
                    return self.send_json(404, {"error": "Documento nao encontrado"})
                if not self.authorize_document_page_access(identity, document):
                    return
                if not document.get("allow_document_page_submission"):
                    return self.send_json(403, {"error": "Este documento nao permite preenchimento pela pagina de documento."})
                if document.get("single_submission_per_user") and db.user_already_submitted_document(document, identity.subject):
                    return self.send_json(409, {"error": "Este documento permite apenas um preenchimento por usuario."})
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > MAX_JSON_SIZE or self.headers.get_content_type() != "application/json":
                    raise ValueError("Envie um corpo JSON valido de ate 64 KB")
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError("O corpo JSON deve ser um objeto")
                values = validate_submission_values(request.get("values"), document.get("fields", []))
                saved = db.save_document_submission(
                    document,
                    identity.subject,
                    identity.claims.get("email") or identity.username,
                    values,
                )
                return self.send_json(201, json_safe({
                    "submission_id": saved["submission_id"],
                    "created_at": saved["created_at"],
                }))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.send_json(400, {"error": str(exc)})
            except Exception:
                LOGGER.exception("Erro ao salvar preenchimento do documento")
                return self.send_json(500, {"error": "Erro interno ao salvar o resultado"})
        if (
            path == "/api/tenants"
            or re.fullmatch(r"/api/tenants/[0-9a-f]{32}/groups", path)
            or re.fullmatch(r"/api/tenants/[0-9a-f]{32}/groups/[0-9a-f]{32}/categories", path)
        ):
            if not self.require_admin(identity):
                return
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
                if path == "/api/tenants":
                    return self.send_json(201, json_safe(db.create_tenant(name, metadata)))
                path_parts = Path(path.lstrip("/")).parts
                tenant_id = path_parts[2]
                resource = (
                    db.create_category(tenant_id, path_parts[4], name, metadata)
                    if path.endswith("/categories") else db.create_group(tenant_id, name, metadata)
                )
                return self.send_json(201, json_safe(resource)) if resource else self.send_json(404, {"error": "Tenant ou grupo nao encontrado"})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.send_json(400, {"error": str(exc)})
        if path == "/api/api-keys":
            if not self.require_admin(identity):
                return
            try:
                if not db or not db.is_available():
                    return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > MAX_JSON_SIZE or self.headers.get_content_type() != "application/json":
                    raise ValueError("Envie um corpo JSON valido de ate 64 KB")
                request = json.loads(self.rfile.read(length))
                client_id = validate_resource_name(request.get("client_id"), "client_id")
                name = validate_resource_name(request.get("name"), "name")
                tenant_id = validate_context_id(request.get("tenant_id"), "tenant_id") if request.get("tenant_id") else None
                group_id = validate_context_id(request.get("group_id"), "group_id") if request.get("group_id") else None
                
                if tenant_id and not db.group_belongs_to_tenant(tenant_id, group_id):
                    raise ValueError("O grupo informado nao pertence ao tenant")
                
                if not authenticator.validate_client(client_id):
                    raise ValueError(f"O client_id '{client_id}' nao existe no Keycloak ou nao possui Service Account habilitado")

                key = db.create_api_key(client_id, name, tenant_id, group_id)
                return self.send_json(201, {"api_key": key})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.send_json(400, {"error": str(exc)})
            except Exception:
                LOGGER.exception("Erro ao gerar API Key")
                return self.send_json(500, {"error": "Erro interno ao gerar API Key"})
        if path == "/api/api-keys/revoke":
            if not self.require_admin(identity):
                return
            try:
                if not db or not db.is_available():
                    return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > MAX_JSON_SIZE or self.headers.get_content_type() != "application/json":
                    raise ValueError("Envie um corpo JSON valido")
                request = json.loads(self.rfile.read(length))
                client_id = request.get("client_id")
                tenant_id = request.get("tenant_id")
                group_id = request.get("group_id")
                
                if not client_id or not tenant_id:
                    raise ValueError("client_id e tenant_id sao obrigatorios")
                
                success = db.revoke_api_key(client_id, tenant_id, group_id)
                return self.send_json(200, {"success": success})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.send_json(400, {"error": str(exc)})
            except Exception:
                LOGGER.exception("Erro ao revogar API Key")
                return self.send_json(500, {"error": "Erro interno ao revogar API Key"})
        if path == "/api/jobs":
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
                single_submission_per_user = validate_boolean(
                    request.get("single_submission_per_user", False),
                    "single_submission_per_user",
                )
                allow_document_page_submission = validate_boolean(
                    request.get("allow_document_page_submission", False),
                    "allow_document_page_submission",
                )
                tenant_id = validate_context_id(request.get("tenant_id"), "tenant_id") if request.get("tenant_id") else None
                group_id = validate_context_id(request.get("group_id"), "group_id") if request.get("group_id") else None

                # Se não foi passado no JSON, tenta obter da identidade (API Key)
                if not tenant_id and identity:
                    tenant_id = identity.claims.get("tenant_id")
                    if not group_id:
                        group_id = identity.claims.get("group_id")

                category_id = validate_context_id(request.get("category_id"), "category_id") if request.get("category_id") else None
                if tenant_id and not db.group_belongs_to_tenant(tenant_id, group_id):
                    raise ValueError("tenant_id deve existir e group_id, quando informado, deve pertencer ao tenant")
                if tenant_id and not db.category_belongs_to_group(tenant_id, group_id, category_id):
                    raise ValueError("category_id deve pertencer ao grupo informado")
                if not self.authorize_context(identity, tenant_id, group_id, "editor"):
                    return
                job = uuid.uuid4().hex
                LOGGER.info("Criando background job %s para URL: %s", job, pdf_url)
                initial = {
                    "job_id": job, "reference": reference, "status": "queued",
                    "tenant_id": tenant_id, "group_id": group_id, "category_id": category_id,
                    "single_submission_per_user": single_submission_per_user,
                    "allow_document_page_submission": allow_document_page_submission,
                }
                db.save_job(job, initial)
                EXECUTOR.submit(
                    run_api_job, job, pdf_url, callback_url, reference, self.base_url(),
                    tenant_id, group_id, category_id, single_submission_per_user,
                    allow_document_page_submission,
                )
                status_query = urllib.parse.urlencode({key: value for key, value in {"tenant_id": tenant_id, "group_id": group_id}.items() if value})
                return self.send_json(202, {**initial, "status_url": f"{self.base_url()}/api/jobs/{job}?{status_query}"})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                LOGGER.warning("Requisição inválida para /api/jobs: %s", str(exc))
                return self.send_json(400, {"error": str(exc)})
            except Exception:
                LOGGER.exception("Erro ao criar job")
                return self.send_json(500, {"error": "Erro interno ao criar job"})
        if path != "/api/convert":
            self.send_error(404); return
        try:
            LOGGER.info("Iniciando requisicao /api/convert")
            if not db or not db.is_available():
                return self.send_json(503, {"error": "Servico de banco de dados indisponivel"})
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_PDF_SIZE + 1024 * 1024:
                raise ValueError("O limite e 30 MB")
            body = self.rfile.read(length)
            (
                name, data, url, tenant_id, group_id, category_id,
                raw_single_submission, raw_page_submission,
            ) = multipart_data(self.headers.get("Content-Type", ""), body)
            tenant_id = validate_context_id(tenant_id, "tenant_id") if tenant_id else None
            group_id = validate_context_id(group_id, "group_id") if group_id else None
            single_submission_per_user = validate_boolean(raw_single_submission, "single_submission_per_user")
            allow_document_page_submission = validate_boolean(raw_page_submission, "allow_document_page_submission")

            # Se não foi passado no form-data, tenta obter da identidade (API Key)
            if not tenant_id and identity:
                tenant_id = identity.claims.get("tenant_id")
                if not group_id:
                    group_id = identity.claims.get("group_id")

            category_id = validate_context_id(category_id, "category_id") if category_id else None
            if tenant_id and not db.group_belongs_to_tenant(tenant_id, group_id):
                raise ValueError("tenant_id deve existir e group_id, quando informado, deve pertencer ao tenant")
            if tenant_id and not db.category_belongs_to_group(tenant_id, group_id, category_id):
                raise ValueError("category_id deve pertencer ao grupo informado")
            if not self.authorize_context(identity, tenant_id, group_id, "editor"):
                return
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
                category_id=category_id,
                single_submission_per_user=single_submission_per_user,
                allow_document_page_submission=allow_document_page_submission,
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
                "category_id": category_id,
                "single_submission_per_user": single_submission_per_user,
                "allow_document_page_submission": allow_document_page_submission,
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
                "category_id": category_id,
                "single_submission_per_user": single_submission_per_user,
                "allow_document_page_submission": allow_document_page_submission,
                "metadata": {"filename": name},
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
