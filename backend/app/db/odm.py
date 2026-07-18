from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pymongo import MongoClient


class OdmBackendUnavailable(RuntimeError):
    pass


class MongoDocument(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)


class ApiKeyDocument(MongoDocument):
    client_id: str
    name: str
    key_hash: str
    tenant_id: str | None = None
    group_id: str | None = None
    active: bool = True
    created_at: datetime


class JobDocument(MongoDocument):
    job_id: str
    status: str | None = None
    tenant_id: str | None = None
    group_id: str | None = None
    category_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TenantDocument(MongoDocument):
    tenant_id: str
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class TenantGroupDocument(MongoDocument):
    tenant_id: str
    group_id: str
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class DocumentCategoryDocument(MongoDocument):
    tenant_id: str
    group_id: str
    category_id: str
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class UserAccessDocument(MongoDocument):
    subject: str
    tenant_id: str
    group_id: str | None = None
    permission: str = "reader"
    username: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocumentRecord(MongoDocument):
    document_id: str | None = None
    job_id: str | None = None
    tenant_id: str | None = None
    group_id: str | None = None
    category_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    fields: list[dict[str, Any]] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    pages: list[dict[str, Any]] = Field(default_factory=list)
    neural_tables: list[dict[str, Any]] = Field(default_factory=list)
    current_version: int | None = None
    is_current: bool | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocumentVersionDocument(DocumentRecord):
    document_id: str
    job_id: str
    version: int
    is_current: bool = False
    deprecated: bool = False
    html_content: str | None = None


class ImageDocument(MongoDocument):
    job_id: str
    image_key: str
    data_hash: str
    base64_data: str
    content_type: str = "image/png"
    created_at: datetime


class DocumentSubmissionDocument(MongoDocument):
    submission_id: str
    document_id: str
    job_id: str | None = None
    version: int | None = None
    tenant_id: str | None = None
    group_id: str | None = None
    subject: str
    email: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


ODM_MODELS: dict[str, type[MongoDocument]] = {
    "api_keys": ApiKeyDocument,
    "jobs": JobDocument,
    "tenants": TenantDocument,
    "tenant_groups": TenantGroupDocument,
    "document_categories": DocumentCategoryDocument,
    "user_access": UserAccessDocument,
    "documents": DocumentRecord,
    "document_versions": DocumentVersionDocument,
    "images": ImageDocument,
    "document_submissions": DocumentSubmissionDocument,
}


class MongoOdmStore:
    def __init__(self, uri: str):
        self.client = MongoClient(uri, serverSelectionTimeoutMS=2000)
        try:
            self.db = self.client.get_database()
        except Exception:
            self.db = self.client.get_database("pdf_neural")

    def get_collection(self, name: str) -> "OdmCollection":
        return OdmCollection(self.db.get_collection(name), ODM_MODELS.get(name, MongoDocument))


class OdmCollection:
    def __init__(self, collection, model: type[MongoDocument]):
        self.collection = collection
        self.model = model

    def __getattr__(self, name: str):
        return getattr(self.collection, name)

    def insert_one(self, document: dict[str, Any], *args, **kwargs):
        return self.collection.insert_one(self._validate_document(document), *args, **kwargs)

    def update_one(self, filter: dict[str, Any], update: dict[str, Any], *args, **kwargs):
        self._validate_update(update)
        return self.collection.update_one(filter, update, *args, **kwargs)

    def update_many(self, filter: dict[str, Any], update: dict[str, Any], *args, **kwargs):
        self._validate_update(update)
        return self.collection.update_many(filter, update, *args, **kwargs)

    def find_one_and_update(self, filter: dict[str, Any], update: dict[str, Any], *args, **kwargs):
        self._validate_update(update)
        return self.collection.find_one_and_update(filter, update, *args, **kwargs)

    def _validate_document(self, document: dict[str, Any]) -> dict[str, Any]:
        validated = self.model.model_validate(document)
        return validated.model_dump(exclude_none=False)

    def _validate_update(self, update: dict[str, Any]) -> None:
        if not isinstance(update, dict):
            raise TypeError("Atualizacao de documento deve ser um dicionario")
        operators = [key for key in update if key.startswith("$")]
        if operators:
            invalid = [key for key in operators if key not in {"$set", "$setOnInsert", "$inc", "$unset"}]
            if invalid:
                raise ValueError(f"Operadores MongoDB nao suportados pelo ODM: {', '.join(invalid)}")
