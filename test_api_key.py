import hashlib
import uuid
from datetime import datetime
from backend.app.db.mongo import Database

def test_api_key():
    db = Database()
    if not db.is_available():
        print("MongoDB não disponível")
        return

    client_id = "test_client"
    name = "Test API Key"
    
    # Criar uma API Key
    print(f"Criando API Key para {client_id}...")
    key = db.create_api_key(client_id, name)
    print(f"Chave gerada: {key}")
    
    # Validar a chave
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    key_data = db.get_api_key(key_hash)
    
    if key_data and key_data["client_id"] == client_id:
        print("Validação da API Key: SUCESSO")
    else:
        print("Validação da API Key: FALHA")
        print(f"Dados encontrados: {key_data}")

if __name__ == "__main__":
    test_api_key()
