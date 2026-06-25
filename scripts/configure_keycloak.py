#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import urllib.error
import urllib.parse
import urllib.request


def default_app_urls() -> list[str]:
    port = os.getenv("PORT")
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not port and env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "PORT":
                port = value.strip().strip("\"'")
                break
    port = port or "8000"
    return [f"http://localhost:{port}", f"http://127.0.0.1:{port}"]


def request(url: str, method: str = "GET", token: str | None = None, payload: object = None):
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, data=data, headers=headers, method=method), timeout=10
        ) as response:
            body = response.read()
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        if exc.code == 409:
            return exc.code, None
        raise RuntimeError(f"Keycloak respondeu HTTP {exc.code}: {body}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Configura realm, client e administrador do PDF Neural")
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--admin-user", default="admin")
    parser.add_argument("--admin-password", default="admin")
    parser.add_argument("--realm", default="pdf-neural")
    parser.add_argument("--app-user", default="pdf-admin")
    parser.add_argument("--app-password", help="Senha inicial; se omitida, uma senha forte e gerada")
    parser.add_argument("--reset-app-password", action="store_true")
    parser.add_argument(
        "--app-url", action="append",
        default=default_app_urls(),
        help="Origem permitida para login/logout; pode ser repetida",
    )
    args = parser.parse_args()
    base = args.url.rstrip("/")
    app_urls = list(dict.fromkeys(url.rstrip("/") for url in args.app_url))
    app_password = args.app_password or secrets.token_urlsafe(32)

    form = urllib.parse.urlencode({
        "client_id": "admin-cli", "grant_type": "password",
        "username": args.admin_user, "password": args.admin_password,
    }).encode()
    token_request = urllib.request.Request(
        f"{base}/realms/master/protocol/openid-connect/token", data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
    )
    with urllib.request.urlopen(token_request, timeout=10) as response:
        token = json.load(response)["access_token"]

    admin = f"{base}/admin/realms"
    request(admin, "POST", token, {"realm": args.realm, "enabled": True})
    realm_admin = f"{admin}/{urllib.parse.quote(args.realm)}"

    _, clients = request(f"{realm_admin}/clients?clientId=pdf-neural-api", token=token)
    if clients:
        client_uuid = clients[0]["id"]
    else:
        request(f"{realm_admin}/clients", "POST", token, {
            "clientId": "pdf-neural-api", "name": "PDF Neural API",
            "enabled": True, "publicClient": True,
            "standardFlowEnabled": True, "directAccessGrantsEnabled": True,
            "redirectUris": [f"{url}/*" for url in app_urls],
            "webOrigins": app_urls,
            "protocol": "openid-connect",
            "protocolMappers": [{
                "name": "pdf-neural-audience", "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "config": {"included.client.audience": "pdf-neural-api", "access.token.claim": "true"},
            }],
        })
        _, clients = request(f"{realm_admin}/clients?clientId=pdf-neural-api", token=token)
        client_uuid = clients[0]["id"]
    _, client = request(f"{realm_admin}/clients/{client_uuid}", token=token)
    client.update({
        "enabled": True, "publicClient": True,
        "standardFlowEnabled": True, "directAccessGrantsEnabled": True,
        "redirectUris": [f"{url}/*" for url in app_urls],
        "webOrigins": app_urls,
    })
    client["attributes"] = {
        **client.get("attributes", {}),
        "post.logout.redirect.uris": "##".join(f"{url}/*" for url in app_urls),
        "pkce.code.challenge.method": "S256",
    }
    request(f"{realm_admin}/clients/{client_uuid}", "PUT", token, client)

    request(f"{realm_admin}/roles", "POST", token, {"name": "pdf-admin"})
    _, roles = request(f"{realm_admin}/roles/pdf-admin", token=token)

    _, users = request(
        f"{realm_admin}/users?username={urllib.parse.quote(args.app_user)}&exact=true", token=token
    )
    if users:
        user_id = users[0]["id"]
        user_created = False
    else:
        request(f"{realm_admin}/users", "POST", token, {
            "username": args.app_user, "enabled": True,
            "credentials": [{"type": "password", "value": app_password, "temporary": False}],
        })
        _, users = request(
            f"{realm_admin}/users?username={urllib.parse.quote(args.app_user)}&exact=true", token=token
        )
        user_id = users[0]["id"]
        user_created = True
    request(f"{realm_admin}/users/{user_id}", "PUT", token, {
        "username": args.app_user, "enabled": True,
        "firstName": "PDF", "lastName": "Admin",
        "email": "pdf-admin@localhost", "emailVerified": True,
        "requiredActions": [],
    })
    if user_created or args.reset_app_password:
        request(f"{realm_admin}/users/{user_id}/reset-password", "PUT", token, {
            "type": "password", "value": app_password, "temporary": False,
        })
    request(f"{realm_admin}/users/{user_id}/role-mappings/realm", "POST", token, [roles])

    print(f"Realm configurado: {args.realm}")
    print("Client: pdf-neural-api")
    print(f"Usuario administrador da aplicacao: {args.app_user}")
    print(f"Keycloak subject (sub): {user_id}")
    print(f"Client UUID: {client_uuid}")
    if user_created or args.reset_app_password:
        print(f"Senha inicial da aplicacao: {app_password}")


if __name__ == "__main__":
    main()
