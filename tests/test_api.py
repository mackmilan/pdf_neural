import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class AsyncApiTest(unittest.TestCase):
    def test_openapi_documents_every_api_operation(self):
        spec = json.loads((app.STATIC / "openapi.json").read_text())
        self.assertEqual("3.1.0", spec["openapi"])
        self.assertEqual(
            {("post", "/api/convert"), ("post", "/api/jobs"), ("get", "/api/jobs/{job_id}")},
            {(method, path) for path, methods in spec["paths"].items() for method in methods},
        )
        self.assertIn("extractionFinished", spec["paths"]["/api/jobs"]["post"]["callbacks"])

    def test_completed_job_is_persisted_and_sent_to_callback(self):
        with tempfile.TemporaryDirectory() as temp:
            jobs = Path(temp)
            job = "a" * 32
            (jobs / job).mkdir()

            def fake_convert(_source, output):
                output.mkdir()
                (output / "index.html").write_text("<html></html>")
                (output / "fields.json").write_text('[{"name": "cpf"}]')
                return output

            callbacks = []
            with (
                patch.object(app, "JOBS", jobs),
                patch.object(app, "download_pdf", return_value=("form.pdf", b"%PDF fake")),
                patch.object(app, "convert", side_effect=fake_convert),
                patch.object(app, "deliver_callback", side_effect=lambda _url, payload: callbacks.append(payload)),
            ):
                app.run_api_job(job, "https://files.example/form.pdf", "https://api.example/callback", "doc-7", "https://pdf.example")

            status = json.loads((jobs / job / "status.json").read_text())
            self.assertEqual("completed", status["status"])
            self.assertEqual("delivered", status["callback_status"])
            self.assertEqual("doc-7", callbacks[0]["reference"])
            self.assertEqual("cpf", callbacks[0]["result"]["fields"][0]["name"])
            self.assertEqual(f"https://pdf.example/jobs/{job}/resultado.zip", callbacks[0]["result"]["download_url"])

    def test_failed_extraction_is_also_sent_to_callback(self):
        with tempfile.TemporaryDirectory() as temp:
            jobs = Path(temp)
            job = "b" * 32
            (jobs / job).mkdir()
            callbacks = []
            with (
                patch.object(app, "JOBS", jobs),
                patch.object(app, "download_pdf", side_effect=ValueError("download invalido")),
                patch.object(app, "deliver_callback", side_effect=lambda _url, payload: callbacks.append(payload)),
            ):
                app.run_api_job(job, "https://files.example/form.pdf", "https://api.example/callback", None, "https://pdf.example")

            self.assertEqual("failed", callbacks[0]["status"])
            self.assertIn("download invalido", callbacks[0]["error"])


if __name__ == "__main__":
    unittest.main()
