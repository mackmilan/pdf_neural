from __future__ import annotations

import logging
import math
import re
import os
import hashlib
import uuid
from datetime import datetime
from typing import Any
from pymongo import MongoClient, ReturnDocument
from dotenv import load_dotenv

import formatting

load_dotenv()

LOGGER = logging.getLogger("pdf-neural.database")

_UNCHANGED = object()

FIELD_TEXT_FONT_SIZE = 12
FIELD_TEXT_LINE_HEIGHT = 1.2
FIELD_TEXT_VERTICAL_PADDING = 4
FIELD_TEXT_HEIGHT = math.ceil(FIELD_TEXT_FONT_SIZE * FIELD_TEXT_LINE_HEIGHT + FIELD_TEXT_VERTICAL_PADDING)
FIELD_CHOICE_WIDTH = 14
FIELD_CHOICE_HEIGHT = 18
FIELD_ALIGNS = {"left", "center", "justify", "right"}


def normalized_field_height(field: dict) -> float:
    if field.get("type") in {"checkbox", "radio"}:
        return float(FIELD_CHOICE_HEIGHT)
    if field.get("type") == "textarea":
        try:
            height = float(field.get("height"))
        except (TypeError, ValueError):
            return float(FIELD_TEXT_HEIGHT)
        return height if math.isfinite(height) and height > 0 else float(FIELD_TEXT_HEIGHT)
    return float(FIELD_TEXT_HEIGHT)


def normalize_choice_box(box: dict) -> dict:
    item = dict(box)
    item["width"] = float(FIELD_CHOICE_WIDTH)
    item["height"] = float(FIELD_CHOICE_HEIGHT)
    return item


def normalize_field_heights(fields: list[dict]) -> list[dict]:
    """Mantem campos com dimensoes padrao para texto e controles de escolha."""
    normalized = []
    for field in fields or []:
        item = dict(field)
        item["height"] = normalized_field_height(item)
        if item.get("type") in {"checkbox", "radio"}:
            item["width"] = float(FIELD_CHOICE_WIDTH)
        if item.get("type") == "radio" and isinstance(item.get("option_boxes"), list):
            item["option_boxes"] = [normalize_choice_box(box) for box in item["option_boxes"]]
        if item.get("align") not in FIELD_ALIGNS:
            item["align"] = "left"
        normalized.append(item)
    return normalized


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
        self.categories = None
        self.user_access = None
        self.api_keys = None
        self.document_submissions = None
        
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
                self.categories = self.db.get_collection("document_categories")
                self.user_access = self.db.get_collection("user_access")
                self.api_keys = self.db.get_collection("api_keys")
                self.document_submissions = self.db.get_collection("document_submissions")
                self.documents.create_index("document_id", unique=True, sparse=True)
                self.versions.create_index([("document_id", 1), ("version", 1)], unique=True)
                self.versions.create_index("job_id", unique=True)
                self.tenants.create_index("tenant_id", unique=True)
                self.groups.create_index([("tenant_id", 1), ("group_id", 1)], unique=True)
                category_indexes = self.categories.index_information()
                for legacy_name in ("tenant_id_1_category_id_1", "tenant_id_1_name_1"):
                    if legacy_name in category_indexes:
                        self.categories.drop_index(legacy_name)
                self.categories.create_index(
                    [("tenant_id", 1), ("group_id", 1), ("category_id", 1)], unique=True
                )
                self.categories.create_index(
                    [("tenant_id", 1), ("group_id", 1), ("name", 1)], unique=True
                )
                self.user_access.create_index(
                    [("subject", 1), ("tenant_id", 1), ("group_id", 1)], unique=True
                )
                self.user_access.create_index([("subject", 1), ("tenant_id", 1)])
                self.api_keys.create_index("key_hash", unique=True)
                self.api_keys.create_index("client_id")
                self.document_submissions.create_index("submission_id", unique=True)
                self.document_submissions.create_index([("document_id", 1), ("created_at", -1)])
                self.document_submissions.create_index([("subject", 1), ("created_at", -1)])
                self.document_submissions.create_index([("document_id", 1), ("subject", 1), ("created_at", -1)])
                self.document_submissions.create_index([("tenant_id", 1), ("group_id", 1), ("created_at", -1)])
                self.documents.create_index([("tenant_id", 1), ("group_id", 1), ("updated_at", -1)])
                self.documents.create_index([("tenant_id", 1), ("category_id", 1), ("updated_at", -1)])
                LOGGER.info("Conexão com MongoDB estabelecida com sucesso")
            except Exception as exc:
                LOGGER.error("Falha ao conectar no MongoDB: %s", str(exc))
                self.client = None
                self.db = self.documents = self.versions = self.jobs = self.tenants = self.groups = self.categories = self.user_access = self.api_keys = self.document_submissions = None
        else:
            LOGGER.warning("MONGO_URI não configurada. Operações de banco de dados serão ignoradas.")

    def is_available(self) -> bool:
        return self.jobs is not None

    def get_api_key(self, key_hash: str) -> dict | None:
        """Busca uma chave de API ativa pelo hash."""
        if not self.is_available() or self.api_keys is None:
            return None
        return self.api_keys.find_one({"key_hash": key_hash, "active": True})

    def create_api_key(self, client_id: str, name: str, tenant_id: str | None = None, group_id: str | None = None) -> str:
        """Gera e salva uma nova API Key."""
        if not self.is_available() or self.api_keys is None:
            raise RuntimeError("Banco de dados indisponível")
        
        raw_key = f"ak_{uuid.uuid4().hex}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        
        self.api_keys.insert_one({
            "client_id": client_id,
            "name": name,
            "key_hash": key_hash,
            "tenant_id": tenant_id,
            "group_id": group_id,
            "active": True,
            "created_at": datetime.utcnow()
        })
        return raw_key

    def list_api_keys(self, tenant_id: str, group_id: str | None = None) -> list[dict]:
        """Lista as chaves de API de um tenant/grupo."""
        if not self.is_available() or self.api_keys is None:
            return []
        query = {"tenant_id": tenant_id, "active": True}
        if group_id:
            query["group_id"] = group_id
        
        keys = list(self.api_keys.find(query).sort("created_at", -1))
        # Remover o hash do retorno por segurança, embora seja um hash, não é necessário no front
        for k in keys:
            k.pop("key_hash", None)
            if "_id" in k:
                k["_id"] = str(k["_id"])
        return keys

    def revoke_api_key(self, client_id: str, tenant_id: str, group_id: str | None = None) -> bool:
        """Desativa uma chave de API."""
        if not self.is_available() or self.api_keys is None:
            return False
        query = {"client_id": client_id, "tenant_id": tenant_id}
        if group_id:
            query["group_id"] = group_id
        
        result = self.api_keys.update_many(query, {"$set": {"active": False, "revoked_at": datetime.utcnow()}})
        return result.modified_count > 0

    def save_job(self, job_id: str, data: dict):
        """
        Salva ou atualiza o estado de um job.
        """
        if not self.is_available():
            return None
        
        LOGGER.debug("Salvando status do job %s no banco", job_id)
        if isinstance(data.get("result"), dict) and isinstance(data["result"].get("fields"), list):
            data = {**data, "result": {**data["result"], "fields": normalize_field_heights(data["result"]["fields"])}}
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

    def create_category(
        self, tenant_id: str, group_id: str, name: str, metadata: dict | None = None,
    ) -> dict | None:
        if not self.group_belongs_to_tenant(tenant_id, group_id):
            return None
        now = datetime.utcnow()
        category = {
            "tenant_id": tenant_id, "group_id": group_id,
            "category_id": uuid.uuid4().hex, "name": name,
            "metadata": metadata or {}, "created_at": now, "updated_at": now,
        }
        self.categories.insert_one(category)
        return category

    def list_categories(self, tenant_id: str, group_id: str) -> list[dict]:
        if not self.is_available():
            return []
        return list(self.categories.find(
            {"tenant_id": tenant_id, "group_id": group_id}
        ).sort("name", 1))

    def category_belongs_to_group(
        self, tenant_id: str, group_id: str | None, category_id: str | None,
    ) -> bool:
        return not category_id or self.categories.find_one(
            {"tenant_id": tenant_id, "group_id": group_id, "category_id": category_id}
        ) is not None

    def group_belongs_to_tenant(self, tenant_id: str, group_id: str) -> bool:
        if not tenant_id:
            return False
        if not group_id:
            return self.tenants.find_one({"tenant_id": tenant_id}) is not None
        return self.groups.find_one({"tenant_id": tenant_id, "group_id": group_id}) is not None

    def grant_user_access(
        self, subject: str, tenant_id: str, group_id: str | None = None,
        permission: str = "reader", username: str | None = None,
    ) -> dict | None:
        if permission not in ("reader", "editor") or not self.group_belongs_to_tenant(tenant_id, group_id):
            return None
        now = datetime.utcnow()
        key = {"subject": subject, "tenant_id": tenant_id, "group_id": group_id}
        self.user_access.update_one(
            key,
            {"$set": {"permission": permission, "username": username, "updated_at": now},
             "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        return {**key, "permission": permission, "username": username}

    def list_user_access(self, subject: str) -> list[dict]:
        if not self.is_available():
            return []
        return list(self.user_access.find({"subject": subject}).sort([("tenant_id", 1), ("group_id", 1)]))

    def list_all_user_access(self) -> list[dict]:
        if not self.is_available():
            return []
        tenants = {
            tenant["tenant_id"]: tenant
            for tenant in self.tenants.find({}, {"_id": 0, "tenant_id": 1, "name": 1})
        }
        groups = {
            (group["tenant_id"], group["group_id"]): group
            for group in self.groups.find({}, {"_id": 0, "tenant_id": 1, "group_id": 1, "name": 1})
        }
        users: dict[str, dict] = {}
        cursor = self.user_access.find().sort([("username", 1), ("subject", 1), ("tenant_id", 1), ("group_id", 1)])
        for access in cursor:
            subject = access["subject"]
            user = users.setdefault(subject, {
                "subject": subject,
                "username": access.get("username"),
                "access": [],
            })
            if access.get("username") and not user.get("username"):
                user["username"] = access["username"]
            tenant_id = access.get("tenant_id")
            group_id = access.get("group_id")
            tenant = tenants.get(tenant_id, {})
            group = groups.get((tenant_id, group_id), {}) if group_id else {}
            user["access"].append({
                "subject": subject,
                "username": access.get("username"),
                "tenant_id": tenant_id,
                "tenant_name": tenant.get("name"),
                "group_id": group_id,
                "group_name": group.get("name"),
                "permission": access.get("permission"),
                "created_at": access.get("created_at"),
                "updated_at": access.get("updated_at"),
            })
        return list(users.values())

    def revoke_user_access(self, subject: str, tenant_id: str, group_id: str | None = None) -> bool:
        if not self.is_available():
            return False
        return self.user_access.delete_one(
            {"subject": subject, "tenant_id": tenant_id, "group_id": group_id}
        ).deleted_count > 0

    def delete_user_access(self, subject: str) -> int:
        if not self.is_available():
            return 0
        return self.user_access.delete_many({"subject": subject}).deleted_count

    def user_has_access(
        self, subject: str, tenant_id: str, group_id: str | None = None,
        permission: str = "reader",
    ) -> bool:
        if not self.is_available():
            return False
        query: dict[str, Any] = {"subject": subject, "tenant_id": tenant_id}
        if group_id:
            query["$or"] = [{"group_id": None}, {"group_id": group_id}]
        else:
            query["group_id"] = None
        if permission == "editor":
            query["permission"] = "editor"
        return self.user_access.find_one(query) is not None

    def list_tenants_for_user(self, subject: str) -> list[dict]:
        tenant_ids = self.user_access.distinct("tenant_id", {"subject": subject})
        return list(self.tenants.find({"tenant_id": {"$in": tenant_ids}}).sort("name", 1))

    def list_groups_for_user(self, subject: str, tenant_id: str) -> list[dict]:
        if self.user_access.find_one({"subject": subject, "tenant_id": tenant_id, "group_id": None}):
            return self.list_groups(tenant_id)
        group_ids = self.user_access.distinct(
            "group_id", {"subject": subject, "tenant_id": tenant_id, "group_id": {"$ne": None}}
        )
        return list(self.groups.find({"tenant_id": tenant_id, "group_id": {"$in": group_ids}}).sort("name", 1))

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
        category_id: str | None = None,
        single_submission_per_user: bool = False,
        allow_document_page_submission: bool = False,
    ):
        """Cria uma versão e atualiza o ponteiro do documento canônico."""
        if not self.is_available():
            return None
        fields = normalize_field_heights(fields)
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
                "$set": {
                    "metadata": metadata, "tenant_id": tenant_id, "group_id": group_id,
                    "category_id": category_id, "single_submission_per_user": bool(single_submission_per_user),
                    "allow_document_page_submission": bool(allow_document_page_submission),
                    "updated_at": now,
                },
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
            "deprecated": False,
            "html_content": html_content,
            "fields": fields,
            "tables": tables,
            "pages": pages or [],
            "neural_tables": neural_tables or [],
            "metadata": metadata,
            "created_at": now,
            "tenant_id": tenant_id,
            "group_id": group_id,
            "category_id": category_id,
            "single_submission_per_user": bool(single_submission_per_user),
            "allow_document_page_submission": bool(allow_document_page_submission),
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
                    "category_id": category_id,
                    "single_submission_per_user": bool(single_submission_per_user),
                    "allow_document_page_submission": bool(allow_document_page_submission),
                }},
            )
            return {
                "document_id": document_id, "version": version_number, "job_id": job_id,
                "is_current": True, "tenant_id": tenant_id, "group_id": group_id,
                "category_id": category_id, "single_submission_per_user": bool(single_submission_per_user),
                "allow_document_page_submission": bool(allow_document_page_submission),
            }
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
            current = self.versions.find_one({"document_id": identifier, "version": version, **scope})
            if current:
                current.setdefault("deprecated", False)
            return current
        current = self.versions.find_one({"job_id": identifier, **scope})
        if current:
            current.setdefault("deprecated", False)
            return current
        current = self.versions.find_one({"document_id": identifier, "is_current": True, **scope})
        if current:
            current.setdefault("deprecated", False)
            return current
        latest = self.versions.find_one(
            {"document_id": identifier, **scope},
            sort=[("version", -1)],
        )
        if latest:
            latest.setdefault("deprecated", False)
            return latest
        return self.documents.find_one({"job_id": identifier, **scope})

    def get_document_summary(self, identifier: str, version: int | None = None, tenant_id: str | None = None, group_id: str | None = None):
        """Retorna dados da interface sem transferir o HTML potencialmente grande."""
        if not self.is_available():
            return None
        document = self.get_document(identifier, version, tenant_id, group_id)
        if document:
            document.pop("html_content", None)
        return document

    def save_document_submission(
        self, document: dict, subject: str, email: str | None, values: dict,
    ) -> dict:
        """Salva o preenchimento do visualizador em uma collection isolada."""
        if not self.is_available() or self.document_submissions is None:
            raise RuntimeError("Banco de dados indisponivel")
        submission = {
            "submission_id": uuid.uuid4().hex,
            "document_id": document.get("document_id") or document.get("job_id"),
            "job_id": document.get("job_id"),
            "version": document.get("version"),
            "tenant_id": document.get("tenant_id"),
            "group_id": document.get("group_id"),
            "subject": subject,
            "email": email,
            "values": values,
            "created_at": datetime.utcnow(),
        }
        self.document_submissions.insert_one(submission)
        return submission

    def user_already_submitted_document(self, document: dict, subject: str) -> bool:
        """Verifica se o usuario ja salvou um preenchimento para o documento canonico."""
        if not self.is_available() or self.document_submissions is None:
            return False
        document_id = document.get("document_id") or document.get("job_id")
        if not document_id or not subject:
            return False
        return self.document_submissions.find_one({"document_id": document_id, "subject": subject}) is not None

    def get_document_submission(self, submission_id: str):
        """Busca um preenchimento salvo pelo protocolo da submissao."""
        if not self.is_available() or self.document_submissions is None:
            return None
        return self.document_submissions.find_one({"submission_id": submission_id})

    def list_document_submissions_for_user(self, subject: str, limit: int = 50) -> list[dict]:
        """Lista preenchimentos salvos por usuario, com metadados basicos do documento."""
        if not self.is_available() or self.document_submissions is None:
            return []
        items = []
        cursor = self.document_submissions.find({"subject": subject}).sort("created_at", -1).limit(limit)
        for submission in cursor:
            document = self.get_document(
                submission.get("document_id") or submission.get("job_id"),
                submission.get("version"),
                submission.get("tenant_id"),
                submission.get("group_id"),
            )
            metadata = (document or {}).get("metadata") or {}
            items.append({
                "submission_id": submission.get("submission_id"),
                "document_id": submission.get("document_id"),
                "job_id": submission.get("job_id"),
                "version": submission.get("version"),
                "tenant_id": submission.get("tenant_id"),
                "group_id": submission.get("group_id"),
                "created_at": submission.get("created_at"),
                "email": submission.get("email"),
                "document_name": (document or {}).get("name") or metadata.get("filename") or "Documento submetido",
            })
        return items

    def list_all_document_submissions(
        self,
        tenant_id: str | None = None,
        group_id: str | None = None,
        category_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        user: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Lista preenchimentos de todos os usuarios para a visao administrativa."""
        if not self.is_available() or self.document_submissions is None:
            return []
        query: dict[str, Any] = {}
        if tenant_id:
            query["tenant_id"] = tenant_id
        if group_id:
            query["group_id"] = group_id
        if date_from or date_to:
            created_at: dict[str, datetime] = {}
            if date_from:
                created_at["$gte"] = date_from
            if date_to:
                created_at["$lt"] = date_to
            query["created_at"] = created_at
        if user:
            pattern = {"$regex": re.escape(user), "$options": "i"}
            user_filter: list[dict[str, Any]] = [{"subject": pattern}, {"email": pattern}]
            if self.user_access is not None:
                matching_subjects = self.user_access.distinct("subject", {"username": pattern})
                if matching_subjects:
                    user_filter.append({"subject": {"$in": matching_subjects}})
            query["$or"] = user_filter

        tenants = {
            tenant["tenant_id"]: tenant
            for tenant in self.tenants.find({}, {"_id": 0, "tenant_id": 1, "name": 1})
        } if self.tenants is not None else {}
        groups = {
            (group["tenant_id"], group["group_id"]): group
            for group in self.groups.find({}, {"_id": 0, "tenant_id": 1, "group_id": 1, "name": 1})
        } if self.groups is not None else {}
        categories = {
            (category.get("tenant_id"), category.get("group_id"), category.get("category_id")): category
            for category in self.categories.find({}, {"_id": 0, "tenant_id": 1, "group_id": 1, "category_id": 1, "name": 1})
            if category.get("tenant_id") and category.get("category_id")
        } if self.categories is not None else {}
        usernames = {
            access["subject"]: access.get("username")
            for access in self.user_access.find({}, {"_id": 0, "subject": 1, "username": 1})
            if access.get("username")
        } if self.user_access is not None else {}

        items = []
        cursor = self.document_submissions.find(query).sort("created_at", -1).limit(max(1, min(limit, 500)))
        for submission in cursor:
            document = self.get_document(
                submission.get("document_id") or submission.get("job_id"),
                submission.get("version"),
                submission.get("tenant_id"),
                submission.get("group_id"),
            )
            document_category_id = (document or {}).get("category_id")
            if category_id and document_category_id != category_id:
                continue
            metadata = (document or {}).get("metadata") or {}
            submission_tenant_id = submission.get("tenant_id")
            submission_group_id = submission.get("group_id")
            tenant = tenants.get(submission_tenant_id, {})
            group = groups.get((submission_tenant_id, submission_group_id), {}) if submission_group_id else {}
            category = categories.get((submission_tenant_id, submission_group_id, document_category_id), {}) if document_category_id else {}
            subject = submission.get("subject")
            items.append({
                "submission_id": submission.get("submission_id"),
                "document_id": submission.get("document_id"),
                "job_id": submission.get("job_id"),
                "version": submission.get("version"),
                "tenant_id": submission_tenant_id,
                "tenant_name": tenant.get("name"),
                "group_id": submission_group_id,
                "group_name": group.get("name"),
                "category_id": document_category_id,
                "category_name": category.get("name"),
                "created_at": submission.get("created_at"),
                "subject": subject,
                "username": usernames.get(subject),
                "email": submission.get("email"),
                "document_name": (document or {}).get("name") or metadata.get("filename") or "Documento submetido",
            })
        return items

    def list_submittable_documents_for_user(self, subject: str | None = None, limit: int = 100) -> list[dict]:
        """Lista documentos atuais com campos, respeitando os escopos do usuario."""
        if not self.is_available():
            return []
        query: dict[str, Any] = {
            "fields.0": {"$exists": True},
            "allow_document_page_submission": True,
        }
        if subject:
            scopes = []
            for item in self.list_user_access(subject):
                tenant_id = item.get("tenant_id")
                if not tenant_id:
                    continue
                group_id = item.get("group_id")
                scopes.append({"tenant_id": tenant_id, "group_id": group_id})
            if not scopes:
                return []
            query["$or"] = scopes
        documents = list(
            self.documents.find(query, {"html_content": 0})
            .sort("updated_at", -1)
            .limit(limit)
        )
        if subject:
            documents = [
                document for document in documents
                if not (
                    document.get("single_submission_per_user")
                    and self.user_already_submitted_document(document, subject)
                )
            ]
        return documents

    def get_current_document_version(self, document_id: str, tenant_id: str | None = None, group_id: str | None = None):
        """Retorna somente a versao padrao de um documento."""
        if not self.is_available():
            return None
        query = {"document_id": document_id, "is_current": True}
        if tenant_id:
            query["tenant_id"] = tenant_id
        if group_id:
            query["group_id"] = group_id
        current = self.versions.find_one(query)
        if current:
            current.setdefault("deprecated", False)
        return current

    def list_document_versions(self, document_id: str, tenant_id: str | None = None, group_id: str | None = None) -> list[dict]:
        if not self.is_available():
            return []
        query = {"document_id": document_id}
        if tenant_id:
            query["tenant_id"] = tenant_id
        if group_id:
            query["group_id"] = group_id
        versions = list(self.versions.find(query, {"html_content": 0}).sort("version", -1))
        for version in versions:
            version.setdefault("deprecated", False)
        return versions

    def set_current_version(
        self, document_id: str, version: int,
        tenant_id: str | None = None, group_id: str | None = None,
    ):
        """Define uma versão existente como a versão padrão do documento."""
        if not self.is_available():
            return None
        scope = {}
        if tenant_id:
            scope["tenant_id"] = tenant_id
        if group_id:
            scope["group_id"] = group_id
        selected = self.versions.find_one({"document_id": document_id, "version": version, **scope})
        if not selected:
            return None
        if selected.get("deprecated", False):
            raise ValueError("Uma versao deprecated nao pode ser definida como padrao")
        now = datetime.utcnow()
        self.versions.update_many({"document_id": document_id, **scope}, {"$set": {"is_current": False}})
        self.versions.update_one(
            {"document_id": document_id, "version": version, **scope},
            {"$set": {"is_current": True, "selected_as_current_at": now}},
        )
        self.documents.update_one(
            {"document_id": document_id, **scope},
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

    def update_document_single_submission_per_user(
        self, document_id: str, enabled: bool,
        tenant_id: str, group_id: str | None = None,
    ) -> bool:
        """Atualiza a regra de preenchimento unico no documento e registros relacionados."""
        if not self.is_available():
            return False
        scope: dict[str, Any] = {"tenant_id": tenant_id}
        if group_id:
            scope["group_id"] = group_id
        canonical = self.documents.find_one({"document_id": document_id, **scope})
        if not canonical:
            return False
        now = datetime.utcnow()
        value = bool(enabled)
        self.documents.update_one(
            {"document_id": document_id, **scope},
            {"$set": {"single_submission_per_user": value, "updated_at": now}},
        )
        versions = list(self.versions.find(
            {"document_id": document_id, **scope}, {"job_id": 1}
        ))
        self.versions.update_many(
            {"document_id": document_id, **scope},
            {"$set": {"single_submission_per_user": value}},
        )
        job_ids = [item["job_id"] for item in versions if item.get("job_id")]
        if job_ids:
            self.jobs.update_many(
                {"job_id": {"$in": job_ids}, "tenant_id": tenant_id},
                {"$set": {"single_submission_per_user": value, "updated_at": now}},
            )
        return True

    def update_document_page_submission_allowed(
        self, document_id: str, enabled: bool,
        tenant_id: str, group_id: str | None = None,
    ) -> bool:
        """Atualiza se o documento pode ser preenchido pela pagina de documento."""
        if not self.is_available():
            return False
        scope: dict[str, Any] = {"tenant_id": tenant_id}
        if group_id:
            scope["group_id"] = group_id
        canonical = self.documents.find_one({"document_id": document_id, **scope})
        if not canonical:
            return False
        now = datetime.utcnow()
        value = bool(enabled)
        self.documents.update_one(
            {"document_id": document_id, **scope},
            {"$set": {"allow_document_page_submission": value, "updated_at": now}},
        )
        versions = list(self.versions.find(
            {"document_id": document_id, **scope}, {"job_id": 1}
        ))
        self.versions.update_many(
            {"document_id": document_id, **scope},
            {"$set": {"allow_document_page_submission": value}},
        )
        job_ids = [item["job_id"] for item in versions if item.get("job_id")]
        if job_ids:
            self.jobs.update_many(
                {"job_id": {"$in": job_ids}, "tenant_id": tenant_id},
                {"$set": {"allow_document_page_submission": value, "updated_at": now}},
            )
        return True

    def set_version_deprecated(
        self, document_id: str, version: int, deprecated: bool = True,
        tenant_id: str | None = None, group_id: str | None = None,
    ):
        """Marca ou desmarca uma versao como obsoleta sem apagar seu historico."""
        if not self.is_available():
            return None
        scope = {}
        if tenant_id:
            scope["tenant_id"] = tenant_id
        if group_id:
            scope["group_id"] = group_id
        query = {"document_id": document_id, "version": version, **scope}
        selected = self.versions.find_one(query)
        if not selected:
            return None
        if deprecated and selected.get("is_current"):
            raise ValueError("A versao padrao nao pode ser marcada como deprecated")
        now = datetime.utcnow()
        update = {"deprecated": deprecated, "deprecated_at": now if deprecated else None}
        self.versions.update_one(query, {"$set": update})
        return {
            "document_id": document_id, "version": version,
            "job_id": selected["job_id"], "is_current": bool(selected.get("is_current")),
            **update,
        }

    def delete_document_version(
        self, document_id: str, version: int,
        tenant_id: str | None = None, group_id: str | None = None,
    ):
        """Remove uma versao nao atual do historico."""
        if not self.is_available():
            return None
        scope = {}
        if tenant_id:
            scope["tenant_id"] = tenant_id
        if group_id:
            scope["group_id"] = group_id
        query = {"document_id": document_id, "version": version, **scope}
        selected = self.versions.find_one(query)
        if not selected:
            return None
        if selected.get("is_current"):
            raise ValueError("A versao padrao nao pode ser excluida")
        result = self.versions.delete_one(query)
        if selected.get("job_id"):
            self.jobs.delete_one({"job_id": selected["job_id"], **scope})
            self.db.get_collection("images").delete_many({"job_id": selected["job_id"]})
        return {
            "document_id": document_id,
            "version": version,
            "job_id": selected.get("job_id"),
            "deleted": result.deleted_count > 0,
        }

    def update_document_fields(
        self, job_id: str, fields: list[dict],
        tenant_id: str | None = None, group_id: str | None = None,
    ):
        """Persiste a revisao manual dos campos de um documento."""
        if not self.is_available():
            return None
        fields = normalize_field_heights(fields)
        now = datetime.utcnow()
        scope = {}
        if tenant_id:
            scope["tenant_id"] = tenant_id
        if group_id:
            scope["group_id"] = group_id
        version = self.versions.find_one({"job_id": job_id, **scope})
        if not version:
            return self.documents.update_one({"job_id": job_id, **scope}, {"$set": {"fields": fields, "fields_updated_at": now}})
        result = self.versions.update_one({"job_id": job_id, **scope}, {"$set": {"fields": fields, "fields_updated_at": now}})
        if version.get("is_current"):
            self.documents.update_one({"document_id": version["document_id"], **scope}, {"$set": {"fields": fields, "fields_updated_at": now}})
        return result

    def create_edited_html_version(
        self, document_id: str, html_content: str, edited_by: str | None = None,
        tenant_id: str | None = None, group_id: str | None = None,
        source_version: int | None = None, format_norm: str | None = _UNCHANGED,
    ):
        """Cria uma nova versao do documento com o HTML revisado manualmente."""
        if not self.is_available():
            return None
        scope = {}
        if tenant_id:
            scope["tenant_id"] = tenant_id
        if group_id:
            scope["group_id"] = group_id
        source_query = {"document_id": document_id, **scope}
        if source_version is None:
            source_query["is_current"] = True
        else:
            source_query["version"] = source_version
        current = self.versions.find_one(source_query)
        if not current:
            return None
        now = datetime.utcnow()
        canonical = self.documents.find_one_and_update(
            {"document_id": document_id, **scope},
            {"$inc": {"current_version": 1}, "$set": {"updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if not canonical:
            return None
        version_number = int(canonical["current_version"])
        job_id = uuid.uuid4().hex
        metadata = dict(current.get("metadata", {}))
        metadata["edited_html"] = True
        metadata["edited_at"] = now
        if edited_by:
            metadata["edited_by"] = edited_by
        resolved_format_norm = current.get("format_norm") if format_norm is _UNCHANGED else format_norm
        self.versions.update_many({"document_id": document_id, **scope, "is_current": True}, {"$set": {"is_current": False}})
        version_doc = {
            "document_id": document_id,
            "job_id": job_id,
            "version": version_number,
            "is_current": True,
            "deprecated": False,
            "html_content": html_content,
            "fields": normalize_field_heights(current.get("fields", [])),
            "tables": current.get("tables", []),
            "pages": current.get("pages", []),
            "neural_tables": current.get("neural_tables", []),
            "metadata": metadata,
            "created_at": now,
            "tenant_id": current.get("tenant_id"),
            "group_id": current.get("group_id"),
            "category_id": current.get("category_id"),
            "single_submission_per_user": bool(current.get("single_submission_per_user", False)),
            "allow_document_page_submission": bool(current.get("allow_document_page_submission", False)),
            "format_norm": resolved_format_norm,
            "edited_from_version": current.get("version"),
        }
        self.versions.insert_one(version_doc)
        self.documents.update_one(
            {"document_id": document_id, **scope},
            {"$set": {
                "job_id": job_id, "current_job_id": job_id, "current_version": version_number,
                "fields": version_doc["fields"], "tables": version_doc["tables"],
                "pages": version_doc["pages"], "neural_tables": version_doc["neural_tables"],
                "metadata": metadata, "category_id": version_doc["category_id"],
                "tenant_id": version_doc["tenant_id"], "group_id": version_doc["group_id"],
                "format_norm": resolved_format_norm,
                "single_submission_per_user": version_doc["single_submission_per_user"],
                "allow_document_page_submission": version_doc["allow_document_page_submission"],
                "is_current": True, "updated_at": now,
            }},
        )
        return {
            "document_id": document_id, "version": version_number, "job_id": job_id,
            "is_current": True, "fields": version_doc["fields"], "tables": version_doc["tables"],
            "neural_tables": version_doc["neural_tables"], "metadata": metadata,
            "tenant_id": version_doc["tenant_id"], "group_id": version_doc["group_id"],
            "category_id": version_doc["category_id"], "format_norm": resolved_format_norm,
            "single_submission_per_user": version_doc["single_submission_per_user"],
            "allow_document_page_submission": version_doc["allow_document_page_submission"],
        }

    def apply_format_norm(
        self, document_id: str, format_norm: str | None,
        tenant_id: str | None = None, group_id: str | None = None,
        edited_by: str | None = None,
    ):
        """Aplica a norma de formatacao escolhida ao HTML da versao atual, criando uma nova versao."""
        if not self.is_available():
            return None
        scope = {}
        if tenant_id:
            scope["tenant_id"] = tenant_id
        if group_id:
            scope["group_id"] = group_id
        current = self.versions.find_one({"document_id": document_id, **scope, "is_current": True})
        if not current:
            return None
        formatted_html = formatting.apply_format_norm(current["html_content"], format_norm)
        return self.create_edited_html_version(
            document_id, formatted_html, edited_by, tenant_id, group_id,
            source_version=current["version"], format_norm=format_norm,
        )

    def update_document_category(
        self, document_id: str, category_id: str | None,
        tenant_id: str, group_id: str | None = None,
    ) -> bool:
        """Atualiza a categoria no documento canônico, versões e jobs relacionados."""
        if not self.is_available() or not self.category_belongs_to_group(tenant_id, group_id, category_id):
            return False
        scope: dict[str, Any] = {"tenant_id": tenant_id}
        if group_id:
            scope["group_id"] = group_id
        canonical = self.documents.find_one({"document_id": document_id, **scope})
        if not canonical:
            return False
        now = datetime.utcnow()
        self.documents.update_one(
            {"document_id": document_id, **scope},
            {"$set": {"category_id": category_id, "updated_at": now}},
        )
        versions = list(self.versions.find({"document_id": document_id, **scope}, {"job_id": 1}))
        self.versions.update_many(
            {"document_id": document_id, **scope}, {"$set": {"category_id": category_id}}
        )
        job_ids = [item["job_id"] for item in versions if item.get("job_id")]
        if job_ids:
            self.jobs.update_many(
                {"job_id": {"$in": job_ids}, "tenant_id": tenant_id},
                {"$set": {"category_id": category_id}},
            )
        return True

    def rename_document(
        self, document_id: str, name: str,
        tenant_id: str, group_id: str | None = None,
    ) -> bool:
        """Atualiza o nome visivel do documento e de todos os registros relacionados."""
        if not self.is_available():
            return False
        scope: dict[str, Any] = {"tenant_id": tenant_id}
        if group_id:
            scope["group_id"] = group_id
        canonical = self.documents.find_one({"document_id": document_id, **scope})
        if not canonical:
            return False
        now = datetime.utcnow()
        self.documents.update_one(
            {"document_id": document_id, **scope},
            {"$set": {"metadata.filename": name, "updated_at": now}},
        )
        versions = list(self.versions.find(
            {"document_id": document_id, **scope}, {"job_id": 1}
        ))
        self.versions.update_many(
            {"document_id": document_id, **scope},
            {"$set": {"metadata.filename": name}},
        )
        job_ids = [item["job_id"] for item in versions if item.get("job_id")]
        if job_ids:
            self.jobs.update_many(
                {"job_id": {"$in": job_ids}, "tenant_id": tenant_id},
                {"$set": {"metadata.filename": name, "updated_at": now}},
            )
        return True

    def delete_document(
        self, identifier: str, tenant_id: str | None = None, group_id: str | None = None,
    ) -> bool:
        """Remove documento, estado do job e imagens vinculadas."""
        if not self.is_available():
            return False
        scope = {}
        if tenant_id:
            scope["tenant_id"] = tenant_id
        if group_id:
            scope["group_id"] = group_id
        canonical = self.documents.find_one({"document_id": identifier, **scope})
        if canonical:
            job_ids = [item["job_id"] for item in self.versions.find({"document_id": identifier, **scope}, {"job_id": 1})]
            self.documents.delete_one({"document_id": identifier, **scope})
            self.versions.delete_many({"document_id": identifier, **scope})
            self.jobs.delete_many({"job_id": {"$in": job_ids}})
            self.db.get_collection("images").delete_many({"job_id": {"$in": job_ids}})
            return True
        deleted = self.documents.delete_one({"job_id": identifier, **scope})
        if deleted.deleted_count == 0:
            return False
        self.jobs.delete_one({"job_id": identifier})
        self.db.get_collection("images").delete_many({"job_id": identifier})
        return True

    def list_jobs(self, limit: int = 10, tenant_id: str | None = None, group_id: str | None = None, category_id: str | None = None):
        if not self.is_available():
            return []
        query = {}
        if tenant_id:
            query["tenant_id"] = tenant_id
        if group_id:
            query["group_id"] = group_id
        if category_id:
            query["category_id"] = category_id
        return list(self.jobs.find(query).sort("created_at", -1).limit(limit))

    def list_documents(
        self, page: int = 1, page_size: int = 10, tenant_id: str | None = None,
        group_id: str | None = None, category_id: str | None = None,
        name: str | None = None,
    ) -> dict:
        if not self.is_available():
            return {"items": [], "page": page, "page_size": page_size, "total": 0, "total_pages": 0}
        query = {}
        if tenant_id:
            query["tenant_id"] = tenant_id
        if group_id:
            query["group_id"] = group_id
        if category_id:
            query["category_id"] = category_id
        if name:
            query["metadata.filename"] = {"$regex": re.escape(name), "$options": "i"}
        total = self.documents.count_documents(query)
        items = list(
            self.documents.find(query, {"html_content": 0})
            .sort("updated_at", -1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size) if total else 0,
        }

# Instância global para uso no app
db = Database()
