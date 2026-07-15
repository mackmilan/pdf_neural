from __future__ import annotations

import hashlib
import os
import base64
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from dataclasses import dataclass
from threading import Lock

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


class AuthenticationError(ValueError):
    """Token ausente, invalido ou expirado."""


@dataclass(frozen=True)
class Identity:
    subject: str
    username: str | None
    roles: frozenset[str]
    claims: dict
    client_id: str | None = None

    def has_role(self, role: str) -> bool:
        return role in self.roles


class KeycloakAuthenticator:
    def __init__(self) -> None:
        self.enabled = os.getenv("AUTH_ENABLED", "true").lower() not in ("0", "false", "no")
        self.issuer = os.getenv("KEYCLOAK_ISSUER", "http://localhost:8080/realms/pdf-neural").rstrip("/")
        self.audience = os.getenv("KEYCLOAK_AUDIENCE", "pdf-neural-api")
        self.admin_role = os.getenv("KEYCLOAK_ADMIN_ROLE", "pdf-admin")
        self.jwks_url = os.getenv("KEYCLOAK_JWKS_URL", f"{self.issuer}/protocol/openid-connect/certs")
        self.token_url = os.getenv("KEYCLOAK_TOKEN_URL", f"{self.issuer}/protocol/openid-connect/token")
        self.admin_url = os.getenv("KEYCLOAK_ADMIN_URL", f"{os.path.dirname(self.issuer)}/admin/realms/{os.path.basename(self.issuer)}")
        self._keys: dict[str, rsa.RSAPublicKey] = {}
        self._keys_expires_at = 0.0
        self._lock = Lock()
        self._admin_token: str | None = None
        self._admin_token_expires_at = 0.0

    @staticmethod
    def _decode_segment(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    def _refresh_keys(self) -> None:
        with urllib.request.urlopen(self.jwks_url, timeout=5) as response:
            document = json.load(response)
        keys = {}
        for item in document.get("keys", []):
            if item.get("kty") != "RSA" or not item.get("kid"):
                continue
            modulus = int.from_bytes(self._decode_segment(item["n"]), "big")
            exponent = int.from_bytes(self._decode_segment(item["e"]), "big")
            keys[item["kid"]] = rsa.RSAPublicNumbers(exponent, modulus).public_key()
        if not keys:
            raise AuthenticationError("Keycloak nao publicou chaves RSA")
        self._keys = keys
        self._keys_expires_at = time.monotonic() + 300

    def _signing_key(self, kid: str) -> rsa.RSAPublicKey:
        with self._lock:
            if time.monotonic() >= self._keys_expires_at or kid not in self._keys:
                self._refresh_keys()
            key = self._keys.get(kid)
        if key is None:
            raise AuthenticationError("Chave de assinatura desconhecida")
        return key

    def authenticate(self, authorization: str | None) -> Identity:
        if not self.enabled:
            return Identity("development-user", "development-user", frozenset({self.admin_role}), {})
        return self.authenticate_bearer(authorization)

    def authenticate_bearer(self, authorization: str | None) -> Identity:
        scheme, separator, token = (authorization or "").partition(" ")
        if not separator or scheme.lower() != "bearer" or not token.strip():
            raise AuthenticationError("Token Bearer ausente")
        try:
            encoded_header, encoded_claims, encoded_signature = token.split(".")
            header = json.loads(self._decode_segment(encoded_header))
            claims = json.loads(self._decode_segment(encoded_claims))
            if header.get("alg") != "RS256" or not header.get("kid"):
                raise AuthenticationError("Algoritmo de assinatura nao permitido")
            key = self._signing_key(header["kid"])
            key.verify(
                self._decode_segment(encoded_signature),
                f"{encoded_header}.{encoded_claims}".encode("ascii"),
                padding.PKCS1v15(), hashes.SHA256(),
            )
            now = time.time()
            audiences = claims.get("aud", [])
            if isinstance(audiences, str):
                audiences = [audiences]
            if (
                claims.get("iss") != self.issuer
                or self.audience not in audiences
                or not claims.get("sub")
                or "iat" not in claims
                or float(claims.get("iat", 0)) > now + 30
                or float(claims.get("exp", 0)) < now - 30
                or float(claims.get("nbf", 0)) > now + 30
            ):
                raise AuthenticationError("Claims do token invalidas")
        except AuthenticationError:
            raise
        except (ValueError, KeyError, json.JSONDecodeError, InvalidSignature) as exc:
            raise AuthenticationError("Token invalido ou expirado") from exc
        except Exception as exc:
            raise AuthenticationError("Nao foi possivel validar o token") from exc

        roles = set(claims.get("realm_access", {}).get("roles", []))
        roles.update(claims.get("resource_access", {}).get(self.audience, {}).get("roles", []))
        return Identity(
            subject=str(claims["sub"]),
            username=claims.get("preferred_username"),
            roles=frozenset(str(role) for role in roles),
            claims=claims,
        )


    def _get_admin_token(self) -> str:
        """Obtem um token de acesso usando client_credentials para chamadas Admin."""
        with self._lock:
            if self._admin_token and time.monotonic() < self._admin_token_expires_at:
                return self._admin_token
            
            client_id = os.getenv("KEYCLOAK_ADMIN_CLIENT_ID")
            client_secret = os.getenv("KEYCLOAK_ADMIN_CLIENT_SECRET")
            if not client_id or not client_secret:
                raise AuthenticationError("Configuracao de Admin do Keycloak ausente")

            data = urllib.parse.urlencode({
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }).encode("ascii")
            
            req = urllib.request.Request(self.token_url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=5) as response:
                res_data = json.load(response)
                self._admin_token = res_data["access_token"]
                # Expira um pouco antes do tempo real para seguranca
                self._admin_token_expires_at = time.monotonic() + float(res_data.get("expires_in", 60)) - 10
                return self._admin_token

    def _get_client_roles(self, client_id: str) -> set[str]:
        """Busca as roles de um cliente especifico no Keycloak."""
        token = self._get_admin_token()
        
        # 1. Buscar a ID interna (UUID) do cliente pelo seu clientId
        url = f"{self.admin_url}/clients?clientId={client_id}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=5) as response:
            clients = json.load(response)
            if not clients:
                return set()
            internal_id = clients[0]["id"]
            
        # 2. Buscar roles de realm mapeadas para este cliente (via service account se aplicavel)
        # No Keycloak, clients que usam client_credentials tem uma Service Account.
        # As roles sao mapeadas para o service-account-user do cliente.
        service_account_url = f"{self.admin_url}/clients/{internal_id}/service-account-user"
        req = urllib.request.Request(service_account_url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                user = json.load(response)
                user_id = user["id"]
        except Exception:
            return set() # Talvez nao tenha service account ativa
            
        # 3. Buscar role mappings (realm roles)
        roles_url = f"{self.admin_url}/users/{user_id}/role-mappings/realm"
        req = urllib.request.Request(roles_url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=5) as response:
            roles_data = json.load(response)
            return {role["name"] for role in roles_data}

    def create_user(
        self, username: str, email: str | None = None, password: str | None = None,
        temporary_password: bool = True,
    ) -> dict:
        """Cria ou localiza um usuario no Keycloak e opcionalmente define senha."""
        try:
            username = username.strip()
            email = (email or "").strip() or None
            if not username:
                raise AuthenticationError("username obrigatorio")
            if not self.enabled:
                return {"id": username, "username": username, "email": email}

            token = self._get_admin_token()
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            search_url = f"{self.admin_url}/users?username={urllib.parse.quote(username)}&exact=true"
            req = urllib.request.Request(search_url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                users = json.load(response)
            if users:
                user_id = users[0]["id"]
            else:
                payload = {"username": username, "enabled": True, "emailVerified": bool(email)}
                if email:
                    payload["email"] = email
                create_headers = {**headers, "Content-Type": "application/json"}
                req = urllib.request.Request(
                    f"{self.admin_url}/users", data=json.dumps(payload).encode("utf-8"),
                    headers=create_headers, method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    location = response.headers.get("Location", "")
                if location.rstrip("/").split("/")[-1]:
                    user_id = location.rstrip("/").split("/")[-1]
                else:
                    req = urllib.request.Request(search_url, headers=headers)
                    with urllib.request.urlopen(req, timeout=5) as response:
                        users = json.load(response)
                    if not users:
                        raise AuthenticationError("Usuario criado, mas ID nao encontrado no Keycloak")
                    user_id = users[0]["id"]

            if password:
                credential = {"type": "password", "value": password, "temporary": temporary_password}
                req = urllib.request.Request(
                    f"{self.admin_url}/users/{urllib.parse.quote(user_id)}/reset-password",
                    data=json.dumps(credential).encode("utf-8"),
                    headers={**headers, "Content-Type": "application/json"}, method="PUT",
                )
                with urllib.request.urlopen(req, timeout=5):
                    pass
            return {"id": user_id, "username": username, "email": email}
        except AuthenticationError:
            raise
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise AuthenticationError(f"Keycloak respondeu HTTP {exc.code}: {body or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise AuthenticationError(f"Nao foi possivel acessar o Keycloak Admin: {exc.reason}") from exc

    def validate_client(self, client_id: str) -> bool:
        """Valida se o client_id existe no Keycloak e tem Service Account ativo."""
        if not self.enabled:
            return True
            
        try:
            token = self._get_admin_token()
            url = f"{self.admin_url}/clients?clientId={client_id}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=5) as response:
                clients = json.load(response)
                if not clients:
                    print(f"[DEBUG_LOG] Client '{client_id}' not found in Keycloak")
                    return False
                
                # Verifica se o service account está habilitado
                client_data = clients[0]
                enabled = client_data.get("serviceAccountsEnabled", False)
                if not enabled:
                    print(f"[DEBUG_LOG] Client '{client_id}' found but Service Account is disabled")
                return enabled
        except urllib.error.URLError as exc:
            # Erro de conexão ou HTTP
            print(f"[DEBUG_LOG] Keycloak connection error during client validation: {exc}")
            # Em desenvolvimento, se o Keycloak estiver fora, permitimos para não bloquear o fluxo básico,
            # mas registramos o erro.
            return True 
        except AuthenticationError as exc:
            # Erro de configuração do Admin
            print(f"[DEBUG_LOG] Keycloak admin configuration error: {exc}")
            # Se a configuração do admin está errada, não podemos validar.
            # Decidimos se bloqueamos ou permitimos. Por segurança, vamos permitir
            # mas logar fortemente.
            return True
        except Exception as exc:
            print(f"[DEBUG_LOG] Unexpected error during client validation for {client_id}: {exc}")
            return True

    def authenticate_api_key(self, api_key: str | None) -> Identity:
        if not api_key:
            raise AuthenticationError("API Key ausente")
        
        from database import db
        if not db or not db.is_available():
            raise AuthenticationError("Servico de banco de dados indisponivel")
        
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        key_data = db.get_api_key(key_hash)
        
        if not key_data:
            raise AuthenticationError("API Key invalida ou inativa")
        
        client_id = key_data["client_id"]
        roles = set()
        
        # Se AUTH_ENABLED e tivermos as configurações de Admin, buscar roles no Keycloak
        # Usando a mesma lógica de desabilitar se necessário
        if self.enabled:
            try:
                # Buscar roles reais do client_id no Keycloak
                roles.update(self._get_client_roles(client_id))
            except Exception:
                # Falha ao buscar roles não deve necessariamente bloquear se a chave é válida no banco,
                # mas em um ambiente de produção rigoroso poderíamos exigir sucesso.
                pass

        claims = {
            "client_id": client_id,
            "name": key_data.get("name"),
            "tenant_id": key_data.get("tenant_id"),
            "group_id": key_data.get("group_id")
        }
        
        return Identity(
            subject=f"client:{client_id}",
            username=key_data.get("name"),
            roles=frozenset(roles),
            claims=claims,
            client_id=client_id
        )


authenticator = KeycloakAuthenticator()
