import json
import tempfile
import unittest
from pathlib import Path

from reportlab.pdfgen import canvas

from converter import ConversionResult, convert, image_key, textual_empty_parentheses_fields
from app import validate_public_url


class ConverterTest(unittest.TestCase):
    def test_matches_pdf_images_by_xobject_name_not_list_order(self):
        self.assertEqual(image_key("IM59.jpg"), "IM59")
        self.assertEqual(image_key("IM8"), "IM8")

    def test_rejects_private_pdf_url(self):
        with self.assertRaisesRegex(ValueError, "locais|privada"):
            validate_public_url("http://127.0.0.1/documento.pdf")

    def test_returns_all_artifacts_in_memory_without_output_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "memory.pdf"
            c = canvas.Canvas(str(pdf), pagesize=(300, 200))
            c.drawString(20, 170, "Documento em memoria")
            c.save()

            before = set(root.iterdir())
            result = convert(pdf)

            self.assertIsInstance(result, ConversionResult)
            self.assertIn("Documento", result.html_content)
            self.assertEqual(1, len(result.pages))
            self.assertEqual(before, set(root.iterdir()))

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
            self.assertNotIn("form-field", document)
            self.assertNotIn("<input", document)
            self.assertNotIn("<textarea", document)
            self.assertNotIn("<select", document)
            self.assertGreaterEqual(len(fields), 2)
            self.assertIn("email", {field["type"] for field in fields})
            self.assertTrue(
                {"name", "label", "type", "page", "x", "y", "width", "height"}
                <= fields[0].keys()
            )

    def test_preserves_each_page_size_and_aspect_ratio(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); pdf = root / "mixed-sizes.pdf"
            c = canvas.Canvas(str(pdf), pagesize=(400, 300))
            c.drawString(20, 270, "Paisagem")
            c.showPage()
            c.setPageSize((300, 500))
            c.drawString(20, 470, "Retrato")
            c.save()

            output = convert(pdf, root / "out")
            pages = json.loads((output / "pages.json").read_text())
            document = (output / "index.html").read_text()

            self.assertEqual([(p["width"], p["height"]) for p in pages], [(400.0, 300.0), (300.0, 500.0)])
            self.assertEqual([p["orientation"] for p in pages], ["landscape", "portrait"])
            self.assertAlmostEqual(pages[0]["aspect_ratio"], 4 / 3)
            self.assertAlmostEqual(pages[1]["aspect_ratio"], 3 / 5)
            self.assertIn('data-page-width="400" data-page-height="300"', document)
            self.assertIn('data-page-width="300" data-page-height="500"', document)
            self.assertIn("shell.getBoundingClientRect().width", document)
            self.assertIn("page.style.setProperty('--page-scale',String(renderedWidth/width))", document)
            self.assertNotIn("max-width:400px", document)
            self.assertNotIn("Math.min(1,renderedWidth/width)", document)

    def test_detects_table_layout_and_blank_value_cells(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); pdf = root / "table-form.pdf"
            c = canvas.Canvas(str(pdf), pagesize=(400, 300))
            c.rect(30, 70, 340, 150)
            c.line(180, 70, 180, 220)
            c.line(30, 170, 370, 170)
            c.line(30, 120, 370, 120)
            c.drawString(38, 193, "NOME COMPLETO")
            c.drawString(38, 143, "CPF")
            c.drawString(38, 93, "E-MAIL")
            c.save()

            output = convert(pdf, root / "out")
            tables = json.loads((output / "tables.json").read_text())
            fields = json.loads((output / "fields.json").read_text())

            self.assertEqual(len(tables), 1)
            self.assertEqual(tables[0]["row_count"], 3)
            self.assertEqual(tables[0]["column_count"], 2)
            table_fields = [field for field in fields if field["source"] == "table"]
            self.assertEqual({field["label"] for field in table_fields}, {"NOME COMPLETO", "CPF", "E-MAIL"})
            self.assertIn("email", {field["type"] for field in table_fields})

    def test_detects_merged_cells_inner_fields_and_visual_checkboxes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); pdf = root / "merged-table.pdf"
            c = canvas.Canvas(str(pdf), pagesize=(400, 300))
            c.rect(30, 60, 340, 180)
            c.line(30, 140, 370, 140)
            c.line(180, 140, 180, 240)
            c.drawString(38, 210, "NOME")
            c.drawString(38, 110, "TITULACAO:")
            c.drawString(38, 80, "ANO:")
            c.drawString(220, 65, "ATIVO ( )")
            c.save()

            output = convert(pdf, root / "out")
            tables = json.loads((output / "tables.json").read_text())
            fields = json.loads((output / "fields.json").read_text())

            merged = tables[0]["rows"][1]["cells"]
            self.assertEqual(len(merged), 1)
            self.assertEqual(merged[0]["colspan"], 2)
            by_label = {field["label"]: field for field in fields}
            self.assertEqual(by_label["ANO"]["type"], "number")
            self.assertEqual(by_label["ATIVO"]["type"], "checkbox")

    def test_detects_only_exact_empty_parentheses_sequence(self):
        with tempfile.TemporaryDirectory() as temp:
            import pdfplumber

            root = Path(temp); pdf = root / "exact-parentheses.pdf"
            c = canvas.Canvas(str(pdf), pagesize=(400, 300))
            c.drawString(30, 250, "Aceite ( ) Sim")
            c.drawString(30, 220, "Compacto () Nao")
            c.drawString(30, 190, "Marcado (x) Talvez")
            c.save()

            with pdfplumber.open(pdf) as document:
                page = document.pages[0]
                fields = textual_empty_parentheses_fields(page, page.extract_words())

            self.assertEqual(1, len(fields))
            self.assertEqual("checkbox", fields[0]["type"])

            output = convert(pdf, root / "out")
            converted = json.loads((output / "fields.json").read_text())
            checkbox = next(field for field in converted if field["type"] == "checkbox")
            self.assertEqual((checkbox["width"], checkbox["height"]), (14.0, 18.0))


if __name__ == "__main__":
    unittest.main()
