import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import app
from auth import AuthenticationError, KeycloakAuthenticator
from converter import ConversionResult
from database import Database


class FakeDatabase:
    def __init__(self):
        self.jobs = {}
        self.documents = {}

    def is_available(self):
        return True

    def save_job(self, job_id, data):
        self.jobs[job_id] = data

    def save_document(self, job_id, **data):
        self.documents[job_id] = data


class AsyncApiTest(unittest.TestCase):
    def test_renders_neural_table_overlay_in_html_page(self):
        with tempfile.TemporaryDirectory() as temp:
            result = Path(temp)
            (result / "index.html").write_text(
                '<html><head></head><body><section class="pdf-page" data-page="1" '
                'style="width:600px;height:800px">conteudo</section></body></html>',
                encoding="utf-8",
            )
            app.render_neural_tables(result, [{
                "id": "page-1-neural-table-1", "page": 1,
                "x": 10, "y": 20, "width": 300, "height": 120,
                "confidence": .875, "source": "neural", "row_count": 2, "column_count": 1,
                "lines": [{"orientation": "h", "x": 10, "y": 20, "width": 300,
                           "height": 0, "line_width": .75, "color": "#264f73"}],
            }])

            document = (result / "index.html").read_text(encoding="utf-8")
            self.assertIn('class="neural-table-structure"', document)
            self.assertIn('class="neural-table-line"', document)
            self.assertIn('left:10.00px;top:20.00px;width:300.00px;height:0.75px;background:#264f73', document)
            self.assertIn("Tabela neural 88%, 2 linhas, 1 colunas", document)
            self.assertNotIn("neural-table-region", document)

    def test_openapi_documents_every_api_operation(self):
        spec = json.loads((app.STATIC / "openapi.json").read_text())
        self.assertEqual("3.1.0", spec["openapi"])
        operations = {(method, path) for path, methods in spec["paths"].items() for method in methods}
        self.assertTrue(
            {("post", "/api/convert"), ("post", "/api/jobs"), ("get", "/api/jobs/{job_id}"),
             ("put", "/api/documents/{job_id}/fields"), ("delete", "/api/documents/{document_id}"),
             ("get", "/api/documents/{document_id}/versions"),
             ("get", "/api/documents/{document_id}/versions/{version}"),
             ("put", "/api/documents/{document_id}/versions/{version}/current"),
             ("put", "/api/documents/{document_id}/versions/{version}/deprecated"),
             ("delete", "/api/documents/{document_id}/versions/{version}/deprecated")} <= operations
        )
        self.assertTrue({("get", "/api/tenants"), ("post", "/api/tenants"),
                         ("get", "/api/tenants/{tenant_id}/groups"),
                         ("post", "/api/tenants/{tenant_id}/groups")} <= operations)
        self.assertTrue({("get", "/api/tenants/{tenant_id}/groups/{group_id}/categories"),
                         ("post", "/api/tenants/{tenant_id}/groups/{group_id}/categories"),
                         ("put", "/api/documents/{document_id}/category"),
                         ("put", "/api/documents/{document_id}/name")} <= operations)
        self.assertIn("extractionFinished", spec["paths"]["/api/jobs"]["post"]["callbacks"])
        self.assertEqual(spec["security"], [{"bearerAuth": []}])
        self.assertIn("bearerAuth", spec["components"]["securitySchemes"])
        self.assertIn("/api/users/{subject}/access", spec["paths"])

    def test_rejects_missing_bearer_token(self):
        authenticator = KeycloakAuthenticator()
        authenticator.enabled = True
        with self.assertRaisesRegex(AuthenticationError, "Token Bearer ausente"):
            authenticator.authenticate(None)

    def test_login_page_uses_oidc_pkce_and_hides_application(self):
        page = (app.STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="login-screen"', page)
        self.assertIn('id="app-shell" hidden', page)
        self.assertIn('id="result-document-name"', page)
        self.assertIn('id="result-category-select"', page)
        self.assertIn('id="save-document-name"', page)
        self.assertIn("code_challenge_method:'S256'", page)
        self.assertIn("grant_type:'authorization_code'", page)
        self.assertIn("grant_type:'refresh_token'", page)
        self.assertNotIn('id="access-token"', page)

    def test_user_access_accepts_tenant_wide_or_exact_group(self):
        database = Database.__new__(Database)
        database.jobs = MagicMock()
        database.user_access = MagicMock()
        database.user_access.find_one.side_effect = [{"permission": "editor"}, None]

        self.assertTrue(database.user_has_access("subject-1", "a" * 32, "b" * 32, "editor"))
        self.assertFalse(database.user_has_access("subject-1", "a" * 32, None, "editor"))
        first_query = database.user_access.find_one.call_args_list[0].args[0]
        self.assertEqual(first_query["$or"], [{"group_id": None}, {"group_id": "b" * 32}])
        self.assertEqual(first_query["permission"], "editor")

    def test_validates_manually_edited_fields(self):
        fields = app.validate_fields_payload([{
            "name": "data_dia", "label": "Data - dia", "type": "date",
            "page": 1, "x": 10, "y": 20, "width": 30, "height": 20,
            "source": "manual",
        }])
        self.assertEqual(fields[0]["href"], "index.html#data_dia")
        self.assertEqual(fields[0]["source"], "manual")

        with self.assertRaises(ValueError):
            app.validate_fields_payload([
                {**fields[0], "name": "duplicado"},
                {**fields[0], "name": "duplicado"},
            ])

    def test_search_context_requires_tenant_and_accepts_optional_group(self):
        with self.assertRaisesRegex(ValueError, "tenant_id invalido"):
            app.validate_search_context({})

        tenant_id, group_id = app.validate_search_context({"tenant_id": ["a" * 32]})
        self.assertEqual(tenant_id, "a" * 32)
        self.assertIsNone(group_id)

        tenant_id, group_id = app.validate_search_context({
            "tenant_id": ["a" * 32], "group_id": ["b" * 32],
        })
        self.assertEqual(group_id, "b" * 32)

        self.assertIsNone(app.validate_category_query({}))
        self.assertEqual(app.validate_category_query({"category_id": ["c" * 32]}), "c" * 32)
        with self.assertRaisesRegex(ValueError, "category_id invalido"):
            app.validate_category_query({"category_id": ["invalida"]})

    def test_openapi_searches_require_tenant_and_make_group_optional(self):
        spec = json.loads((app.STATIC / "openapi.json").read_text())
        parameters = spec["components"]["parameters"]
        self.assertTrue(parameters["TenantQuery"]["required"])
        self.assertFalse(parameters["GroupQuery"]["required"])
        for path in (
            "/api/documents", "/api/documents/{document_id}",
            "/api/documents/{document_id}/versions",
            "/api/documents/{document_id}/versions/{version}",
            "/api/jobs", "/api/jobs/{job_id}",
        ):
            refs = {item.get("$ref") for item in spec["paths"][path]["get"].get("parameters", [])}
            self.assertIn("#/components/parameters/TenantQuery", refs)
            self.assertIn("#/components/parameters/GroupQuery", refs)

    def test_delete_document_removes_related_records(self):
        database = Database.__new__(Database)
        database.documents = MagicMock()
        database.versions = MagicMock()
        database.jobs = MagicMock()
        database.db = MagicMock()
        database.documents.find_one.return_value = None
        database.documents.delete_one.return_value.deleted_count = 1

        self.assertTrue(database.delete_document("a" * 32))

        database.documents.delete_one.assert_called_once_with({"job_id": "a" * 32})
        database.jobs.delete_one.assert_called_once_with({"job_id": "a" * 32})
        database.db.get_collection.return_value.delete_many.assert_called_once_with({"job_id": "a" * 32})

    def test_repeated_document_creates_new_current_version(self):
        database = Database.__new__(Database)
        database.documents = MagicMock()
        database.versions = MagicMock()
        database.jobs = MagicMock()
        database.db = MagicMock()
        database.documents.find_one_and_update.return_value = {"current_version": 2}

        identity = database.save_document(
            "b" * 32, "<html></html>", [], [], metadata={"filename": "form.pdf"},
            content_hash="c" * 64,
        )

        self.assertEqual(identity["document_id"], "c" * 64)
        self.assertEqual(identity["version"], 2)
        database.versions.update_many.assert_called_once_with(
            {"document_id": "c" * 64, "is_current": True}, {"$set": {"is_current": False}}
        )
        inserted = database.versions.insert_one.call_args.args[0]
        self.assertTrue(inserted["is_current"])
        self.assertEqual(inserted["version"], 2)

    def test_tenant_group_scopes_document_identity(self):
        database = Database.__new__(Database)
        database.documents = MagicMock()
        database.versions = MagicMock()
        database.jobs = MagicMock()
        database.documents.find_one_and_update.return_value = {"current_version": 1}

        identity = database.save_document(
            "b" * 32, "<html></html>", [], [], content_hash="c" * 64,
            tenant_id="d" * 32, group_id="e" * 32,
        )

        self.assertNotEqual(identity["document_id"], "c" * 64)
        self.assertEqual(len(identity["document_id"]), 64)
        inserted = database.versions.insert_one.call_args.args[0]
        self.assertEqual(inserted["tenant_id"], "d" * 32)
        self.assertEqual(inserted["group_id"], "e" * 32)

    def test_lists_documents_scoped_by_tenant_and_group(self):
        database = Database.__new__(Database)
        database.documents = MagicMock()
        database.jobs = MagicMock()
        database.documents.count_documents.return_value = 0
        database.documents.find.return_value.sort.return_value.limit.return_value = []

        database.list_documents(tenant_id="d" * 32, group_id="e" * 32)

        database.documents.find.assert_called_once_with(
            {"tenant_id": "d" * 32, "group_id": "e" * 32}, {"html_content": 0}
        )

    def test_filters_documents_by_category(self):
        database = Database.__new__(Database)
        database.documents = MagicMock()
        database.jobs = MagicMock()
        database.documents.count_documents.return_value = 0
        database.documents.find.return_value.sort.return_value.limit.return_value = []

        database.list_documents(tenant_id="d" * 32, category_id="f" * 32)

        database.documents.find.assert_called_once_with(
            {"tenant_id": "d" * 32, "category_id": "f" * 32}, {"html_content": 0}
        )

    def test_paginates_and_filters_documents_by_name(self):
        database = Database.__new__(Database)
        database.documents = MagicMock()
        database.jobs = MagicMock()
        database.documents.count_documents.return_value = 23
        cursor = database.documents.find.return_value.sort.return_value
        cursor.skip.return_value.limit.return_value = [{"document_id": "c" * 64}]

        result = database.list_documents(
            page=2, page_size=10, tenant_id="d" * 32, name="Ata (final)"
        )

        expected_query = {
            "tenant_id": "d" * 32,
            "metadata.filename": {"$regex": "Ata\\ \\(final\\)", "$options": "i"},
        }
        database.documents.count_documents.assert_called_once_with(expected_query)
        database.documents.find.assert_called_once_with(expected_query, {"html_content": 0})
        cursor.skip.assert_called_once_with(10)
        self.assertEqual(result["total_pages"], 3)
        self.assertEqual(len(result["items"]), 1)

    def test_updates_category_across_document_versions_and_jobs(self):
        database = Database.__new__(Database)
        database.jobs = MagicMock()
        database.documents = MagicMock()
        database.versions = MagicMock()
        database.categories = MagicMock()
        database.categories.find_one.return_value = {"category_id": "f" * 32}
        database.documents.find_one.return_value = {"document_id": "c" * 64}
        database.versions.find.return_value = [{"job_id": "b" * 32}]

        updated = database.update_document_category(
            "c" * 64, "f" * 32, "d" * 32, "e" * 32,
        )

        self.assertTrue(updated)
        database.categories.find_one.assert_called_once_with({
            "tenant_id": "d" * 32, "group_id": "e" * 32, "category_id": "f" * 32,
        })
        database.versions.update_many.assert_called_once()
        database.jobs.update_many.assert_called_once_with(
            {"job_id": {"$in": ["b" * 32]}, "tenant_id": "d" * 32},
            {"$set": {"category_id": "f" * 32}},
        )

    def test_lists_categories_scoped_by_tenant_and_group(self):
        database = Database.__new__(Database)
        database.jobs = MagicMock()
        database.categories = MagicMock()
        database.categories.find.return_value.sort.return_value = []

        database.list_categories("d" * 32, "e" * 32)

        database.categories.find.assert_called_once_with(
            {"tenant_id": "d" * 32, "group_id": "e" * 32}
        )

    def test_renames_document_across_versions_and_jobs(self):
        database = Database.__new__(Database)
        database.documents = MagicMock()
        database.versions = MagicMock()
        database.jobs = MagicMock()
        database.documents.find_one.return_value = {"document_id": "c" * 64}
        database.versions.find.return_value = [{"job_id": "b" * 32}]

        renamed = database.rename_document(
            "c" * 64, "Novo nome.pdf", "d" * 32, "e" * 32,
        )

        self.assertTrue(renamed)
        database.documents.update_one.assert_called_once()
        database.versions.update_many.assert_called_once()
        database.jobs.update_many.assert_called_once()
        self.assertEqual(
            database.documents.update_one.call_args.args[1]["$set"]["metadata.filename"],
            "Novo nome.pdf",
        )

    def test_fetches_current_document_and_explicit_version(self):
        database = Database.__new__(Database)
        database.documents = MagicMock()
        database.versions = MagicMock()
        database.jobs = MagicMock()
        current = {"document_id": "c" * 64, "version": 3, "is_current": True}
        explicit = {"document_id": "c" * 64, "version": 1, "is_current": False}
        database.versions.find_one.side_effect = [None, current, explicit]

        self.assertEqual(database.get_document("c" * 64), current)
        self.assertEqual(database.get_document("c" * 64, 1), explicit)
        self.assertEqual(
            database.versions.find_one.call_args_list[-1].args[0],
            {"document_id": "c" * 64, "version": 1},
        )

    def test_selects_document_default_version(self):
        database = Database.__new__(Database)
        database.documents = MagicMock()
        database.versions = MagicMock()
        database.jobs = MagicMock()
        database.versions.find_one.return_value = {
            "document_id": "c" * 64, "version": 1, "job_id": "b" * 32,
            "fields": [{"name": "data"}], "tables": [], "metadata": {"filename": "form.pdf"},
        }

        selected = database.set_current_version("c" * 64, 1)

        self.assertTrue(selected["is_current"])
        self.assertEqual(selected["job_id"], "b" * 32)
        database.versions.update_many.assert_called_once_with(
            {"document_id": "c" * 64}, {"$set": {"is_current": False}}
        )
        canonical_update = database.documents.update_one.call_args.args[1]["$set"]
        self.assertEqual(canonical_update["current_version"], 1)
        self.assertEqual(canonical_update["fields"], [{"name": "data"}])

    def test_marks_and_restores_non_current_version_as_deprecated(self):
        database = Database.__new__(Database)
        database.documents = MagicMock()
        database.versions = MagicMock()
        database.jobs = MagicMock()
        database.versions.find_one.return_value = {
            "document_id": "c" * 64, "version": 1, "job_id": "b" * 32,
            "is_current": False,
        }

        marked = database.set_version_deprecated("c" * 64, 1)
        restored = database.set_version_deprecated("c" * 64, 1, False)

        self.assertTrue(marked["deprecated"])
        self.assertFalse(restored["deprecated"])
        self.assertEqual(database.versions.update_one.call_args_list[0].args[1]["$set"]["deprecated"], True)
        self.assertEqual(database.versions.update_one.call_args_list[1].args[1]["$set"]["deprecated"], False)

    def test_rejects_deprecating_current_version_or_selecting_deprecated_version(self):
        database = Database.__new__(Database)
        database.documents = MagicMock()
        database.versions = MagicMock()
        database.jobs = MagicMock()
        database.versions.find_one.return_value = {
            "document_id": "c" * 64, "version": 1, "job_id": "b" * 32,
            "is_current": True,
        }
        with self.assertRaisesRegex(ValueError, "padrao"):
            database.set_version_deprecated("c" * 64, 1)

        database.versions.find_one.return_value = {
            "document_id": "c" * 64, "version": 1, "job_id": "b" * 32,
            "deprecated": True,
        }
        with self.assertRaisesRegex(ValueError, "deprecated"):
            database.set_current_version("c" * 64, 1)

    def test_completed_job_is_persisted_and_sent_to_callback(self):
        with tempfile.TemporaryDirectory() as temp:
            jobs = Path(temp)
            job = "a" * 32

            result = ConversionResult(
                "<html></html>", [{"name": "cpf"}], [{"id": "page-1-table-1"}], [],
                [{"id": "page-1-neural-table-1"}],
            )

            callbacks = []
            fake_db = FakeDatabase()
            with (
                patch.object(app, "db", fake_db),
                patch.object(app, "download_pdf", return_value=("form.pdf", b"%PDF fake")),
                patch.object(app, "convert_pdf_bytes", return_value=result),
                patch.object(app, "deliver_callback", side_effect=lambda _url, payload: callbacks.append(payload)),
                patch.object(app, "get_detectors", return_value=(None, None)),
                patch.object(app, "NEURAL_REQUIRED", False),
            ):
                app.run_api_job(job, "https://files.example/form.pdf", "https://api.example/callback", "doc-7", "https://pdf.example")

            status = fake_db.jobs[job]
            self.assertEqual("completed", status["status"])
            self.assertEqual("delivered", status["callback_status"])
            self.assertEqual("doc-7", callbacks[0]["reference"])
            self.assertEqual("cpf", callbacks[0]["result"]["fields"][0]["name"])
            self.assertEqual("page-1-table-1", callbacks[0]["result"]["tables"][0]["id"])
            self.assertEqual("page-1-neural-table-1", callbacks[0]["result"]["neural_tables"][0]["id"])
            self.assertEqual(f"https://pdf.example/jobs/{job}/html/index.html", callbacks[0]["result"]["preview_url"])
            self.assertFalse(any(jobs.iterdir()))

    def test_failed_extraction_is_also_sent_to_callback(self):
        with tempfile.TemporaryDirectory() as temp:
            jobs = Path(temp)
            job = "b" * 32
            callbacks = []
            fake_db = FakeDatabase()
            with (
                patch.object(app, "db", fake_db),
                patch.object(app, "download_pdf", side_effect=ValueError("download invalido")),
                patch.object(app, "deliver_callback", side_effect=lambda _url, payload: callbacks.append(payload)),
            ):
                app.run_api_job(job, "https://files.example/form.pdf", "https://api.example/callback", None, "https://pdf.example")

            self.assertEqual("failed", callbacks[0]["status"])
            self.assertIn("download invalido", callbacks[0]["error"])


if __name__ == "__main__":
    unittest.main()
