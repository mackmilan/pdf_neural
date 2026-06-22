import unittest
from pathlib import Path
from unittest.mock import MagicMock
import pdfplumber
from converter import convert, Field

class TestNeuralFieldExclusion(unittest.TestCase):
    def test_convert_filters_neural_fields_on_text_and_headers(self):
        # Mock do field_detector
        mock_detector = MagicMock()
        # No PDF '01-Cadastro_participante_externo_banca.pdf':
        # Texto 'CADASTRO DE PARTICIPANTE EXTERNO' está no topo.
        # Vamos simular um campo neural sobre esse texto.
        
        # Coordenadas aproximadas do texto no PDF real (página 1):
        # "CADASTRO" x0=181, top=86, x1=237, bottom=95
        
        mock_detector.detect.return_value = [
            # Campo sobre texto (deve ser filtrado)
            {"page": 1, "x": 190, "y": 88, "width": 40, "height": 10, "confidence": 0.9, "source": "neural_field"},
            # Campo em área limpa (deve ser mantido)
            # x=500, y=700 deve estar no canto inferior direito
            {"page": 1, "x": 500, "y": 700, "width": 50, "height": 20, "confidence": 0.9, "source": "neural_field"}
        ]
        
        pdf_path = Path("data/uepg/pdfs/01-Cadastro_participante_externo_banca.pdf")
        if not pdf_path.exists():
            self.skipTest("PDF de teste não encontrado")

        result = convert(pdf_path, field_detector=mock_detector)
        
        neural_fields = [f for f in result.fields if f["source"] == "neural_field"]
        
        # Verificamos se apenas um campo neural restou (o de 300,300)
        # Atualmente, o teste falha porque ainda não implementamos a filtragem de texto.
        self.assertEqual(len(neural_fields), 1, f"Campos neurais encontrados: {neural_fields}")
        self.assertEqual(neural_fields[0]["x"], 500)

if __name__ == "__main__":
    unittest.main()
