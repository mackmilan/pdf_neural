import os
from datetime import datetime
from typing import Any
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

class Database:
    def __init__(self, uri: str = None):
        self.uri = uri or os.getenv("MONGO_URI")
        self.client = None
        self.db = None
        self.documents = None
        self.jobs = None
        
        if self.uri:
            try:
                self.client = MongoClient(self.uri, serverSelectionTimeoutMS=2000)
                # Tenta um comando simples para validar a conexão
                self.client.admin.command('ping')
                self.db = self.client.get_database()
                self.documents = self.db.get_collection("documents")
                self.jobs = self.db.get_collection("jobs")
            except Exception:
                self.client = None

    def is_available(self) -> bool:
        return self.jobs is not None

    def save_job(self, job_id: str, data: dict):
        """
        Salva ou atualiza o estado de um job.
        """
        if not self.is_available():
            return None
        data["updated_at"] = datetime.utcnow()
        if "created_at" not in data:
            data["created_at"] = data["updated_at"]
        
        return self.jobs.update_one(
            {"job_id": job_id},
            {"$set": data},
            upsert=True
        )

    def get_job(self, job_id: str):
        if not self.is_available():
            return None
        return self.jobs.find_one({"job_id": job_id})

    def save_document(
        self,
        job_id: str,
        html_content: str,
        fields: list[dict],
        tables: list[dict],
        metadata: dict = None,
        pages: list[dict] = None,
        neural_tables: list[dict] = None,
    ):
        """
        Armazena a estrutura HTML, campos JSON e tabelas relacionados a um job_id.
        """
        if not self.is_available():
            return None
        doc = {
            "job_id": job_id,
            "html_content": html_content,
            "fields": fields,
            "tables": tables,
            "pages": pages or [],
            "neural_tables": neural_tables or [],
            "metadata": metadata or {},
            "created_at": datetime.utcnow()
        }
        return self.documents.update_one(
            {"job_id": job_id},
            {"$set": doc},
            upsert=True
        )

    def save_image(self, job_id: str, image_key: str, data_hash: str, base64_data: str, content_type: str = "image/png"):
        """
        Armazena uma imagem em base64 associada a um job.
        """
        if not self.is_available():
            return None
        
        image_doc = {
            "job_id": job_id,
            "image_key": image_key,
            "data_hash": data_hash,
            "base64_data": base64_data,
            "content_type": content_type,
            "created_at": datetime.utcnow()
        }
        
        return self.db.get_collection("images").update_one(
            {"job_id": job_id, "data_hash": data_hash},
            {"$set": image_doc},
            upsert=True
        )

    def get_image(self, job_id: str, data_hash: str):
        if not self.is_available():
            return None
        return self.db.get_collection("images").find_one({"job_id": job_id, "data_hash": data_hash})

    def get_document(self, job_id: str):
        if not self.is_available():
            return None
        return self.documents.find_one({"job_id": job_id})

    def get_document_summary(self, job_id: str):
        """Retorna dados da interface sem transferir o HTML potencialmente grande."""
        if not self.is_available():
            return None
        return self.documents.find_one({"job_id": job_id}, {"html_content": 0})

    def list_jobs(self, limit: int = 10):
        if not self.is_available():
            return []
        return list(self.jobs.find().sort("created_at", -1).limit(limit))

    def list_documents(self, limit: int = 10):
        if not self.is_available():
            return []
        return list(self.documents.find({}, {"html_content": 0}).sort("created_at", -1).limit(limit))

# Instância global para uso no app
db = Database()
