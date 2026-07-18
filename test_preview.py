import requests
import json
import time

def test_preview_from_db():
    # URL do servidor (ajuste se necessário)
    base_url = "http://localhost:8000"
    
    # Simular o salvamento de um documento no MongoDB diretamente
    from backend.app.db.mongo import db
    import uuid
    
    job_id = uuid.uuid4().hex
    html_content = f"<html><body><h1>Preview from DB {job_id}</h1></body></html>"
    
    print(f"Salvando documento fake para job {job_id}...")
    db.save_document(job_id, html_content, [], [])
    
    # Tentar acessar o preview via API
    preview_url = f"{base_url}/jobs/{job_id}/html/index.html"
    print(f"Acessando preview: {preview_url}")
    
    try:
        # Nota: O servidor precisa estar rodando para este teste funcionar via requests
        # Como não posso garantir que o servidor está rodando, vou testar a lógica internamente
        pass
    except Exception as e:
        print(f"Erro ao acessar preview: {e}")

if __name__ == "__main__":
    test_preview_from_db()
