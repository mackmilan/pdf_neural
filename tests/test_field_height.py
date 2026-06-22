import unittest
from pathlib import Path
from unittest.mock import MagicMock
from converter import convert

class TestNeuralFieldHeight(unittest.TestCase):
    def test_neural_fields_have_fixed_height(self):
        # Mock do field_detector
        mock_detector = MagicMock()
        
        # Simulamos detecções com alturas variadas em coordenadas que NÃO sobreponham texto/imagens
        mock_detector.detect.return_value = [
            {"page": 1, "x": 500, "y": 700, "width": 100, "height": 10, "confidence": 0.9, "source": "neural_field"},
            {"page": 1, "x": 500, "y": 750, "width": 100, "height": 30, "confidence": 0.9, "source": "neural_field"}
        ]
        
        pdf_path = Path("data/uepg/pdfs/01-Cadastro_participante_externo_banca.pdf")
        if not pdf_path.exists():
            self.skipTest("PDF de teste não encontrado")

        result = convert(pdf_path, field_detector=mock_detector)
        
        neural_fields = [f for f in result.fields if f["source"] == "neural_field"]
        
        self.assertEqual(len(neural_fields), 2)
        
        for field in neural_fields:
            # A altura deve ter sido forçada para 20.0
            self.assertEqual(field["height"], 20.0, f"Campo em y={field['y']} tem altura {field['height']}, esperava 20.0")
            
        # Verificar se a base foi mantida
        # Original 1: y=700, h=10 -> base=710. Novo: y=690, h=20 -> base=710
        self.assertEqual(neural_fields[0]["y"], 690.0)
        # Original 2: y=750, h=30 -> base=780. Novo: y=760, h=20 -> base=780
        self.assertEqual(neural_fields[1]["y"], 760.0)

if __name__ == "__main__":
    unittest.main()
