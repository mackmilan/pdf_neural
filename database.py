from __future__ import annotations

import logging
import os
import hashlib
import uuid
from datetime import datetime
from typing import Any
from pymongo import MongoClient, ReturnDocument
from dotenv import load_dotenv

load_dotenv()

LOGGER = logging.getLogger("pdf-neural.database")

class Database:
    def __init__(self, uri: str = None):
        self.uri = uri or os.getenv("MONGO_URI")
        self.client = None
        self.db = None
        self.documents = None
        self.versions = None
        self.jobs = None
        self.tenants = None
        self.groups = None
        
        if self.uri:
            LOGGER.info("Conectando ao MongoDB...")
            try:
                self.client = MongoClient(self.uri, serverSelectionTimeoutMS=2000)
                # Tenta obter o banco de dados da URI, se não existir usa 'pdf_neural' como padrão
                try:
                    self.db = self.client.get_database()
                except Exception:
                    LOGGER.warning("Nenhum banco de dados definido na MONGO_URI, usando 'pdf_neural' por padrão")
                    self.db = self.client.get_database("pdf_neural")
                
                self.documents = self.db.get_collection("documents")
                self.versions = self.db.get_collection("document_versions")
                self.jobs = self.db.get_collection("jobs")
                self.tenants = self.db.get_collection("tenants")
                self.groups = self.db.get_collection("tenant_groups")
                self.documents.create_index("document_id", unique=True, sparse=True)
                self.versions.create_index([("document_id", 1), ("version", 1)], unique=True)
                self.versions.create_index("job_id", unique=True)
                self.tenants.create_index("tenant_id", unique=True)
                self.groups.create_index([("tenant_id", 1), ("group_id", 1)], unique=True)
                self.documents.create_index([("tenant_id", 1), ("group_id", 1), ("updated_at", -1)])
                LOGGER.info("Conexão com MongoDB estabelecida com sucesso")
            except Exception as exc:
                LOGGER.error("Falha ao conectar no MongoDB: %s", str(exc))
                self.client = None
                self.db = self.documents = self.versions = self.jobs = self.tenants = self.groups = None
        else:
            LOGGER.warning("MONGO_URI não configurada. Operações de banco de dados serão ignoradas.")

    def is_available(self) -> bool:
        return self.jobs is not None

    def save_job(self, job_id: str, data: dict):
        """
        Salva ou atualiza o estado de um job.
        """
        if not self.is_available():
            return None
        
        LOGGER.debug("Salvando status do job %s no banco", job_id)
        data["updated_at"] = datetime.utcnow()
        if "created_at" not in data:
            data["created_at"] = data["updated_at"]
        
        try:
            return self.jobs.update_one(
                {"job_id": job_id},
                {"$set": data},
                upsert=True
            )
        except Exception:
            LOGGER.exception("Erro ao salvar job %s no MongoDB", job_id)
            return None

    def get_job(self, job_id: str, tenant_id: str | None = None, group_id: str | None = None):
        if not self.is_available():
            return None
        LOGGER.debug("Buscando job %s no MongoDB", job_id)
        query = {"job_id": job_id}
        if tenant_id:
            query["tenant_id"] = tenant_id
        if group_id:
            query["group_id"] = group_id
        return self.jobs.find_one(query)

    def create_tenant(self, name: str, metadata: dict | None = None) -> dict:
        now = datetime.utcnow()
        tenant = {
            "tenant_id": uuid.uuid4().hex, "name": name, "metadata": metadata or {},
            "created_at": now, "updated_at": now,
        }
        self.tenants.insert_one(tenant)
        return tenant

    def list_tenants(self) -> list[dict]:
        if not self.is_available():
            return []
        return list(self.tenants.find().sort("name", 1))

    def create_group(self, tenant_id: str, name: str, metadata: dict | None = None) -> dict | None:
        if not self.tenants.find_one({"tenant_id": tenant_id}):
            return None
        now = datetime.utcnow()
        group = {
            "tenant_id": tenant_id, "group_id": uuid.uuid4().hex, "name": name,
            "metadata": metadata or {}, "created_at": now, "updated_at": now,
        }
        self.groups.insert_one(group)
        return group

    def list_groups(self, tenant_id: str) -> list[dict]:
        if not self.is_available():
            return []
        return list(self.groups.find({"tenant_id": tenant_id}).sort("name", 1))

    def group_belongs_to_tenant(self, tenant_id: str, group_id: str) -> bool:
        if not tenant_id:
            return False
        if not group_id:
            return self.tenants.find_one({"tenant_id": tenant_id}) is not None
        return self.groups.find_one({"tenant_id": tenant_id, "group_id": group_id}) is not None

    def save_document(
        self,
        job_id: str,
        html_content: str,
        fields: list[dict],
        tables: list[dict],
        metadata: dict = None,
        pages: list[dict] = None,
        neural_tables: list[dict] = None,
        content_hash: str | None = None,
        tenant_id: str | None = None,
        group_id: str | None = None,
    ):
        """Cria uma versão e atualiza o ponteiro do documento canônico."""
        if not self.is_available():
            return None
        metadata = metadata or {}
        raw_content_hash = content_hash or metadata.get("content_hash") or job_id
        document_id = (
            hashlib.sha256(f"{tenant_id}:{group_id or ''}:{raw_content_hash}".encode()).hexdigest()
            if tenant_id else raw_content_hash
        )
        now = datetime.utcnow()
        LOGGER.info("Salvando versão do documento %s para job %s", document_id, job_id)
        canonical = self.documents.find_one_and_update(
            {"document_id": document_id},
            {
                "$setOnInsert": {"document_id": document_id, "content_hash": raw_content_hash, "created_at": now},
                "$set": {"metadata": metadata, "tenant_id": tenant_id, "group_id": group_id, "updated_at": now},
                "$inc": {"current_version": 1},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        version_number = int(canonical["current_version"])
        self.versions.update_many({"document_id": document_id, "is_current": True}, {"$set": {"is_current": False}})
        version_doc = {
            "document_id": document_id,
            "job_id": job_id,
            "version": version_number,
            "is_current": True,
            "html_content": html_content,
            "fields": fields,
            "tables": tables,
            "pages": pages or [],
            "neural_tables": neural_tables or [],
            "metadata": metadata,
            "created_at": now,
            "tenant_id": tenant_id,
            "group_id": group_id,
        }
        try:
            self.versions.insert_one(version_doc)
            self.documents.update_one(
                {"document_id": document_id},
                {"$set": {
                    "job_id": job_id, "current_job_id": job_id, "current_version": version_number,
                    "fields": fields, "tables": tables, "pages": pages or [],
                    "neural_tables": neural_tables or [], "is_current": True,
                    "tenant_id": tenant_id, "group_id": group_id,
                }},
            )
            return {"document_id": document_id, "version": version_number, "job_id": job_id, "is_current": True, "tenant_id": tenant_id, "group_id": group_id}
        except Exception:
            LOGGER.exception("Erro ao salvar versão do job %s no MongoDB", job_id)
            return None

    def save_image(self, job_id: str, image_key: str, data_hash: str, base64_data: str, content_type: str = "image/png"):
        """
        Armazena uma imagem em base64 associada a um job.
        """
        if not self.is_available():
            return None
        
        LOGGER.debug("Salvando imagem %s (hash: %s) para job %s no MongoDB", image_key, data_hash, job_id)
        image_doc = {
            "job_id": job_id,
            "image_key": image_key,
            "data_hash": data_hash,
            "base64_data": base64_data,
            "content_type": content_type,
            "created_at": datetime.utcnow()
        }
        
        try:
            return self.db.get_collection("images").update_one(
                {"job_id": job_id, "data_hash": data_hash},
                {"$set": image_doc},
                upsert=True
            )
        except Exception:
            LOGGER.exception("Erro ao salvar imagem %s do job %s no MongoDB", image_key, job_id)
            return None

    def get_image(self, job_id: str, data_hash: str):
        if not self.is_available():
            return None
        LOGGER.debug("Buscando imagem (hash: %s) do job %s no MongoDB", data_hash, job_id)
        return self.db.get_collection("images").find_one({"job_id": job_id, "data_hash": data_hash})

    def get_document(self, identifier: str, version: int | None = None, tenant_id: str | None = None, group_id: str | None = None):
        if not self.is_available():
            return None
        scope = {}
        if tenant_id:
            scope["tenant_id"] = tenant_id
        if group_id:
            scope["group_id"] = group_id
        if version is not None:
            return self.versions.find_one({"document_id": identifier, "version": version, **scope})
        current = self.versions.find_one({"job_id": identifier, **scope})
        if current:
            return current
        current = self.versions.find_one({"document_id": identifier, "is_current": True, **scope})
        if current:
            return current
        return self.documents.find_one({"job_id": identifier, **scope})

    def get_document_summary(self, identifier: str, version: int | None = None, tenant_id: str | None = None, group_id: str | None = None):
        """Retorna dados da interface sem transferir o HTML potencialmente grande."""
        if not self.is_available():
            return None
        document = self.get_document(identifier, version, tenant_id, group_id)
        if document:
            document.pop("html_content", None)
        return document

    def list_document_versions(self, document_id: str, tenant_id: str | None = None, group_id: str | None = None) -> list[dict]:
        if not self.is_available():
            return []
        query = {"document_id": document_id}
        if tenant_id:
            query["tenant_id"] = tenant_id
        if group_id:
            query["group_id"] = group_id
        return list(self.versions.find(query, {"html_content": 0}).sort("version", -1))

    def set_current_version(self, document_id: str, version: int):
        """Define uma versão existente como a versão padrão do documento."""
        if not self.is_available():
            return None
        selected = self.versions.find_one({"document_id": document_id, "version": version})
        if not selected:
            return None
        now = datetime.utcnow()
        self.versions.update_many({"document_id": document_id}, {"$set": {"is_current": False}})
        self.versions.update_one(
            {"document_id": document_id, "version": version},
            {"$set": {"is_current": True, "selected_as_current_at": now}},
        )
        self.documents.update_one(
            {"document_id": document_id},
            {"$set": {
                "job_id": selected["job_id"], "current_job_id": selected["job_id"],
                "current_version": version, "is_current": True,
                "fields": selected.get("fields", []), "tables": selected.get("tables", []),
                "pages": selected.get("pages", []),
                "neural_tables": selected.get("neural_tables", []),
                "metadata": selected.get("metadata", {}), "updated_at": now,
            }},
        )
        return {"document_id": document_id, "version": version, "job_id": selected["job_id"], "is_current": True}

    def update_document_fields(self, job_id: str, fields: list[dict]):
        """Persiste a revisao manual dos campos de um documento."""
        if not self.is_available():
            return None
        now = datetime.utcnow()
        version = self.versions.find_one({"job_id": job_id})
        if not version:
            return self.documents.update_one({"job_id": job_id}, {"$set": {"fields": fields, "fields_updated_at": now}})
        result = self.versions.update_one({"job_id": job_id}, {"$set": {"fields": fields, "fields_updated_at": now}})
        if version.get("is_current"):
            self.documents.update_one({"document_id": version["document_id"]}, {"$set": {"fields": fields, "fields_updated_at": now}})
        return result

    def delete_document(self, identifier: str) -> bool:
        """Remove documento, estado do job e imagens vinculadas."""
        if not self.is_available():
            return False
        canonical = self.documents.find_one({"document_id": identifier})
        if canonical:
            job_ids = [item["job_id"] for item in self.versions.find({"document_id": identifier}, {"job_id": 1})]
            self.documents.delete_one({"document_id": identifier})
            self.versions.delete_many({"document_id": identifier})
            self.jobs.delete_many({"job_id": {"$in": job_ids}})
            self.db.get_collection("images").delete_many({"job_id": {"$in": job_ids}})
            return True
        deleted = self.documents.delete_one({"job_id": identifier})
        if deleted.deleted_count == 0:
            return False
        self.jobs.delete_one({"job_id": identifier})
        self.db.get_collection("images").delete_many({"job_id": identifier})
        return True

    def list_jobs(self, limit: int = 10, tenant_id: str | None = None, group_id: str | None = None):
        if not self.is_available():
            return []
        query = {}
        if tenant_id:
            query["tenant_id"] = tenant_id
        if group_id:
            query["group_id"] = group_id
        return list(self.jobs.find(query).sort("created_at", -1).limit(limit))

    def list_documents(self, limit: int = 10, tenant_id: str | None = None, group_id: str | None = None):
        if not self.is_available():
            return []
        query = {}
        if tenant_id:
            query["tenant_id"] = tenant_id
        if group_id:
            query["group_id"] = group_id
        return list(self.documents.find(query, {"html_content": 0}).sort("updated_at", -1).limit(limit))

# Instância global para uso no app
db = Database()
