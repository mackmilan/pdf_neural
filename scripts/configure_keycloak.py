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


def get_client(realm_admin: str, token: str, client_id: str) -> dict | None:
    _, clients = request(f"{realm_admin}/clients?clientId={urllib.parse.quote(client_id)}", token=token)
    return clients[0] if clients else None


def get_or_create_client(realm_admin: str, token: str, client_id: str, payload: dict) -> tuple[str, dict]:
    client = get_client(realm_admin, token, client_id)
    if not client:
        request(f"{realm_admin}/clients", "POST", token, payload)
        client = get_client(realm_admin, token, client_id)
    if not client:
        raise RuntimeError(f"Client {client_id} nao encontrado apos criacao")
    return client["id"], client


def client_secret(realm_admin: str, token: str, client_uuid: str) -> str:
    _, credentials = request(f"{realm_admin}/clients/{client_uuid}/client-secret", token=token)
    return credentials["value"]


def assign_service_account_realm_management_roles(
    realm_admin: str, token: str, admin_client_uuid: str, role_names: list[str],
) -> None:
    _, service_account = request(f"{realm_admin}/clients/{admin_client_uuid}/service-account-user", token=token)
    service_account_id = service_account["id"]
    realm_management = get_client(realm_admin, token, "realm-management")
    if not realm_management:
        raise RuntimeError("Client realm-management nao encontrado")
    management_uuid = realm_management["id"]
    roles = []
    for role_name in role_names:
        _, role = request(
            f"{realm_admin}/clients/{management_uuid}/roles/{urllib.parse.quote(role_name)}",
            token=token,
        )
        roles.append(role)
    request(
        f"{realm_admin}/users/{service_account_id}/role-mappings/clients/{management_uuid}",
        "POST", token, roles,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Configura realm, client e administrador do PDF Neural")
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--admin-user", default="admin")
    parser.add_argument("--admin-password", default="admin")
    parser.add_argument("--realm", default="pdf-neural")
    parser.add_argument("--api-client-id", default="pdf-neural-api")
    parser.add_argument("--admin-client-id", default="pdf-neural-admin")
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

    client_uuid, client = get_or_create_client(realm_admin, token, args.api_client_id, {
            "clientId": args.api_client_id, "name": "PDF Neural API",
            "enabled": True, "publicClient": True,
            "standardFlowEnabled": True, "directAccessGrantsEnabled": True,
            "redirectUris": [f"{url}/*" for url in app_urls],
            "webOrigins": app_urls,
            "protocol": "openid-connect",
            "protocolMappers": [{
                "name": "pdf-neural-audience", "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "config": {"included.client.audience": args.api_client_id, "access.token.claim": "true"},
            }],
        })
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

    admin_client_uuid, admin_client = get_or_create_client(realm_admin, token, args.admin_client_id, {
        "clientId": args.admin_client_id,
        "name": "PDF Neural Admin API",
        "enabled": True,
        "publicClient": False,
        "serviceAccountsEnabled": True,
        "standardFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "protocol": "openid-connect",
    })
    admin_client.update({
        "enabled": True,
        "publicClient": False,
        "serviceAccountsEnabled": True,
        "standardFlowEnabled": False,
        "directAccessGrantsEnabled": False,
    })
    request(f"{realm_admin}/clients/{admin_client_uuid}", "PUT", token, admin_client)
    admin_secret = client_secret(realm_admin, token, admin_client_uuid)
    assign_service_account_realm_management_roles(
        realm_admin, token, admin_client_uuid,
        ["view-clients", "query-clients", "view-users", "query-users", "manage-users"],
    )

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
    print(f"Client publico: {args.api_client_id}")
    print(f"Client administrativo: {args.admin_client_id}")
    print(f"KEYCLOAK_ADMIN_CLIENT_ID={args.admin_client_id}")
    print(f"KEYCLOAK_ADMIN_CLIENT_SECRET={admin_secret}")
    print(f"Usuario administrador da aplicacao: {args.app_user}")
    print(f"Keycloak subject (sub): {user_id}")
    print(f"Client UUID: {client_uuid}")
    if user_created or args.reset_app_password:
        print(f"Senha inicial da aplicacao: {app_password}")


if __name__ == "__main__":
    main()
