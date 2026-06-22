from __future__ import annotations

import os
import base64
import json
import time
import urllib.request
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

    def has_role(self, role: str) -> bool:
        return role in self.roles


class KeycloakAuthenticator:
    def __init__(self) -> None:
        self.enabled = os.getenv("AUTH_ENABLED", "true").lower() not in ("0", "false", "no")
        self.issuer = os.getenv("KEYCLOAK_ISSUER", "http://localhost:8080/realms/pdf-neural").rstrip("/")
        self.audience = os.getenv("KEYCLOAK_AUDIENCE", "pdf-neural-api")
        self.admin_role = os.getenv("KEYCLOAK_ADMIN_ROLE", "pdf-admin")
        self.jwks_url = os.getenv("KEYCLOAK_JWKS_URL", f"{self.issuer}/protocol/openid-connect/certs")
        self._keys: dict[str, rsa.RSAPublicKey] = {}
        self._keys_expires_at = 0.0
        self._lock = Lock()

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


authenticator = KeycloakAuthenticator()
