from __future__ import annotations

import os
import re
import hashlib
import urllib.error
import urllib.parse
import uuid
from datetime import timedelta
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from auth import AuthenticationError, Identity, authenticator
from config import EXECUTOR, LOGGER, MAX_HTML_JSON_SIZE, MAX_PDF_SIZE
from database import db
from fastapi_helpers import (
    SECURITY_HEADERS,
    base_url,
    body_context_id,
    body_resource_name,
    convert_html_with_gotenberg,
    html_for_pdf_payload,
    json_body,
    parse_query_date,
    pdf_filename,
    preview_html_response,
)
from fastapi_static import router as static_router
from jobs import run_api_job
from services import convert_pdf_bytes
from utils import json_safe
from utils import download_pdf, multipart_data, validate_public_url
from validators import (
    validate_boolean,
    validate_category_query,
    validate_context_id,
    validate_fields_payload,
    validate_format_norm,
    validate_html_payload,
    validate_search_context,
    validate_submission_values,
)


TENANT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
DOCUMENT_ID_PATTERN = re.compile(r"^(?:[0-9a-f]{32}|[0-9a-f]{64})$")
JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def create_app() -> FastAPI:
    api = FastAPI(
        title="PDF Neural",
        version="0.1.0",
        description="API FastAPI em migracao incremental a partir do handler legado.",
    )
    api.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    )
    register_middleware(api)
    register_routes(api)
    api.include_router(static_router)
    return api


def register_middleware(api: FastAPI) -> None:
    @api.exception_handler(HTTPException)
    async def legacy_http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        headers = exc.headers or None
        if isinstance(exc.detail, dict):
            content = exc.detail
        else:
            content = {"error": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=content, headers=headers)

    @api.middleware("http")
    async def add_security_headers(request: Request, call_next) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response


def require_database() -> None:
    if not db or not db.is_available():
        raise HTTPException(status_code=503, detail={"error": "Servico de banco de dados indisponivel"})


def auth_error_response(exc: AuthenticationError, api_key: str | None) -> HTTPException:
    headers = {}
    if not api_key:
        headers["WWW-Authenticate"] = 'Bearer realm="pdf-neural"'
    return HTTPException(status_code=401, detail={"error": str(exc)}, headers=headers)


def current_identity(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Identity:
    try:
        if x_api_key:
            return authenticator.authenticate_api_key(x_api_key)
        return authenticator.authenticate(authorization)
    except AuthenticationError as exc:
        raise auth_error_response(exc, x_api_key) from exc


def require_admin(identity: Identity) -> None:
    if not identity.has_role(authenticator.admin_role):
        raise HTTPException(status_code=403, detail={"error": "Role pdf-admin necessaria"})


def authorize_tenant_access(identity: Identity, tenant_id: str) -> None:
    if identity.has_role(authenticator.admin_role):
        return
    require_database()
    if not db.user_has_access(identity.subject, tenant_id):
        raise HTTPException(status_code=403, detail={"error": "Acesso negado ao tenant"})


def authorize_context(
    identity: Identity,
    tenant_id: str | None,
    group_id: str | None = None,
    permission: str = "reader",
) -> None:
    if identity.has_role(authenticator.admin_role):
        return
    require_database()
    if not tenant_id:
        raise HTTPException(status_code=403, detail={"error": "Acesso negado: tenant_id obrigatorio para usuarios nao-admin"})

    key_tenant_id = identity.claims.get("tenant_id")
    key_group_id = identity.claims.get("group_id")
    if key_tenant_id:
        if key_tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail={"error": "Esta API Key está restrita a outro tenant"})
        if key_group_id and key_group_id != group_id:
            raise HTTPException(status_code=403, detail={"error": "Esta API Key está restrita a outro grupo"})

    if db.user_has_access(identity.subject, tenant_id, group_id, permission):
        return
    raise HTTPException(status_code=403, detail={"error": "Usuario sem acesso ao tenant ou grupo solicitado"})


def validate_tenant_id(tenant_id: str) -> str:
    if not TENANT_ID_PATTERN.fullmatch(tenant_id):
        raise HTTPException(status_code=404, detail={"error": "Tenant nao encontrado"})
    return tenant_id


def validate_document_id(document_id: str) -> str:
    if not DOCUMENT_ID_PATTERN.fullmatch(document_id):
        raise HTTPException(status_code=404, detail={"error": "Documento nao encontrado"})
    return document_id


def validate_job_id(job_id: str) -> str:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise HTTPException(status_code=404, detail={"error": "Job nao encontrado"})
    return job_id


def query_lists(request: Request) -> dict[str, list[str]]:
    return {key: request.query_params.getlist(key) for key in request.query_params}


def search_context(request: Request, identity: Identity | None = None) -> tuple[str | None, str | None]:
    try:
        return validate_search_context(query_lists(request), identity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc


def category_context(request: Request) -> str | None:
    try:
        return validate_category_query(query_lists(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc


def ensure_category_belongs_to_group(
    tenant_id: str | None,
    group_id: str | None,
    category_id: str | None,
) -> None:
    if category_id and tenant_id and (
        not group_id or not db.category_belongs_to_group(tenant_id, group_id, category_id)
    ):
        raise HTTPException(status_code=400, detail={"error": "category_id deve pertencer ao group_id informado"})


def pagination(request: Request) -> tuple[int, int]:
    try:
        page = int(request.query_params.get("page", "1"))
        page_size = int(request.query_params.get("page_size", "10"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"error": "page e page_size devem ser numeros inteiros"}) from exc
    if page < 1 or not 1 <= page_size <= 100:
        raise HTTPException(status_code=400, detail={"error": "page deve ser maior que zero e page_size deve estar entre 1 e 100"})
    return page, page_size


def authorize_document_page_access(identity: Identity, document: dict) -> None:
    if identity.has_role(authenticator.admin_role):
        return
    tenant_id = document.get("tenant_id")
    group_id = document.get("group_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail={"error": "Documento sem tenant vinculado"})
    require_database()
    for access in db.list_user_access(identity.subject):
        if access.get("tenant_id") == tenant_id and access.get("group_id") == group_id:
            return
    raise HTTPException(status_code=403, detail={"error": "Usuario sem acesso ao tenant ou grupo do documento"})


def save_completed_version_job(updated: dict, *, flag: str | None = None) -> None:
    job_id = updated["job_id"]
    job_data = {
        "job_id": job_id,
        "status": "completed",
        "result": {
            "fields": updated["fields"],
            "tables": updated["tables"],
            "neural_tables": updated["neural_tables"],
            "preview": f"/jobs/{job_id}/html/index.html",
            "document_id": updated["document_id"],
            "version": updated["version"],
        },
        "tenant_id": updated["tenant_id"],
        "group_id": updated["group_id"],
        "category_id": updated["category_id"],
    }
    if flag:
        job_data[flag] = True
    if "format_norm" in updated:
        job_data["format_norm"] = updated["format_norm"]
    db.save_job(job_id, job_data)


def register_routes(api: FastAPI) -> None:
    @api.get("/auth/config")
    def auth_config() -> dict:
        return {
            "issuer": authenticator.issuer,
            "client_id": authenticator.audience,
        }

    @api.get("/api/me")
    def me(identity: Annotated[Identity, Depends(current_identity)]) -> object:
        access = db.list_user_access(identity.subject) if db and db.is_available() else []
        return json_safe({
            "sub": identity.subject,
            "username": identity.username,
            "roles": sorted(identity.roles),
            "access": access,
        })

    @api.post("/api/pdf/html")
    async def pdf_from_html(request: Request, identity: Annotated[Identity, Depends(current_identity)]) -> Response:
        payload = await json_body(
            request,
            max_size=MAX_PDF_SIZE + 4096,
            message="Corpo JSON ausente ou maior que 30 MB",
        )
        try:
            html_content = html_for_pdf_payload(payload.get("html_content"))
            filename = pdf_filename(payload.get("filename"))
            pdf = convert_html_with_gotenberg(html_content, filename)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            LOGGER.warning("Gotenberg retornou erro HTTP %s: %s", exc.code, detail)
            raise HTTPException(status_code=502, detail={"error": f"Gotenberg retornou erro HTTP {exc.code}"}) from exc
        except urllib.error.URLError as exc:
            LOGGER.warning("Erro ao acessar Gotenberg: %s", exc)
            raise HTTPException(status_code=502, detail={"error": "Nao foi possivel acessar o Gotenberg"}) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @api.get("/api/public/viewer/documents/{document_id}")
    def public_viewer_document(document_id: str) -> object:
        document_id = validate_document_id(document_id)
        require_database()
        document = db.get_document_summary(document_id)
        if not document or not document.get("allow_document_page_submission"):
            raise HTTPException(status_code=404, detail={"error": "Documento nao encontrado"})
        metadata = document.get("metadata") or {}
        tenant_id = document.get("tenant_id")
        group_id = document.get("group_id")
        tenant = db.get_tenant(tenant_id)
        group = db.get_group(tenant_id, group_id)
        return json_safe({
            "document_id": document.get("document_id") or document.get("job_id"),
            "document_name": document.get("name") or metadata.get("filename") or "Documento",
            "tenant_id": tenant_id,
            "tenant_name": tenant.get("name") if tenant else None,
            "group_id": group_id,
            "group_name": group.get("name") if group else None,
        })

    @api.get("/api/users/access")
    def users_access(identity: Annotated[Identity, Depends(current_identity)]) -> object:
        require_admin(identity)
        require_database()
        return json_safe(db.list_all_user_access())

    @api.get("/api/users/{subject}/access")
    def user_access(subject: str, identity: Annotated[Identity, Depends(current_identity)]) -> object:
        require_admin(identity)
        require_database()
        return json_safe(db.list_user_access(subject))

    @api.post("/api/users")
    async def create_user(request: Request, identity: Annotated[Identity, Depends(current_identity)]) -> Response:
        require_admin(identity)
        require_database()
        payload = await json_body(request)
        try:
            username = str(payload.get("username") or "").strip()
            email = str(payload.get("email") or "").strip() or None
            password = str(payload.get("password") or "")
            if not 1 <= len(username) <= 120:
                raise ValueError("username deve possuir entre 1 e 120 caracteres")
            if email and (len(email) > 254 or "@" not in email):
                raise ValueError("email invalido")
            if not 8 <= len(password) <= 256:
                raise ValueError("password deve possuir entre 8 e 256 caracteres")
            tenant_id = validate_context_id(payload.get("tenant_id"), "tenant_id")
            group_id = validate_context_id(payload.get("group_id"), "group_id") if payload.get("group_id") else None
            permission = str(payload.get("permission", "reader"))
            keycloak_user = authenticator.create_user(
                username,
                email,
                password,
                bool(payload.get("temporary_password", True)),
            )
            access = db.grant_user_access(
                keycloak_user["id"],
                tenant_id,
                group_id,
                permission,
                payload.get("display_name") or username,
            )
            if not access:
                raise ValueError("Tenant/grupo inexistente ou permissao invalida")
        except AuthenticationError as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except Exception as exc:
            LOGGER.exception("Erro ao criar usuario no Keycloak")
            raise HTTPException(status_code=502, detail={"error": f"Falha ao criar usuario no Keycloak: {exc}"}) from exc
        return JSONResponse(status_code=201, content=json_safe({"user": keycloak_user, "access": access}))

    @api.put("/api/users/{subject}/access")
    async def grant_access(
        subject: str,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        require_admin(identity)
        require_database()
        payload = await json_body(request)
        tenant_id = body_context_id(payload, "tenant_id")
        group_id = body_context_id(payload, "group_id", required=False)
        permission = str(payload.get("permission", "reader"))
        access = db.grant_user_access(subject, tenant_id, group_id, permission, payload.get("username"))
        if not access:
            raise HTTPException(status_code=400, detail={"error": "Tenant/grupo inexistente ou permissao invalida"})
        return json_safe(access)

    @api.delete("/api/users/{subject}/access")
    def revoke_access(
        subject: str,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        require_admin(identity)
        require_database()
        tenant_id, group_id = search_context(request)
        deleted = db.revoke_user_access(subject, tenant_id, group_id)
        if not deleted:
            raise HTTPException(status_code=404, detail={"error": "Acesso nao encontrado"})
        return {"deleted": True}

    @api.delete("/api/users/{subject}")
    def delete_user(subject: str, identity: Annotated[Identity, Depends(current_identity)]) -> object:
        require_admin(identity)
        require_database()
        deleted = db.delete_user_access(subject)
        if not deleted:
            raise HTTPException(status_code=404, detail={"error": "Usuario nao encontrado"})
        return {"deleted": deleted}

    @api.get("/api/api-keys")
    def api_keys(request: Request, identity: Annotated[Identity, Depends(current_identity)]) -> object:
        require_admin(identity)
        require_database()
        tenant_id = request.query_params.get("tenant_id")
        group_id = request.query_params.get("group_id")
        if not tenant_id:
            raise HTTPException(status_code=400, detail={"error": "tenant_id é obrigatório"})
        keys = db.list_api_keys(tenant_id, group_id)
        return json_safe(keys)

    @api.post("/api/api-keys")
    async def create_api_key(request: Request, identity: Annotated[Identity, Depends(current_identity)]) -> object:
        require_admin(identity)
        require_database()
        payload = await json_body(request)
        client_id = body_resource_name(payload, "client_id")
        name = body_resource_name(payload, "name")
        tenant_id = body_context_id(payload, "tenant_id", required=False)
        group_id = body_context_id(payload, "group_id", required=False)
        if tenant_id and not db.group_belongs_to_tenant(tenant_id, group_id):
            raise HTTPException(status_code=400, detail={"error": "O grupo informado nao pertence ao tenant"})
        if not authenticator.validate_client(client_id):
            raise HTTPException(status_code=400, detail={"error": f"O client_id '{client_id}' nao existe no Keycloak ou nao possui Service Account habilitado"})
        return {"api_key": db.create_api_key(client_id, name, tenant_id, group_id)}

    @api.post("/api/api-keys/revoke")
    async def revoke_api_key(request: Request, identity: Annotated[Identity, Depends(current_identity)]) -> object:
        require_admin(identity)
        require_database()
        payload = await json_body(request, message="Envie um corpo JSON valido")
        client_id = payload.get("client_id")
        tenant_id = payload.get("tenant_id")
        group_id = payload.get("group_id")
        if not client_id or not tenant_id:
            raise HTTPException(status_code=400, detail={"error": "client_id e tenant_id sao obrigatorios"})
        return {"success": db.revoke_api_key(client_id, tenant_id, group_id)}

    @api.get("/api/admin/submissions")
    def admin_submissions(request: Request, identity: Annotated[Identity, Depends(current_identity)]) -> object:
        require_admin(identity)
        require_database()
        try:
            tenant_id, group_id = search_context(request)
            category_id = category_context(request)
            date_from = parse_query_date(request.query_params.get("date_from", ""), "date_from")
            date_to = parse_query_date(request.query_params.get("date_to", ""), "date_to")
            if date_to:
                date_to = date_to + timedelta(days=1)
            user = request.query_params.get("user", "").strip()
            if len(user) > 255:
                raise ValueError("user deve ter no maximo 255 caracteres")
            if category_id and tenant_id and (
                not group_id or not db.category_belongs_to_group(tenant_id, group_id, category_id)
            ):
                raise HTTPException(status_code=400, detail={"error": "category_id deve pertencer ao group_id informado"})
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return json_safe(db.list_all_document_submissions(
            tenant_id=tenant_id,
            group_id=group_id,
            category_id=category_id,
            date_from=date_from,
            date_to=date_to,
            user=user or None,
        ))

    @api.get("/api/viewer/documents")
    def viewer_documents(identity: Annotated[Identity, Depends(current_identity)]) -> object:
        require_database()
        subject = None if identity.has_role(authenticator.admin_role) else identity.subject
        return json_safe(db.list_submittable_documents_for_user(subject))

    @api.get("/api/viewer/documents/{document_id}")
    def viewer_document(document_id: str, identity: Annotated[Identity, Depends(current_identity)]) -> object:
        document_id = validate_document_id(document_id)
        require_database()
        document = db.get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail={"error": "Documento nao encontrado"})
        authorize_document_page_access(identity, document)
        if not document.get("allow_document_page_submission"):
            raise HTTPException(status_code=403, detail={"error": "Este documento nao permite preenchimento pela pagina de documento."})
        summary = dict(document)
        summary.pop("_id", None)
        summary.pop("html_content", None)
        summary["preview"] = f"/api/viewer/documents/{document_id}/html"
        return json_safe(summary)

    @api.get("/api/viewer/documents/{document_id}/html")
    def viewer_document_html(document_id: str, identity: Annotated[Identity, Depends(current_identity)]) -> HTMLResponse:
        document_id = validate_document_id(document_id)
        require_database()
        document = db.get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail={"error": "Documento nao encontrado"})
        authorize_document_page_access(identity, document)
        if not document.get("allow_document_page_submission"):
            raise HTTPException(status_code=403, detail={"error": "Este documento nao permite preenchimento pela pagina de documento."})
        content = document.get("html_content")
        if not content:
            raise HTTPException(status_code=404, detail={"error": "Conteudo convertido nao encontrado"})
        return preview_html_response(content)

    @api.post("/api/viewer/documents/{document_id}/submissions")
    async def create_viewer_submission(
        document_id: str,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> Response:
        document_id = validate_document_id(document_id)
        require_database()
        document = db.get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail={"error": "Documento nao encontrado"})
        authorize_document_page_access(identity, document)
        if not document.get("allow_document_page_submission"):
            raise HTTPException(status_code=403, detail={"error": "Este documento nao permite preenchimento pela pagina de documento."})
        if document.get("single_submission_per_user") and db.user_already_submitted_document(document, identity.subject):
            raise HTTPException(status_code=409, detail={"error": "Este documento permite apenas um preenchimento por usuario."})
        payload = await json_body(request)
        try:
            values = validate_submission_values(payload.get("values"), document.get("fields", []))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        saved = db.save_document_submission(
            document,
            identity.subject,
            identity.claims.get("email") or identity.username,
            values,
        )
        return JSONResponse(status_code=201, content=json_safe({
            "submission_id": saved["submission_id"],
            "created_at": saved["created_at"],
        }))

    @api.get("/api/viewer/submissions")
    def viewer_submissions(identity: Annotated[Identity, Depends(current_identity)]) -> object:
        require_database()
        return json_safe(db.list_document_submissions_for_user(identity.subject))

    @api.get("/api/viewer/submissions/{submission_id}")
    def viewer_submission(submission_id: str, identity: Annotated[Identity, Depends(current_identity)]) -> object:
        validate_job_id(submission_id)
        require_database()
        submission = db.get_document_submission(submission_id)
        if not submission:
            raise HTTPException(status_code=404, detail={"error": "Submissao nao encontrada"})
        authorize_context(identity, submission.get("tenant_id"), submission.get("group_id"))
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
            raise HTTPException(status_code=404, detail={"error": "Documento da submissao nao encontrado"})
        summary = dict(document)
        summary.pop("_id", None)
        summary.pop("html_content", None)
        summary["preview"] = f"/api/viewer/submissions/{submission_id}/html"
        summary["submission"] = {
            "submission_id": submission.get("submission_id"),
            "values": submission.get("values") or {},
            "created_at": submission.get("created_at"),
            "subject": submission.get("subject"),
            "email": submission.get("email"),
        }
        return json_safe(summary)

    @api.get("/api/viewer/submissions/{submission_id}/html")
    def viewer_submission_html(submission_id: str, identity: Annotated[Identity, Depends(current_identity)]) -> HTMLResponse:
        validate_job_id(submission_id)
        require_database()
        submission = db.get_document_submission(submission_id)
        if not submission:
            raise HTTPException(status_code=404, detail={"error": "Submissao nao encontrada"})
        authorize_context(identity, submission.get("tenant_id"), submission.get("group_id"))
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
            raise HTTPException(status_code=404, detail={"error": "Documento da submissao nao encontrado"})
        content = document.get("html_content")
        if not content:
            raise HTTPException(status_code=404, detail={"error": "Conteudo convertido nao encontrado"})
        return preview_html_response(content)

    @api.get("/jobs/{job_id}/html/index.html")
    def job_preview_html(job_id: str, identity: Annotated[Identity, Depends(current_identity)]) -> HTMLResponse:
        job_id = validate_job_id(job_id)
        require_database()
        job = db.get_job(job_id)
        document = None
        tenant_id = job.get("tenant_id") if job else None
        group_id = job.get("group_id") if job else None
        if tenant_id:
            authorize_context(identity, tenant_id, group_id)
            document = db.get_document(job_id, tenant_id=tenant_id, group_id=group_id)
        else:
            document = db.get_document(job_id)
            if document:
                tenant_id = document.get("tenant_id")
                group_id = document.get("group_id")
            if not document or not tenant_id:
                raise HTTPException(status_code=404, detail={"error": "Documento nao encontrado"})
            authorize_context(identity, tenant_id, group_id)
        if not document and tenant_id:
            document = db.get_document(job_id, tenant_id=tenant_id, group_id=group_id)
        if not document or "html_content" not in document:
            raise HTTPException(status_code=404, detail={"error": "Documento nao encontrado"})
        return preview_html_response(document["html_content"])

    @api.get("/api/documents")
    def documents(request: Request, identity: Annotated[Identity, Depends(current_identity)]) -> object:
        require_database()
        tenant_id, group_id = search_context(request, identity)
        category_id = category_context(request)
        ensure_category_belongs_to_group(tenant_id, group_id, category_id)
        authorize_context(identity, tenant_id, group_id)
        page, page_size = pagination(request)
        name = request.query_params.get("name", "").strip()
        if len(name) > 255:
            raise HTTPException(status_code=400, detail={"error": "name deve ter no maximo 255 caracteres"})
        return json_safe(db.list_documents(
            page=page,
            page_size=page_size,
            tenant_id=tenant_id,
            group_id=group_id,
            category_id=category_id,
            name=name or None,
        ))

    @api.get("/api/jobs")
    def jobs(request: Request, identity: Annotated[Identity, Depends(current_identity)]) -> object:
        require_database()
        tenant_id, group_id = search_context(request, identity)
        category_id = category_context(request)
        ensure_category_belongs_to_group(tenant_id, group_id, category_id)
        authorize_context(identity, tenant_id, group_id)
        return json_safe(db.list_jobs(tenant_id=tenant_id, group_id=group_id, category_id=category_id))

    @api.post("/api/jobs")
    async def create_job(request: Request, identity: Annotated[Identity, Depends(current_identity)]) -> Response:
        LOGGER.info("Recebida requisicao POST /api/jobs")
        require_database()
        payload = await json_body(request, message="Corpo JSON ausente ou maior que 64 KB")
        try:
            pdf_url = validate_public_url(str(payload.get("pdf_url", "")))
            callback_url = validate_public_url(str(payload.get("callback_url", "")))
            reference = payload.get("reference")
            single_submission_per_user = validate_boolean(
                payload.get("single_submission_per_user", False),
                "single_submission_per_user",
            )
            allow_document_page_submission = validate_boolean(
                payload.get("allow_document_page_submission", False),
                "allow_document_page_submission",
            )
            tenant_id = validate_context_id(payload.get("tenant_id"), "tenant_id") if payload.get("tenant_id") else None
            group_id = validate_context_id(payload.get("group_id"), "group_id") if payload.get("group_id") else None
            if not tenant_id:
                tenant_id = identity.claims.get("tenant_id")
                if not group_id:
                    group_id = identity.claims.get("group_id")
            category_id = validate_context_id(payload.get("category_id"), "category_id") if payload.get("category_id") else None
            if tenant_id and not db.group_belongs_to_tenant(tenant_id, group_id):
                raise ValueError("tenant_id deve existir e group_id, quando informado, deve pertencer ao tenant")
            if tenant_id and not db.category_belongs_to_group(tenant_id, group_id, category_id):
                raise ValueError("category_id deve pertencer ao grupo informado")
            authorize_context(identity, tenant_id, group_id, "editor")
        except ValueError as exc:
            LOGGER.warning("Requisicao invalida para /api/jobs: %s", str(exc))
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        job = uuid.uuid4().hex
        LOGGER.info("Criando background job %s para URL: %s", job, pdf_url)
        initial = {
            "job_id": job,
            "reference": reference,
            "status": "queued",
            "tenant_id": tenant_id,
            "group_id": group_id,
            "category_id": category_id,
            "single_submission_per_user": single_submission_per_user,
            "allow_document_page_submission": allow_document_page_submission,
        }
        db.save_job(job, initial)
        EXECUTOR.submit(
            run_api_job,
            job,
            pdf_url,
            callback_url,
            reference,
            base_url(request),
            tenant_id,
            group_id,
            category_id,
            single_submission_per_user,
            allow_document_page_submission,
        )
        status_query = urllib.parse.urlencode({
            key: value
            for key, value in {"tenant_id": tenant_id, "group_id": group_id}.items()
            if value
        })
        return JSONResponse(
            status_code=202,
            content={**initial, "status_url": f"{base_url(request)}/api/jobs/{job}?{status_query}"},
        )

    @api.post("/api/convert")
    async def convert_pdf(request: Request, identity: Annotated[Identity, Depends(current_identity)]) -> object:
        LOGGER.info("Iniciando requisicao /api/convert")
        require_database()
        length = int(request.headers.get("content-length", "0") or "0")
        if length > MAX_PDF_SIZE + 1024 * 1024:
            raise HTTPException(status_code=400, detail={"error": "O limite e 30 MB"})
        body = await request.body()
        try:
            (
                name,
                data,
                url,
                tenant_id,
                group_id,
                category_id,
                raw_single_submission,
                raw_page_submission,
            ) = multipart_data(request.headers.get("content-type", ""), body)
            tenant_id = validate_context_id(tenant_id, "tenant_id") if tenant_id else None
            group_id = validate_context_id(group_id, "group_id") if group_id else None
            single_submission_per_user = validate_boolean(raw_single_submission, "single_submission_per_user")
            allow_document_page_submission = validate_boolean(raw_page_submission, "allow_document_page_submission")
            if not tenant_id:
                tenant_id = identity.claims.get("tenant_id")
                if not group_id:
                    group_id = identity.claims.get("group_id")
            category_id = validate_context_id(category_id, "category_id") if category_id else None
            if tenant_id and not db.group_belongs_to_tenant(tenant_id, group_id):
                raise ValueError("tenant_id deve existir e group_id, quando informado, deve pertencer ao tenant")
            if tenant_id and not db.category_belongs_to_group(tenant_id, group_id, category_id):
                raise ValueError("category_id deve pertencer ao grupo informado")
            authorize_context(identity, tenant_id, group_id, "editor")
            if not data and url:
                LOGGER.info("Baixando PDF remoto: %s", url)
                name, data = download_pdf(url)
            if not data:
                raise ValueError("Envie um arquivo PDF ou informe uma URL")
            if not data.startswith(b"%PDF"):
                raise ValueError("O conteudo recebido nao e um PDF valido")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

        try:
            job = uuid.uuid4().hex
            LOGGER.info("Iniciando job sincrono: %s", job)
            result = convert_pdf_bytes(data, name, job)
            content_hash = hashlib.sha256(data).hexdigest()
            document_identity = db.save_document(
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
            document_identity = document_identity or {
                "document_id": content_hash,
                "version": 1,
                "job_id": job,
                "is_current": True,
            }
            db.save_job(job, {
                "job_id": job,
                "status": "completed",
                "result": {
                    "fields": result.fields,
                    "tables": result.tables,
                    "neural_tables": result.neural_tables,
                    "preview": f"/jobs/{job}/html/index.html",
                    "document_id": document_identity["document_id"],
                    "version": document_identity["version"],
                },
                "sync": True,
                "tenant_id": tenant_id,
                "group_id": group_id,
                "category_id": category_id,
                "single_submission_per_user": single_submission_per_user,
                "allow_document_page_submission": allow_document_page_submission,
            })
            LOGGER.info("Job sincrono concluido: %s", job)
        except Exception as exc:
            LOGGER.exception("Erro ao processar /api/convert")
            raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc

        return json_safe({
            "job_id": job,
            "document_id": document_identity["document_id"],
            "version": document_identity["version"],
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
        })

    @api.get("/api/jobs/{job_id}")
    def job_detail(
        job_id: str,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        job_id = validate_job_id(job_id)
        require_database()
        tenant_id, group_id = search_context(request)
        authorize_context(identity, tenant_id, group_id)
        job_data = db.get_job(job_id, tenant_id, group_id)
        if not job_data:
            raise HTTPException(status_code=404, detail={"error": "Job nao encontrado"})
        return json_safe(job_data)

    @api.get("/api/documents/{document_id}/versions")
    def document_versions(
        document_id: str,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        document_id = validate_document_id(document_id)
        require_database()
        tenant_id, group_id = search_context(request, identity)
        authorize_context(identity, tenant_id, group_id)
        return json_safe(db.list_document_versions(document_id, tenant_id, group_id))

    @api.get("/api/documents/{document_id}/versions/current")
    def current_document_version(
        document_id: str,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        document_id = validate_document_id(document_id)
        require_database()
        tenant_id, group_id = search_context(request, identity)
        authorize_context(identity, tenant_id, group_id)
        document = db.get_current_document_version(document_id, tenant_id, group_id)
        if not document:
            raise HTTPException(status_code=404, detail={"error": "Versao padrao nao encontrada"})
        return json_safe(document)

    @api.put("/api/documents/{document_id}/versions/{version}/current")
    def set_current_version(
        document_id: str,
        version: int,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        document_id = validate_document_id(document_id)
        require_database()
        tenant_id, group_id = search_context(request)
        authorize_context(identity, tenant_id, group_id, "editor")
        try:
            selected = db.set_current_version(document_id, version, tenant_id, group_id)
        except ValueError as exc:
            status_code = 409 if "deprecated" in str(exc) else 400
            raise HTTPException(status_code=status_code, detail={"error": str(exc)}) from exc
        if not selected:
            raise HTTPException(status_code=404, detail={"error": "Versao nao encontrada"})
        return json_safe(selected)

    @api.put("/api/documents/{document_id}/versions/{version}/deprecated")
    def deprecate_version(
        document_id: str,
        version: int,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        document_id = validate_document_id(document_id)
        require_database()
        tenant_id, group_id = search_context(request)
        authorize_context(identity, tenant_id, group_id, "editor")
        try:
            updated = db.set_version_deprecated(document_id, version, True, tenant_id, group_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
        if not updated:
            raise HTTPException(status_code=404, detail={"error": "Versao nao encontrada"})
        return json_safe(updated)

    @api.delete("/api/documents/{document_id}/versions/{version}/deprecated")
    def undeprecate_version(
        document_id: str,
        version: int,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        document_id = validate_document_id(document_id)
        require_database()
        tenant_id, group_id = search_context(request)
        authorize_context(identity, tenant_id, group_id, "editor")
        try:
            updated = db.set_version_deprecated(document_id, version, False, tenant_id, group_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if not updated:
            raise HTTPException(status_code=404, detail={"error": "Versao nao encontrada"})
        return json_safe(updated)

    @api.delete("/api/documents/{document_id}/versions/{version}")
    def delete_document_version(
        document_id: str,
        version: int,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        document_id = validate_document_id(document_id)
        require_database()
        tenant_id, group_id = search_context(request)
        authorize_context(identity, tenant_id, group_id, "editor")
        try:
            deleted = db.delete_document_version(document_id, version, tenant_id, group_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail={"error": "Versao nao encontrada"})
        return json_safe(deleted)

    @api.get("/api/documents/{document_id}/versions/{version}")
    def document_version(
        document_id: str,
        version: int,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        document_id = validate_document_id(document_id)
        require_database()
        tenant_id, group_id = search_context(request)
        authorize_context(identity, tenant_id, group_id)
        document = db.get_document_summary(document_id, version, tenant_id, group_id)
        if not document:
            raise HTTPException(status_code=404, detail={"error": "Versao nao encontrada"})
        return json_safe(document)

    @api.get("/api/documents/{document_id}")
    def document_detail(
        document_id: str,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        document_id = validate_document_id(document_id)
        require_database()
        tenant_id, group_id = search_context(request)
        authorize_context(identity, tenant_id, group_id)
        document = db.get_document_summary(document_id, tenant_id=tenant_id, group_id=group_id)
        if not document:
            raise HTTPException(status_code=404, detail={"error": "Documento nao encontrado"})
        return json_safe(document)

    @api.put("/api/documents/{document_id}/name")
    async def rename_document(
        document_id: str,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        document_id = validate_document_id(document_id)
        require_database()
        tenant_id, group_id = search_context(request)
        authorize_context(identity, tenant_id, group_id, "editor")
        payload = await json_body(request)
        name = str(payload.get("name") or "").strip()
        if not 1 <= len(name) <= 255 or any(ord(char) < 32 for char in name):
            raise HTTPException(status_code=400, detail={"error": "name deve possuir entre 1 e 255 caracteres validos"})
        if not db.rename_document(document_id, name, tenant_id, group_id):
            raise HTTPException(status_code=404, detail={"error": "Documento nao encontrado"})
        return {"document_id": document_id, "name": name}

    @api.put("/api/documents/{document_id}/category")
    async def update_document_category(
        document_id: str,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        document_id = validate_document_id(document_id)
        require_database()
        tenant_id, group_id = search_context(request)
        authorize_context(identity, tenant_id, group_id, "editor")
        payload = await json_body(request)
        category_id = body_context_id(payload, "category_id", required=False)
        if category_id and not db.category_belongs_to_group(tenant_id, group_id, category_id):
            raise HTTPException(status_code=400, detail={"error": "category_id deve pertencer ao grupo informado"})
        if not db.update_document_category(document_id, category_id, tenant_id, group_id):
            raise HTTPException(status_code=404, detail={"error": "Documento nao encontrado"})
        return {"document_id": document_id, "category_id": category_id}

    @api.put("/api/documents/{document_id}/single-submission")
    async def update_single_submission(
        document_id: str,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        document_id = validate_document_id(document_id)
        require_database()
        tenant_id, group_id = search_context(request, identity)
        authorize_context(identity, tenant_id, group_id, "editor")
        payload = await json_body(request)
        try:
            enabled = validate_boolean(payload.get("single_submission_per_user"), "single_submission_per_user")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if not db.update_document_single_submission_per_user(document_id, enabled, tenant_id, group_id):
            raise HTTPException(status_code=404, detail={"error": "Documento nao encontrado"})
        return {"document_id": document_id, "single_submission_per_user": enabled}

    @api.put("/api/documents/{document_id}/document-page-submission")
    async def update_document_page_submission(
        document_id: str,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        document_id = validate_document_id(document_id)
        require_database()
        tenant_id, group_id = search_context(request, identity)
        authorize_context(identity, tenant_id, group_id, "editor")
        payload = await json_body(request)
        try:
            enabled = validate_boolean(payload.get("allow_document_page_submission"), "allow_document_page_submission")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if not db.update_document_page_submission_allowed(document_id, enabled, tenant_id, group_id):
            raise HTTPException(status_code=404, detail={"error": "Documento nao encontrado"})
        return {"document_id": document_id, "allow_document_page_submission": enabled}

    @api.put("/api/documents/{document_id}/format-norm")
    async def update_format_norm(
        document_id: str,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        document_id = validate_document_id(document_id)
        require_database()
        tenant_id, group_id = search_context(request, identity)
        authorize_context(identity, tenant_id, group_id, "editor")
        payload = await json_body(request)
        try:
            format_norm = validate_format_norm(payload.get("format_norm"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        updated = db.apply_format_norm(
            document_id,
            format_norm,
            tenant_id,
            group_id,
            identity.username or identity.subject,
        )
        if not updated:
            raise HTTPException(status_code=404, detail={"error": "Documento nao encontrado"})
        save_completed_version_job(updated)
        return json_safe({**updated, "preview": f"/jobs/{updated['job_id']}/html/index.html"})

    @api.put("/api/documents/{document_id}/html")
    async def update_document_html(
        document_id: str,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        document_id = validate_document_id(document_id)
        require_database()
        tenant_id, group_id = search_context(request, identity)
        authorize_context(identity, tenant_id, group_id, "editor")
        payload = await json_body(
            request,
            max_size=MAX_HTML_JSON_SIZE + 1024,
            message="Corpo JSON ausente ou maior que 8 MB",
        )
        try:
            html_content = validate_html_payload(payload.get("html_content"))
            source_version = payload.get("base_version")
            source_version = int(source_version) if source_version is not None else None
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        updated = db.create_edited_html_version(
            document_id,
            html_content,
            identity.username or identity.subject,
            tenant_id,
            group_id,
            source_version,
        )
        if not updated:
            raise HTTPException(status_code=404, detail={"error": "Documento nao encontrado"})
        save_completed_version_job(updated, flag="edited_html")
        return json_safe({**updated, "preview": f"/jobs/{updated['job_id']}/html/index.html"})

    @api.put("/api/documents/{job_id}/fields")
    async def update_document_fields(
        job_id: str,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        job_id = validate_job_id(job_id)
        require_database()
        tenant_id, group_id = search_context(request)
        authorize_context(identity, tenant_id, group_id, "editor")
        payload = await json_body(request, message="Corpo JSON ausente ou maior que 64 KB")
        try:
            fields = validate_fields_payload(payload.get("fields"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        result = db.update_document_fields(job_id, fields, tenant_id, group_id)
        if result is None or getattr(result, "matched_count", 1) == 0:
            raise HTTPException(status_code=404, detail={"error": "Documento nao encontrado"})
        job_data = db.get_job(job_id, tenant_id, group_id)
        if job_data and isinstance(job_data.get("result"), dict):
            updated = dict(job_data)
            updated.pop("_id", None)
            updated["result"] = {**job_data["result"], "fields": fields}
            db.save_job(job_id, updated)
        return {"job_id": job_id, "fields": fields}

    @api.delete("/api/documents/{document_id}")
    def delete_document(
        document_id: str,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        document_id = validate_document_id(document_id)
        require_database()
        tenant_id, group_id = search_context(request)
        authorize_context(identity, tenant_id, group_id, "editor")
        if not db.delete_document(document_id, tenant_id, group_id):
            raise HTTPException(status_code=404, detail={"error": "Documento nao encontrado"})
        return {"job_id": document_id, "deleted": True}

    @api.get("/api/tenants")
    def tenants(identity: Annotated[Identity, Depends(current_identity)]) -> object:
        require_database()
        if identity.has_role(authenticator.admin_role):
            return json_safe(db.list_tenants())
        return json_safe(db.list_tenants_for_user(identity.subject))

    @api.get("/api/tenants/{tenant_id}/groups")
    def groups(tenant_id: str, identity: Annotated[Identity, Depends(current_identity)]) -> object:
        tenant_id = validate_tenant_id(tenant_id)
        require_database()
        authorize_tenant_access(identity, tenant_id)
        if identity.has_role(authenticator.admin_role):
            return json_safe(db.list_groups(tenant_id))
        return json_safe(db.list_groups_for_user(identity.subject, tenant_id))

    @api.get("/api/tenants/{tenant_id}/groups/{group_id}/categories")
    def categories(
        tenant_id: str,
        group_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> object:
        tenant_id = validate_tenant_id(tenant_id)
        if not TENANT_ID_PATTERN.fullmatch(group_id):
            raise HTTPException(status_code=404, detail={"error": "Grupo nao encontrado no tenant"})
        require_database()
        if not db.group_belongs_to_tenant(tenant_id, group_id):
            raise HTTPException(status_code=404, detail={"error": "Grupo nao encontrado no tenant"})
        authorize_context(identity, tenant_id, group_id)
        return json_safe(db.list_categories(tenant_id, group_id))

    @api.post("/api/tenants")
    async def create_tenant(request: Request, identity: Annotated[Identity, Depends(current_identity)]) -> object:
        require_admin(identity)
        require_database()
        payload = await json_body(request)
        name = body_resource_name(payload, "name")
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            raise HTTPException(status_code=400, detail={"error": "metadata deve ser um objeto"})
        return JSONResponse(status_code=201, content=json_safe(db.create_tenant(name, metadata)))

    @api.post("/api/tenants/{tenant_id}/groups")
    async def create_group(
        tenant_id: str,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> Response:
        tenant_id = validate_tenant_id(tenant_id)
        require_admin(identity)
        require_database()
        payload = await json_body(request)
        name = body_resource_name(payload, "name")
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            raise HTTPException(status_code=400, detail={"error": "metadata deve ser um objeto"})
        resource = db.create_group(tenant_id, name, metadata)
        if not resource:
            raise HTTPException(status_code=404, detail={"error": "Tenant ou grupo nao encontrado"})
        return JSONResponse(status_code=201, content=json_safe(resource))

    @api.post("/api/tenants/{tenant_id}/groups/{group_id}/categories")
    async def create_category(
        tenant_id: str,
        group_id: str,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> Response:
        tenant_id = validate_tenant_id(tenant_id)
        if not TENANT_ID_PATTERN.fullmatch(group_id):
            raise HTTPException(status_code=404, detail={"error": "Tenant ou grupo nao encontrado"})
        require_admin(identity)
        require_database()
        payload = await json_body(request)
        name = body_resource_name(payload, "name")
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            raise HTTPException(status_code=400, detail={"error": "metadata deve ser um objeto"})
        resource = db.create_category(tenant_id, group_id, name, metadata)
        if not resource:
            raise HTTPException(status_code=404, detail={"error": "Tenant ou grupo nao encontrado"})
        return JSONResponse(status_code=201, content=json_safe(resource))


app = create_app()


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("fastapi_app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
