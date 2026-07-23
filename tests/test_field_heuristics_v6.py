"""Regressoes das heuristicas adicionadas no retreino v6.

Cobrem os padroes reportados nos formularios da UEPG: emails/URLs impressos,
rotulos terminados em ':', linhas pontilhadas, tabelas estaticas e a
sobreposicao de campos neurais.
"""
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import pdfplumber

from backend.app.services.converter import (
    convert,
    hyperlink_text_bboxes,
    inferred_fields,
    is_url_text,
    table_layouts,
    textual_dotted_fields,
    textual_label_colon_fields,
)


def find_pdf(name: str) -> Path | None:
    return next(Path("data").glob(f"*/pdfs/{name}"), None)


class TestHyperlinkExclusion(unittest.TestCase):
    def test_url_pattern(self):
        self.assertTrue(is_url_text("https://bicenficha.apps.uepg.br/login"))
        self.assertTrue(is_url_text("www.exemplo.gov.br/form"))
        self.assertFalse(is_url_text("Titulo:"))
        self.assertFalse(is_url_text("R$ 10,00"))

    def test_ficha_catalografica_has_hyperlink_zones(self):
        pdf_path = find_pdf("08-FICHA-CATALOGRAFICA.pdf")
        if pdf_path is None:
            self.skipTest("PDF de teste não encontrado")
        with pdfplumber.open(pdf_path) as pdf:
            words = pdf.pages[0].extract_words()
            bboxes = hyperlink_text_bboxes(words)
        # URL do sistema e email de contato
        self.assertGreaterEqual(len(bboxes), 2)

    def test_no_inferred_field_over_hyperlinks(self):
        pdf_path = find_pdf("08-FICHA-CATALOGRAFICA.pdf")
        if pdf_path is None:
            self.skipTest("PDF de teste não encontrado")
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[0]
            words = page.extract_words()
            links = hyperlink_text_bboxes(words)
            fields = inferred_fields(page, 1, words, [], [])
        for field in fields:
            for (lx0, ly0, lx1, ly1) in links:
                overlap = not (
                    field.x + field.width < lx0 or lx1 < field.x
                    or field.y + field.height < ly0 or ly1 < field.y
                )
                self.assertFalse(overlap, f"Campo {field.label!r} sobre hyperlink")


class TestLabelColonFields(unittest.TestCase):
    def test_lista_declaracao_labels(self):
        pdf_path = find_pdf("05-LISTA-DECLARACAO-DE-ACOMPANHAMENTO-COMO-OUVINTE-DE-BANCA-DE-DEFESA-DE-MESTRADO.pdf")
        if pdf_path is None:
            self.skipTest("PDF de teste não encontrado")
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[0]
            words = page.extract_words()
            fields = textual_label_colon_fields(page, words)
        labels = {field["label"] for field in fields}
        for expected in ("Mestrando", "Data", "Horário", "Local", "Título do trabalho"):
            self.assertIn(expected, labels)

    def test_colon_fields_do_not_overlap_each_other(self):
        pdf_path = find_pdf("05-LISTA-DECLARACAO-DE-ACOMPANHAMENTO-COMO-OUVINTE-DE-BANCA-DE-DEFESA-DE-MESTRADO.pdf")
        if pdf_path is None:
            self.skipTest("PDF de teste não encontrado")
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[0]
            words = page.extract_words()
            layouts, table_fields = table_layouts(page, 1, words)
            table_bboxes = [
                (t["x"], t["y"], t["x"] + t["width"], t["y"] + t["height"]) for t in layouts
            ]
            fields = table_fields + inferred_fields(page, 1, words, list(table_fields), table_bboxes)
        for i in range(len(fields)):
            for j in range(i + 1, len(fields)):
                f, g = fields[i], fields[j]
                overlap = not (
                    f.x + f.width <= g.x or g.x + g.width <= f.x
                    or f.y + f.height <= g.y or g.y + g.height <= f.y
                )
                self.assertFalse(overlap, f"{f.label!r} sobrepoe {g.label!r}")


class TestDottedFields(unittest.TestCase):
    def test_ata_dotted_leaders_become_fields(self):
        pdf_path = find_pdf("04-Modelo-de-ata-de-Defesa.pdf")
        if pdf_path is None:
            self.skipTest("PDF de teste não encontrado")
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[0]
            words = page.extract_words()
            fields = textual_dotted_fields(page, words)
        # A ata tem dezenas de trechos "......." a preencher
        self.assertGreaterEqual(len(fields), 10)

    def test_short_ellipsis_is_ignored(self):
        pdf_path = find_pdf("04-Modelo-de-ata-de-Defesa.pdf")
        if pdf_path is None:
            self.skipTest("PDF de teste não encontrado")
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[0]
            words = page.extract_words()
            fields = textual_dotted_fields(page, words)
        for field in fields:
            x0, _, x1, _ = field["bbox"]
            self.assertGreaterEqual(x1 - x0, 12)


class TestStaticTableExclusion(unittest.TestCase):
    def test_ficha_price_table_has_no_fields(self):
        """A tabela de taxas (R$ 10,00 / R$ 30,00) e conteudo estatico."""
        pdf_path = find_pdf("08-FICHA-CATALOGRAFICA.pdf")
        if pdf_path is None:
            self.skipTest("PDF de teste não encontrado")
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[0]
            words = page.extract_words()
            fields = inferred_fields(page, 1, words, [], [])
        printed = [
            (float(w["x0"]), float(w["top"]), float(w["x1"]), float(w["bottom"]))
            for w in words
            if any(c.isalnum() for c in str(w.get("text", "")))
        ]
        for field in fields:
            if field.type in {"date", "time"}:
                continue
            for (tx0, ty0, tx1, ty1) in printed:
                overlap = not (
                    field.x + field.width < tx0 or tx1 < field.x
                    or field.y + field.height < ty0 or ty1 < field.y
                )
                self.assertFalse(overlap, f"Campo {field.label!r} sobre texto impresso")


class TestNeuralOverlapAndTables(unittest.TestCase):
    def test_neural_fields_never_overlap_each_other(self):
        """A normalizacao de altura deve ocorrer antes da checagem de overlap."""
        pdf_path = find_pdf("01-Cadastro_participante_externo_banca.pdf")
        if pdf_path is None:
            self.skipTest("PDF de teste não encontrado")
        mock_detector = MagicMock()
        # Duas caixas curtas e proximas: apos normalizar para 20pt de altura a
        # segunda invadiria a primeira e deve ser descartada.
        mock_detector.detect.return_value = [
            {"page": 1, "x": 400, "y": 690, "width": 80, "height": 5, "confidence": 0.9, "source": "neural_field"},
            {"page": 1, "x": 420, "y": 705, "width": 80, "height": 5, "confidence": 0.8, "source": "neural_field"},
        ]
        result = convert(pdf_path, field_detector=mock_detector)
        fields = result.fields
        neural = [f for f in fields if f["source"] == "neural_field"]
        # Campos neurais nao podem sobrepor nenhum outro campo do documento.
        for f in neural:
            for g in fields:
                if f is g:
                    continue
                overlap = not (
                    f["x"] + f["width"] <= g["x"] or g["x"] + g["width"] <= f["x"]
                    or f["y"] + f["height"] <= g["y"] or g["y"] + g["height"] <= f["y"]
                )
                self.assertFalse(overlap, f"{f['label']!r} sobrepoe {g['label']!r}")

    def test_neural_field_snaps_to_empty_cell(self):
        """Deteccao dentro de celula vazia deve preencher a celula inteira."""
        pdf_path = find_pdf("05-LISTA-DECLARACAO-DE-ACOMPANHAMENTO-COMO-OUVINTE-DE-BANCA-DE-DEFESA-DE-MESTRADO.pdf")
        if pdf_path is None:
            self.skipTest("PDF de teste não encontrado")
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[0]
            words = page.extract_words()
            layouts, _ = table_layouts(page, 1, words)
        empty_cell = None
        for table in layouts:
            for row in table["rows"]:
                for cell in row["cells"]:
                    if not (cell.get("text") or "").strip() and cell["width"] > 40 and cell["height"] > 12:
                        empty_cell = cell
                        break
                if empty_cell:
                    break
            if empty_cell:
                break
        if empty_cell is None:
            self.skipTest("Nenhuma celula vazia encontrada")
        mock_detector = MagicMock()
        # Caixinha pequena e desalinhada no meio da celula.
        mock_detector.detect.return_value = [
            {
                "page": 1,
                "x": empty_cell["x"] + empty_cell["width"] / 3,
                "y": empty_cell["y"] + empty_cell["height"] / 3,
                "width": 30,
                "height": 6,
                "confidence": 0.9,
                "source": "neural_field",
            },
        ]
        result = convert(pdf_path, field_detector=mock_detector)
        # A celula deve ter exatamente um campo alinhado a ela: o heuristico
        # da tabela (linha vazia sob cabecalho) ou o neural encaixado.
        covering = [
            f for f in result.fields
            if f["page"] == 1
            and abs(f["x"] - (empty_cell["x"] + 2.0)) <= 0.5
            and abs(f["y"] - (empty_cell["y"] + 2.0)) <= 0.5
            and abs(f["width"] - (empty_cell["width"] - 4.0)) <= 1.0
            and abs(f["height"] - (empty_cell["height"] - 4.0)) <= 1.0
        ]
        self.assertEqual(len(covering), 1, "A celula vazia deve ter um unico campo alinhado")

    def test_two_detections_in_same_cell_become_one_field(self):
        pdf_path = find_pdf("05-LISTA-DECLARACAO-DE-ACOMPANHAMENTO-COMO-OUVINTE-DE-BANCA-DE-DEFESA-DE-MESTRADO.pdf")
        if pdf_path is None:
            self.skipTest("PDF de teste não encontrado")
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[0]
            words = page.extract_words()
            layouts, _ = table_layouts(page, 1, words)
        empty_cell = None
        for table in layouts:
            for row in table["rows"]:
                for cell in row["cells"]:
                    if not (cell.get("text") or "").strip() and cell["width"] > 40 and cell["height"] > 12:
                        empty_cell = cell
                        break
                if empty_cell:
                    break
            if empty_cell:
                break
        if empty_cell is None:
            self.skipTest("Nenhuma celula vazia encontrada")
        mock_detector = MagicMock()
        mock_detector.detect.return_value = [
            {"page": 1, "x": empty_cell["x"] + 5, "y": empty_cell["y"] + 3, "width": 30, "height": 6, "confidence": 0.9, "source": "neural_field"},
            {"page": 1, "x": empty_cell["x"] + empty_cell["width"] - 40, "y": empty_cell["y"] + 5, "width": 30, "height": 6, "confidence": 0.8, "source": "neural_field"},
        ]
        result = convert(pdf_path, field_detector=mock_detector)
        # Independente de quantas deteccoes cairam na celula, so um campo
        # (heuristico ou neural) pode ocupa-la.
        cell_fields = [
            f for f in result.fields
            if f["page"] == 1
            and f["x"] >= empty_cell["x"] - 0.5
            and f["y"] >= empty_cell["y"] - 0.5
            and f["x"] + f["width"] <= empty_cell["x"] + empty_cell["width"] + 0.5
            and f["y"] + f["height"] <= empty_cell["y"] + empty_cell["height"] + 0.5
        ]
        self.assertEqual(len(cell_fields), 1, "Duas deteccoes na mesma celula devem virar um unico campo")

    def test_neural_field_on_table_border_is_dropped(self):
        pdf_path = find_pdf("05-LISTA-DECLARACAO-DE-ACOMPANHAMENTO-COMO-OUVINTE-DE-BANCA-DE-DEFESA-DE-MESTRADO.pdf")
        if pdf_path is None:
            self.skipTest("PDF de teste não encontrado")
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[0]
            words = page.extract_words()
            layouts, _ = table_layouts(page, 1, words)
        if not layouts:
            self.skipTest("Tabela nao detectada no PDF")
        table = layouts[0]
        mock_detector = MagicMock()
        # Caixa montada sobre a borda superior da tabela (metade fora).
        mock_detector.detect.return_value = [
            {
                "page": 1,
                "x": table["x"] + 5,
                "y": table["y"] - 10,
                "width": 60,
                "height": 20,
                "confidence": 0.9,
                "source": "neural_field",
            },
        ]
        result = convert(pdf_path, field_detector=mock_detector)
        for field in result.fields:
            if field["source"] != "neural_field":
                continue
            self.assertFalse(
                field["y"] < table["y"] < field["y"] + field["height"],
                "Campo neural atravessando a borda da tabela deveria ser descartado",
            )


class TestTextColorRendering(unittest.TestCase):
    def test_html_reproduces_red_text(self):
        pdf_path = find_pdf("04-Modelo-de-ata-de-Defesa.pdf")
        if pdf_path is None:
            self.skipTest("PDF de teste não encontrado")
        result = convert(pdf_path)
        # O modelo de ata tem instrucoes em vermelho (ex.: "INSTITUIÇÃO").
        self.assertRegex(result.html_content, r"\.pdf-text[^}]*color:#111")
        self.assertIn("color:rgb(", result.html_content)


if __name__ == "__main__":
    unittest.main()
