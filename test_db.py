import os
import json
import uuid
from pathlib import Path
from database import db

def test_mongodb_connection():
    print("Testando conexão com MongoDB...")
    try:
        # Tenta listar as coleções para validar a conexão
        collections = db.db.list_collection_names()
        print(f"Conexão OK. Coleções: {collections}")
    except Exception as e:
        print(f"Erro de conexão: {e}")
        return False
    return True

def test_save_document():
    print("\nTestando salvamento de documento...")
    job_id = uuid.uuid4().hex
    html_content = "<html><body><h1>Teste</h1></body></html>"
    fields = [{"name": "campo1", "value": "valor1"}]
    tables = [{"id": "tabela1", "rows": []}]
    metadata = {"test": True}

    try:
        res = db.save_document(job_id, html_content, fields, tables, metadata)
        print(f"Documento salvo. Matched: {res.matched_count}, Upserted ID: {res.upserted_id}")
        
        doc = db.get_document(job_id)
        if doc and doc["job_id"] == job_id:
            print("Documento recuperado com sucesso!")
            print(f"Campos: {len(doc['fields'])}")
            return True
        else:
            print("Falha ao recuperar documento.")
    except Exception as e:
        print(f"Erro ao salvar/recuperar: {e}")
    
    return False

if __name__ == "__main__":
    if test_mongodb_connection():
        test_save_document()
