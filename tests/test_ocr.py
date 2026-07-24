import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.app.ml.ocr import (
    OcrExtractor,
    OcrUnavailable,
    OcrWord,
    load_engine,
    merge_ocr_words,
    split_line_into_words,
)
from backend.app.services.converter import convert


class FakeImage:
    """Imagem renderizada de 1000x1000 px, equivalente a 240x240 pt a 300 dpi."""

    width = 1000
    height = 1000


class FakeEngine:
    name = "fake"

    def __init__(self, words):
        self.words = words
        self.calls = []

    def recognize(self, image):
        self.calls.append(image)
        return list(self.words)


def extractor(words, **kwargs):
    return OcrExtractor(FakeEngine(words), **kwargs)


class SplitLineTest(unittest.TestCase):
    def test_divide_linha_proporcionalmente_aos_caracteres(self):
        words = split_line_into_words("Nome do aluno", 0, 10, 130, 30, 0.9)
        self.assertEqual(["Nome", "do", "aluno"], [word.text for word in words])
        self.assertAlmostEqual(0.0, words[0].x0)
        self.assertAlmostEqual(40.0, words[0].x1)
        self.assertAlmostEqual(50.0, words[1].x0)
        self.assertAlmostEqual(130.0, words[2].x1)
        self.assertEqual([0.9, 0.9, 0.9], [word.confidence for word in words])

    def test_linha_em_branco_nao_gera_palavras(self):
        self.assertEqual([], split_line_into_words("   ", 0, 0, 10, 10, 1.0))


class ShouldRunTest(unittest.TestCase):
    def test_auto_roda_em_pagina_sem_texto_e_com_imagem(self):
        page = mock.Mock(images=[{"x0": 0}])
        self.assertTrue(extractor([]).should_run([], page))

    def test_auto_ignora_pagina_com_camada_de_texto(self):
        page = mock.Mock(images=[{"x0": 0}])
        words = [{"text": f"palavra-{index}"} for index in range(10)]
        self.assertFalse(extractor([]).should_run(words, page))

    def test_auto_ignora_pagina_vazia_sem_imagem(self):
        self.assertFalse(extractor([]).should_run([], mock.Mock(images=[])))

    def test_always_roda_mesmo_com_texto(self):
        page = mock.Mock(images=[])
        words = [{"text": "ja tem texto"}] * 10
        self.assertTrue(extractor([], mode="always").should_run(words, page))


class PageWordsTest(unittest.TestCase):
    def run_extractor(self, words, **kwargs):
        instance = extractor(words, **kwargs)
        with mock.patch("backend.app.ml.ocr.render_page_image", return_value=FakeImage()):
            return instance.page_words(Path("documento.pdf"), 1, 240.0, 240.0)

    def test_converte_pixels_para_pontos_da_pagina(self):
        recognized = [OcrWord("Matricula", 100, 200, 500, 260, 0.95)]
        words = self.run_extractor(recognized)
        self.assertEqual(1, len(words))
        word = words[0]
        self.assertAlmostEqual(24.0, word["x0"])
        self.assertAlmostEqual(120.0, word["x1"])
        self.assertAlmostEqual(48.0, word["top"])
        self.assertAlmostEqual(62.4, word["bottom"])
        self.assertEqual("Matricula", word["text"])
        self.assertEqual("ocr", word["source"])
        self.assertEqual(0.95, word["confidence"])
        self.assertGreater(word["size"], 0)

    def test_descarta_reconhecimento_abaixo_da_confianca_minima(self):
        recognized = [
            OcrWord("certo", 0, 0, 100, 40, 0.9),
            OcrWord("ruido", 0, 100, 100, 140, 0.2),
        ]
        words = self.run_extractor(recognized, min_confidence=0.45)
        self.assertEqual(["certo"], [word["text"] for word in words])

    def test_descarta_texto_vazio_e_caixas_degeneradas(self):
        recognized = [
            OcrWord("   ", 0, 0, 100, 40, 0.9),
            OcrWord("zero", 50, 50, 50, 90, 0.9),
            OcrWord("valido", 0, 200, 100, 240, 0.9),
        ]
        words = self.run_extractor(recognized)
        self.assertEqual(["valido"], [word["text"] for word in words])

    def test_ordena_por_linha_e_coluna(self):
        recognized = [
            OcrWord("segunda", 0, 500, 100, 540, 0.9),
            OcrWord("direita", 400, 100, 500, 140, 0.9),
            OcrWord("esquerda", 0, 100, 100, 140, 0.9),
        ]
        words = self.run_extractor(recognized)
        self.assertEqual(["esquerda", "direita", "segunda"], [word["text"] for word in words])


class MergeTest(unittest.TestCase):
    @staticmethod
    def word(text, x0, top, x1, bottom, source="pdf"):
        return {"text": text, "x0": x0, "top": top, "x1": x1, "bottom": bottom, "source": source}

    def test_descarta_palavra_do_ocr_sobre_texto_nativo(self):
        native = [self.word("Nome", 10, 10, 60, 25)]
        recognized = [self.word("Nome", 11, 11, 59, 24, "ocr")]
        self.assertEqual(native, merge_ocr_words(native, recognized))

    def test_mantem_palavra_do_ocr_em_area_livre(self):
        native = [self.word("Nome", 10, 10, 60, 25)]
        recognized = [self.word("Turma", 10, 60, 60, 75, "ocr")]
        merged = merge_ocr_words(native, recognized)
        self.assertEqual(["Nome", "Turma"], [word["text"] for word in merged])

    def test_sem_texto_nativo_devolve_tudo_do_ocr(self):
        recognized = [self.word("Turma", 10, 60, 60, 75, "ocr")]
        self.assertEqual(recognized, merge_ocr_words([], recognized))


class LoadEngineTest(unittest.TestCase):
    def test_motor_desconhecido_falha(self):
        with self.assertRaises(OcrUnavailable):
            load_engine("motor-inexistente")

    def test_sem_motor_instalado_o_erro_explica_a_instalacao(self):
        unavailable = mock.Mock(side_effect=ImportError("modulo ausente"))
        unavailable.name = "tesseract"
        with mock.patch.dict("backend.app.ml.ocr.ENGINES", {"tesseract": unavailable}, clear=True):
            with self.assertRaises(OcrUnavailable) as context:
                load_engine("auto")
        self.assertIn("modulo ausente", str(context.exception))
        self.assertIn("requirements-ocr.txt", str(context.exception))

    def test_usa_o_motor_disponivel(self):
        engine = object()
        factory = mock.Mock(return_value=engine)
        factory.name = "tesseract"
        with mock.patch.dict("backend.app.ml.ocr.ENGINES", {"tesseract": factory}, clear=True):
            self.assertIs(engine, load_engine("tesseract", "por"))
        factory.assert_called_once_with("por")


class ConvertWithOcrTest(unittest.TestCase):
    """Integracao: uma pagina digitalizada passa a ter texto no HTML e no JSON."""

    def convert_scanned_page(self, ocr, native_words=()):
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "digitalizado.pdf"
            pdf.write_bytes(b"%PDF-1.4\n%%EOF")
            page = mock.MagicMock()
            page.width, page.height = 240, 240
            page.extract_words.return_value = list(native_words)
            page.lines, page.rects, page.curves = [], [], []
            page.images = [{"x0": 0, "top": 0, "x1": 240, "bottom": 240, "name": "Im0"}]
            page.find_tables.return_value = []
            pdf_mock = mock.MagicMock()
            pdf_mock.pages = [page]
            with mock.patch("pdfplumber.open") as open_pdf, \
                 mock.patch("backend.app.services.converter.PdfReader"), \
                 mock.patch("backend.app.services.converter.acro_fields", return_value={}), \
                 mock.patch("backend.app.services.converter.extract_images", return_value={}), \
                 mock.patch("backend.app.ml.ocr.render_page_image", return_value=FakeImage()):
                open_pdf.return_value.__enter__.return_value = pdf_mock
                return convert(pdf, ocr=ocr)

    def test_texto_reconhecido_entra_no_html_e_nas_paginas(self):
        recognized = [OcrWord("Requerimento", 100, 100, 600, 160, 0.92)]
        result = self.convert_scanned_page(extractor(recognized))
        self.assertIn("Requerimento", result.html_content)
        self.assertIn('class="pdf-text pdf-text-ocr"', result.html_content)
        self.assertIn('data-source="ocr"', result.html_content)
        page = result.pages[0]
        self.assertEqual("ocr", page["text_source"])
        self.assertEqual(1, page["ocr_words"])
        self.assertEqual("fake", page["ocr_engine"])
        self.assertEqual("Requerimento", page["ocr_text"])

    def test_sem_ocr_a_pagina_continua_marcada_como_pdf(self):
        result = self.convert_scanned_page(None)
        page = result.pages[0]
        self.assertEqual("pdf", page["text_source"])
        self.assertNotIn("ocr_words", page)

    def test_falha_do_motor_nao_interrompe_a_conversao(self):
        broken = extractor([])
        broken.engine.recognize = mock.Mock(side_effect=RuntimeError("motor caiu"))
        result = self.convert_scanned_page(broken)
        self.assertEqual("pdf", result.pages[0]["text_source"])
        self.assertIn("<html", result.html_content)


if __name__ == "__main__":
    unittest.main()
