import json
import tempfile
import unittest
from pathlib import Path

from reportlab.pdfgen import canvas

from converter import convert
from app import validate_public_url


class ConverterTest(unittest.TestCase):
    def test_rejects_private_pdf_url(self):
        with self.assertRaisesRegex(ValueError, "locais|privada"):
            validate_public_url("http://127.0.0.1/documento.pdf")

    def test_converts_text_image_and_inferred_field(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); pdf = root / "form.pdf"
            c = canvas.Canvas(str(pdf), pagesize=(400, 300))
            c.drawString(30, 250, "Nome completo:")
            c.line(130, 248, 350, 248)
            c.drawString(30, 210, "E-mail:")
            c.line(90, 208, 350, 208)
            c.save()
            output = convert(pdf, root / "out")
            document = (output / "index.html").read_text()
            fields = json.loads((output / "fields.json").read_text())
            self.assertIn("Nome", document)
            self.assertNotIn("data:image", document)
            self.assertGreaterEqual(len(fields), 2)
            self.assertIn("email", {field["type"] for field in fields})


if __name__ == "__main__":
    unittest.main()
