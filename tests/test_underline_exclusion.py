import unittest
from pathlib import Path
from unittest.mock import MagicMock
from converter import convert

class TestUnderlineExclusion(unittest.TestCase):
    def test_convert_filters_neural_fields_on_underlines(self):
        # Mock do field_detector
        mock_detector = MagicMock()
        
        # Coordenadas de uma linha no PDF real '01-Cadastro_participante_externo_banca.pdf'
        # detectada anteriormente: {'x0': 85.05, 'top': 164.25076377952803, 'x1': 524.75, 'bottom': 164.25076377952803}
        
        mock_detector.detect.return_value = [
            # Campo sobre uma linha/sublinhado (deve ser filtrado)
            {"page": 1, "x": 100, "y": 160, "width": 100, "height": 10, "confidence": 0.9, "source": "neural_field"},
            # Campo em área limpa (deve ser mantido)
            {"page": 1, "x": 500, "y": 700, "width": 50, "height": 20, "confidence": 0.9, "source": "neural_field"}
        ]
        
        pdf_path = Path("data/uepg/pdfs/01-Cadastro_participante_externo_banca.pdf")
        if not pdf_path.exists():
            self.skipTest("PDF de teste não encontrado")

        result = convert(pdf_path, field_detector=mock_detector)
        
        neural_fields = [f for f in result.fields if f["source"] == "neural_field"]
        
        # Verificamos se apenas um campo neural restou (o de 500,700)
        self.assertEqual(len(neural_fields), 1, f"Campos neurais encontrados: {neural_fields}")
        self.assertEqual(neural_fields[0]["x"], 500)

if __name__ == "__main__":
    unittest.main()
