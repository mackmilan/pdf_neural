import json
import urllib.request
import urllib.error

def test_api_auth():
    # Nota: Este teste assume que o servidor está rodando em localhost:8000
    # e que acabamos de gerar uma chave válida (podemos gerar uma nova aqui para garantir)
    from database import Database
    db = Database()
    key = db.create_api_key("integration_test", "Integration Test Key")
    print(f"Testando com chave: {key}")

    url = "http://localhost:8000/api/me"
    headers = {"X-API-Key": key}
    
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            print("Resposta /api/me:")
            print(json.dumps(data, indent=2))
            if data.get("client_id") == "integration_test":
                print("Autenticação via API Key: SUCESSO")
            else:
                print("Autenticação via API Key: FALHA (client_id incorreto)")
    except urllib.error.URLError as e:
        print(f"Erro ao conectar ao servidor: {e}")
        print("Certifique-se de que o app.py está rodando.")

if __name__ == "__main__":
    test_api_auth()
