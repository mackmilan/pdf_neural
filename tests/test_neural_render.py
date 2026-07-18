import json
import tempfile
import unittest
from pathlib import Path
from backend.app.services.converter import convert

class MockDetector:
    def detect(self, pdf_path):
        return [
            {
                "id": "mock-table-1",
                "page": 1,
                "confidence": 0.95,
                "row_count": 2,
                "column_count": 2,
                "lines": [
                    {"x": 10, "y": 10, "width": 100, "height": 0, "color": "#FF0000", "line_width": 1},
                    {"x": 10, "y": 10, "width": 0, "height": 100, "color": "#00FF00", "line_width": 1}
                ]
            }
        ]

class NeuralRenderingTest(unittest.TestCase):
    def test_renders_neural_tables_in_html(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Create a dummy PDF file
            pdf = root / "dummy.pdf"
            pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Page /Contents 2 0 R >>\nendobj\n2 0 obj\n<< >>\nstream\nendstream\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF")
            
            # Since we can't easily run with real pdfplumber/torch in this env,
            # we will mock the parts of convert that use them if necessary,
            # but let's see if we can at least test the logic if we mock the detector.
            # Wait, convert() calls pdfplumber.open. I must mock it.
            
            from unittest import mock
            with mock.patch('pdfplumber.open') as mock_pdf_open, \
                 mock.patch('converter.PdfReader') as mock_pdf_reader, \
                 mock.patch('converter.extract_images') as mock_extract_images, \
                 mock.patch('converter.acro_fields') as mock_acro_fields:
                
                # Setup mock page
                mock_page = mock.MagicMock()
                mock_page.width = 400
                mock_page.height = 300
                mock_page.extract_words.return_value = []
                mock_page.lines = []
                mock_page.rects = []
                mock_page.curves = []
                mock_page.images = []
                
                mock_pdf = mock.MagicMock()
                mock_pdf.pages = [mock_page]
                mock_pdf_open.return_value.__enter__.return_value = mock_pdf
                
                mock_acro_fields.return_value = {}
                mock_extract_images.return_value = {}
                
                output_dir = root / "out"
                detector = MockDetector()
                
                convert(pdf, output_dir, table_detector=detector)
                
                index_html = (output_dir / "index.html").read_text()
                neural_json = (output_dir / "neural-tables.json").read_text()
                
                # Check if neural table structure is in HTML
                self.assertIn('class="neural-table-structure"', index_html)
                self.assertIn('data-neural-table="mock-table-1"', index_html)
                self.assertIn('background:#FF0000', index_html)
                self.assertIn('background:#00FF00', index_html)
                
                # Check if neural-tables.json was created
                tables = json.loads(neural_json)
                self.assertEqual(len(tables), 1)
                self.assertEqual(tables[0]["id"], "mock-table-1")

if __name__ == "__main__":
    unittest.main()
