import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import fastapi_app
from auth import Identity


ADMIN = Identity("admin-sub", "admin", frozenset({"pdf-admin"}), {})
READER = Identity("reader-sub", "reader", frozenset(), {})


class FastApiMigrationTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(fastapi_app.app)

    def test_auth_config_is_public(self):
        response = self.client.get("/auth/config")

        self.assertEqual(200, response.status_code)
        self.assertEqual(fastapi_app.authenticator.issuer, response.json()["issuer"])
        self.assertEqual(fastapi_app.authenticator.audience, response.json()["client_id"])
        self.assertEqual("nosniff", response.headers["x-content-type-options"])

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_me_returns_identity_and_access(self, fake_db, authenticate):
        authenticate.return_value = READER
        fake_db.is_available.return_value = True
        fake_db.list_user_access.return_value = [{"tenant_id": "a" * 32, "group_id": None}]

        response = self.client.get("/api/me", headers={"Authorization": "Bearer token"})

        self.assertEqual(200, response.status_code)
        self.assertEqual({
            "sub": "reader-sub",
            "username": "reader",
            "roles": [],
            "access": [{"tenant_id": "a" * 32, "group_id": None}],
        }, response.json())

    @patch("fastapi_app.authenticator.authenticate")
    def test_me_rejects_missing_bearer_token(self, authenticate):
        authenticate.side_effect = fastapi_app.AuthenticationError("Token Bearer ausente")

        response = self.client.get("/api/me")

        self.assertEqual(401, response.status_code)
        self.assertEqual({"error": "Token Bearer ausente"}, response.json())
        self.assertEqual('Bearer realm="pdf-neural"', response.headers["www-authenticate"])

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_admin_lists_all_tenants(self, fake_db, authenticate):
        authenticate.return_value = ADMIN
        fake_db.is_available.return_value = True
        fake_db.list_tenants.return_value = [{"tenant_id": "a" * 32, "name": "Tenant A"}]

        response = self.client.get("/api/tenants", headers={"Authorization": "Bearer token"})

        self.assertEqual(200, response.status_code)
        self.assertEqual([{"tenant_id": "a" * 32, "name": "Tenant A"}], response.json())
        fake_db.list_tenants.assert_called_once_with()

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_reader_lists_only_allowed_tenants(self, fake_db, authenticate):
        authenticate.return_value = READER
        fake_db.is_available.return_value = True
        fake_db.list_tenants_for_user.return_value = [{"tenant_id": "b" * 32, "name": "Tenant B"}]

        response = self.client.get("/api/tenants", headers={"Authorization": "Bearer token"})

        self.assertEqual(200, response.status_code)
        self.assertEqual([{"tenant_id": "b" * 32, "name": "Tenant B"}], response.json())
        fake_db.list_tenants_for_user.assert_called_once_with("reader-sub")

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_reader_must_have_tenant_access_for_groups(self, fake_db, authenticate):
        authenticate.return_value = READER
        fake_db.is_available.return_value = True
        fake_db.user_has_access.return_value = False

        response = self.client.get(f"/api/tenants/{'a' * 32}/groups", headers={"Authorization": "Bearer token"})

        self.assertEqual(403, response.status_code)
        self.assertEqual({"error": "Acesso negado ao tenant"}, response.json())

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_lists_categories_when_group_belongs_to_tenant(self, fake_db, authenticate):
        authenticate.return_value = ADMIN
        fake_db.is_available.return_value = True
        fake_db.group_belongs_to_tenant.return_value = True
        fake_db.list_categories.return_value = [{"category_id": "c" * 32, "name": "Categoria"}]

        response = self.client.get(
            f"/api/tenants/{'a' * 32}/groups/{'b' * 32}/categories",
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual([{"category_id": "c" * 32, "name": "Categoria"}], response.json())

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_lists_documents_with_legacy_pagination_validation(self, fake_db, authenticate):
        authenticate.return_value = ADMIN
        fake_db.is_available.return_value = True
        fake_db.list_documents.return_value = {
            "items": [{"document_id": "d" * 64, "metadata": {"filename": "a.pdf"}}],
            "page": 2,
            "page_size": 5,
            "total": 1,
            "total_pages": 1,
        }

        response = self.client.get(
            f"/api/documents?tenant_id={'a' * 32}&page=2&page_size=5&name=a",
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("a.pdf", response.json()["items"][0]["metadata"]["filename"])
        fake_db.list_documents.assert_called_once_with(
            page=2,
            page_size=5,
            tenant_id="a" * 32,
            group_id=None,
            category_id=None,
            name="a",
        )

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_rejects_invalid_document_pagination_like_legacy_handler(self, fake_db, authenticate):
        authenticate.return_value = ADMIN
        fake_db.is_available.return_value = True

        response = self.client.get(
            f"/api/documents?tenant_id={'a' * 32}&page=x",
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual({"error": "page e page_size devem ser numeros inteiros"}, response.json())

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_lists_jobs_with_api_key_context(self, fake_db, authenticate):
        authenticate.return_value = Identity(
            "client:robot",
            "Robot",
            frozenset(),
            {"tenant_id": "a" * 32, "group_id": "b" * 32},
            client_id="robot",
        )
        fake_db.is_available.return_value = True
        fake_db.user_has_access.return_value = True
        fake_db.list_jobs.return_value = [{"job_id": "c" * 32, "status": "done"}]

        response = self.client.get("/api/jobs", headers={"Authorization": "Bearer token"})

        self.assertEqual(200, response.status_code)
        self.assertEqual([{"job_id": "c" * 32, "status": "done"}], response.json())
        fake_db.list_jobs.assert_called_once_with(
            tenant_id="a" * 32,
            group_id="b" * 32,
            category_id=None,
        )

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_gets_job_detail(self, fake_db, authenticate):
        authenticate.return_value = ADMIN
        fake_db.is_available.return_value = True
        fake_db.get_job.return_value = {"job_id": "c" * 32, "status": "done"}

        response = self.client.get(
            f"/api/jobs/{'c' * 32}?tenant_id={'a' * 32}",
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual({"job_id": "c" * 32, "status": "done"}, response.json())
        fake_db.get_job.assert_called_once_with("c" * 32, "a" * 32, None)

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_gets_document_versions(self, fake_db, authenticate):
        authenticate.return_value = ADMIN
        fake_db.is_available.return_value = True
        fake_db.list_document_versions.return_value = [{"document_id": "d" * 64, "version": 2}]

        response = self.client.get(
            f"/api/documents/{'d' * 64}/versions?tenant_id={'a' * 32}",
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual([{"document_id": "d" * 64, "version": 2}], response.json())
        fake_db.list_document_versions.assert_called_once_with("d" * 64, "a" * 32, None)

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_admin_creates_tenant(self, fake_db, authenticate):
        authenticate.return_value = ADMIN
        fake_db.is_available.return_value = True
        fake_db.create_tenant.return_value = {"tenant_id": "a" * 32, "name": "Tenant A"}

        response = self.client.post(
            "/api/tenants",
            json={"name": "Tenant A", "metadata": {"uf": "PR"}},
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(201, response.status_code)
        self.assertEqual({"tenant_id": "a" * 32, "name": "Tenant A"}, response.json())
        fake_db.create_tenant.assert_called_once_with("Tenant A", {"uf": "PR"})

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_admin_grants_and_revokes_user_access(self, fake_db, authenticate):
        authenticate.return_value = ADMIN
        fake_db.is_available.return_value = True
        fake_db.grant_user_access.return_value = {
            "subject": "sub-1",
            "tenant_id": "a" * 32,
            "group_id": None,
            "permission": "editor",
        }
        fake_db.revoke_user_access.return_value = True

        grant = self.client.put(
            "/api/users/sub-1/access",
            json={"tenant_id": "a" * 32, "permission": "editor", "username": "Maria"},
            headers={"Authorization": "Bearer token"},
        )
        revoke = self.client.delete(
            f"/api/users/sub-1/access?tenant_id={'a' * 32}",
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(200, grant.status_code)
        self.assertEqual(200, revoke.status_code)
        self.assertEqual({"deleted": True}, revoke.json())
        fake_db.grant_user_access.assert_called_once_with("sub-1", "a" * 32, None, "editor", "Maria")
        fake_db.revoke_user_access.assert_called_once_with("sub-1", "a" * 32, None)

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_editor_renames_document_with_context_permission(self, fake_db, authenticate):
        authenticate.return_value = READER
        fake_db.is_available.return_value = True
        fake_db.user_has_access.return_value = True
        fake_db.rename_document.return_value = True

        response = self.client.put(
            f"/api/documents/{'d' * 64}/name?tenant_id={'a' * 32}&group_id={'b' * 32}",
            json={"name": "Novo nome.pdf"},
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual({"document_id": "d" * 64, "name": "Novo nome.pdf"}, response.json())
        fake_db.user_has_access.assert_called_once_with("reader-sub", "a" * 32, "b" * 32, "editor")
        fake_db.rename_document.assert_called_once_with("d" * 64, "Novo nome.pdf", "a" * 32, "b" * 32)

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_sets_current_version_and_maps_deprecated_conflict(self, fake_db, authenticate):
        authenticate.return_value = ADMIN
        fake_db.is_available.return_value = True
        fake_db.set_current_version.side_effect = ValueError("Uma versao deprecated nao pode ser definida como padrao")

        response = self.client.put(
            f"/api/documents/{'d' * 64}/versions/2/current?tenant_id={'a' * 32}",
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(409, response.status_code)
        self.assertEqual({"error": "Uma versao deprecated nao pode ser definida como padrao"}, response.json())

    @patch("fastapi_app.authenticator.validate_client")
    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_admin_creates_api_key(self, fake_db, authenticate, validate_client):
        authenticate.return_value = ADMIN
        validate_client.return_value = True
        fake_db.is_available.return_value = True
        fake_db.group_belongs_to_tenant.return_value = True
        fake_db.create_api_key.return_value = "ak_secret"

        response = self.client.post(
            "/api/api-keys",
            json={
                "client_id": "client-app",
                "name": "Client App",
                "tenant_id": "a" * 32,
                "group_id": "b" * 32,
            },
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual({"api_key": "ak_secret"}, response.json())
        fake_db.create_api_key.assert_called_once_with("client-app", "Client App", "a" * 32, "b" * 32)

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_serves_viewer_document_html_with_preview_csp(self, fake_db, authenticate):
        authenticate.return_value = ADMIN
        fake_db.is_available.return_value = True
        fake_db.get_document.return_value = {
            "document_id": "d" * 64,
            "allow_document_page_submission": True,
            "html_content": "<html><body>ok</body></html>",
        }

        response = self.client.get(
            f"/api/viewer/documents/{'d' * 64}/html",
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(200, response.status_code)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("connect-src 'none'", response.headers["content-security-policy"])
        self.assertIn("ok", response.text)

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_creates_viewer_submission(self, fake_db, authenticate):
        authenticate.return_value = Identity("reader-sub", "reader", frozenset(), {"email": "r@example.com"})
        fake_db.is_available.return_value = True
        fake_db.get_document.return_value = {
            "document_id": "d" * 64,
            "tenant_id": "a" * 32,
            "group_id": "b" * 32,
            "allow_document_page_submission": True,
            "fields": [{"name": "nome", "type": "text", "required": True}],
        }
        fake_db.list_user_access.return_value = [{"tenant_id": "a" * 32, "group_id": "b" * 32}]
        fake_db.save_document_submission.return_value = {
            "submission_id": "s" * 32,
            "created_at": "2026-07-17T12:00:00",
        }

        response = self.client.post(
            f"/api/viewer/documents/{'d' * 64}/submissions",
            json={"values": {"nome": "Maria"}},
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(201, response.status_code)
        self.assertEqual("s" * 32, response.json()["submission_id"])
        fake_db.save_document_submission.assert_called_once()

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_updates_document_html_and_saves_completed_job(self, fake_db, authenticate):
        authenticate.return_value = ADMIN
        fake_db.is_available.return_value = True
        fake_db.create_edited_html_version.return_value = {
            "document_id": "d" * 64,
            "version": 3,
            "job_id": "j" * 32,
            "fields": [],
            "tables": [],
            "neural_tables": [],
            "metadata": {},
            "tenant_id": "a" * 32,
            "group_id": None,
            "category_id": None,
        }

        response = self.client.put(
            f"/api/documents/{'d' * 64}/html?tenant_id={'a' * 32}",
            json={"html_content": "<html><body>editado</body></html>"},
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("j" * 32, response.json()["job_id"])
        self.assertEqual("/jobs/" + "j" * 32 + "/html/index.html", response.json()["preview"])
        fake_db.save_job.assert_called_once()

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_updates_document_fields_and_syncs_job_result(self, fake_db, authenticate):
        authenticate.return_value = ADMIN
        fake_db.is_available.return_value = True
        fake_db.update_document_fields.return_value = MagicMock(matched_count=1)
        fake_db.get_job.return_value = {"job_id": "c" * 32, "result": {"fields": [], "tables": []}}

        response = self.client.put(
            f"/api/documents/{'c' * 32}/fields?tenant_id={'a' * 32}",
            json={"fields": [{
                "name": "nome",
                "label": "Nome",
                "type": "text",
                "page": 1,
                "x": 1,
                "y": 2,
                "width": 100,
                "height": 20,
            }]},
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("c" * 32, response.json()["job_id"])
        fake_db.update_document_fields.assert_called_once()
        fake_db.save_job.assert_called_once()

    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_applies_format_norm_and_saves_completed_job(self, fake_db, authenticate):
        authenticate.return_value = ADMIN
        fake_db.is_available.return_value = True
        fake_db.apply_format_norm.return_value = {
            "document_id": "d" * 64,
            "version": 4,
            "job_id": "f" * 32,
            "fields": [],
            "tables": [],
            "neural_tables": [],
            "metadata": {},
            "tenant_id": "a" * 32,
            "group_id": None,
            "category_id": None,
            "format_norm": None,
        }

        response = self.client.put(
            f"/api/documents/{'d' * 64}/format-norm?tenant_id={'a' * 32}",
            json={"format_norm": None},
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("f" * 32, response.json()["job_id"])
        fake_db.save_job.assert_called_once()

    @patch("fastapi_app.convert_html_with_gotenberg")
    @patch("fastapi_app.authenticator.authenticate")
    def test_generates_pdf_from_html(self, authenticate, convert_html):
        authenticate.return_value = ADMIN
        convert_html.return_value = b"%PDF-1.4\nfake"

        response = self.client.post(
            "/api/pdf/html",
            json={"html_content": "<html><body>ok</body></html>", "filename": "saida.pdf"},
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("application/pdf", response.headers["content-type"])
        self.assertEqual(b"%PDF-1.4\nfake", response.content)
        convert_html.assert_called_once_with("<html><body>ok</body></html>", "saida.pdf")

    @patch("fastapi_app.EXECUTOR.submit")
    @patch("fastapi_app.validate_public_url")
    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_creates_background_job(self, fake_db, authenticate, validate_url, submit):
        authenticate.return_value = ADMIN
        validate_url.side_effect = lambda value: value
        fake_db.is_available.return_value = True
        fake_db.group_belongs_to_tenant.return_value = True
        fake_db.category_belongs_to_group.return_value = True

        response = self.client.post(
            "/api/jobs",
            json={
                "pdf_url": "https://example.com/a.pdf",
                "callback_url": "https://example.com/callback",
                "reference": {"id": 1},
                "tenant_id": "a" * 32,
            },
            headers={"Authorization": "Bearer token", "Host": "api.test"},
        )

        self.assertEqual(202, response.status_code)
        self.assertEqual("queued", response.json()["status"])
        self.assertIn("http://api.test/api/jobs/", response.json()["status_url"])
        fake_db.save_job.assert_called_once()
        submit.assert_called_once()

    @patch("fastapi_app.uuid.uuid4")
    @patch("fastapi_app.convert_pdf_bytes")
    @patch("fastapi_app.authenticator.authenticate")
    @patch("fastapi_app.db")
    def test_converts_pdf_synchronously(self, fake_db, authenticate, convert_pdf, uuid4):
        class Conversion:
            html_content = "<html><body>pdf</body></html>"
            fields = []
            tables = []
            pages = []
            neural_tables = []

        authenticate.return_value = ADMIN
        uuid4.return_value.hex = "e" * 32
        convert_pdf.return_value = Conversion()
        fake_db.is_available.return_value = True
        fake_db.group_belongs_to_tenant.return_value = True
        fake_db.category_belongs_to_group.return_value = True
        fake_db.save_document.return_value = {
            "document_id": "d" * 64,
            "version": 1,
            "job_id": "e" * 32,
            "is_current": True,
        }

        response = self.client.post(
            "/api/convert",
            data={"tenant_id": "a" * 32},
            files={"pdf": ("doc.pdf", b"%PDF-1.4\nfake", "application/pdf")},
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("e" * 32, response.json()["job_id"])
        self.assertEqual("d" * 64, response.json()["document_id"])
        fake_db.save_document.assert_called_once()
        fake_db.save_job.assert_called_once()


if __name__ == "__main__":
    unittest.main()
