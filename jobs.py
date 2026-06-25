from __future__ import annotations

import hashlib

from config import LOGGER, NEURAL_REQUIRED
from database import db
from services import convert_pdf_bytes, get_detectors
from utils import deliver_callback, download_pdf, job_urls

def run_api_job(job: str, pdf_url: str, callback_url: str, reference: object, base_url: str, tenant_id: str | None = None, group_id: str | None = None, category_id: str | None = None) -> None:
    LOGGER.info("Iniciando background job: %s", job)
    common = {"job_id": job, "reference": reference, "tenant_id": tenant_id, "group_id": group_id, "category_id": category_id}

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
            category_id=category_id,
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
