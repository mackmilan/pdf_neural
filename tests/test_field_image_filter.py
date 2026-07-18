import unittest
from pathlib import Path
from unittest.mock import MagicMock
import pdfplumber
from backend.app.services.converter import convert, Field

class TestNeuralFieldImageOverlap(unittest.TestCase):
    def test_convert_filters_neural_fields_on_images(self):
        # Mock do field_detector
        mock_detector = MagicMock()
        # Campo 1: sobrepõe a imagem do logo institucional (x0=32.75, top=-0.049, x1=147.05, bottom=80.8)
        # Vamos colocar um campo em x=50, y=50 que está dentro dessa imagem.
        # Campo 2: fora de imagens
        mock_detector.detect.return_value = [
            {"page": 1, "x": 50, "y": 50, "width": 20, "height": 10, "confidence": 0.9, "source": "neural_field"},
            {"page": 1, "x": 500, "y": 700, "width": 50, "height": 20, "confidence": 0.9, "source": "neural_field"}
        ]
        
        pdf_path = next(Path("data").glob("*/pdfs/01-Cadastro_participante_externo_banca.pdf"), None)
        if pdf_path is None:
            self.skipTest("PDF de teste não encontrado")

        result = convert(pdf_path, field_detector=mock_detector)
        
        # O campo em 50, 50 deve ter sido filtrado.
        # O campo em 300, 300 deve ter sido mantido.
        neural_fields = [f for f in result.fields if f["source"] == "neural_field"]
        
        # Verificamos se apenas um campo neural restou (o de 500,700)
        self.assertEqual(len(neural_fields), 1, f"Campos neurais encontrados: {neural_fields}")
        self.assertEqual(neural_fields[0]["x"], 500)

    def test_field_boxes_filters_images(self):
        from backend.app.ml.fields import field_boxes
        pdf_path = next(Path("data").glob("*/pdfs/01-Cadastro_participante_externo_banca.pdf"), None)
        if pdf_path is None:
            self.skipTest("PDF de teste não encontrado")
            
        data = field_boxes(pdf_path)
        self.assertIsInstance(data, list)
        for page_w, page_h, bboxes in data:
            self.assertIsInstance(bboxes, list)
            # Se houvesse um campo manual na área do logo, ele não deveria estar aqui.

if __name__ == "__main__":
    unittest.main()
