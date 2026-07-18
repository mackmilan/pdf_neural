from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.app.api.helpers import safe_static_response


router = APIRouter()


@router.get("/")
def index() -> FileResponse:
    return safe_static_response("index.html")


@router.get("/favicon.svg")
def favicon() -> FileResponse:
    return safe_static_response("favicon.svg")


@router.get("/icons.svg")
def icons() -> FileResponse:
    return safe_static_response("icons.svg")


@router.get("/assets/{asset_path:path}")
def assets(asset_path: str) -> FileResponse:
    return safe_static_response(f"assets/{asset_path}")


@router.get("/{spa_path:path}")
def spa_fallback(spa_path: str) -> FileResponse:
    if spa_path in {
        "documentos",
        "documentos/",
        "documentos-disponiveis",
        "documentos-disponiveis/",
        "usuarios",
        "usuarios/",
        "submissoes",
        "submissoes/",
        "preenchidos",
        "preenchidos/",
    }:
        return safe_static_response("index.html")
    if re.fullmatch(r"documento/(?:[0-9a-f]{32}|[0-9a-f]{64})/?", spa_path):
        return safe_static_response("index.html")
    if re.fullmatch(r"submissao/[0-9a-f]{32}/?", spa_path):
        return safe_static_response("index.html")
    raise HTTPException(status_code=404, detail={"error": "Arquivo nao encontrado"})
