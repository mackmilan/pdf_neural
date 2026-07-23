from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
import logging
import math
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pdfplumber
from PIL import Image
from pypdf import PdfReader

LOGGER = logging.getLogger("pdf-neural.converter")

FIELD_CHOICE_WIDTH = 14.0
FIELD_CHOICE_HEIGHT = 18.0
EMAIL_TEXT_RE = re.compile(
    r"(?<![\w.+-])[\w.!#$%&'*+/=?^_`{|}~-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])",
    re.IGNORECASE,
)
URL_TEXT_RE = re.compile(
    r"(?:https?://|www\.)[\w-]+(?:\.[\w-]+)+(?:/[\w./?#&%=~-]*)?",
    re.IGNORECASE,
)


@dataclass
class Field:
    name: str
    label: str
    type: str
    page: int
    x: float
    y: float
    width: float
    height: float
    source: str = "inferred"
    required: bool = False
    href: str = ""


@dataclass
class ConversionResult:
    """Artefatos da conversao mantidos em memoria para persistencia no MongoDB."""

    html_content: str
    fields: list[dict[str, Any]]
    tables: list[dict[str, Any]]
    pages: list[dict[str, Any]]
    neural_tables: list[dict[str, Any]]


def normalize_choice_field(field: Field) -> Field:
    if field.type in {"checkbox", "radio"}:
        field.width = FIELD_CHOICE_WIDTH
        field.height = FIELD_CHOICE_HEIGHT
    return field


def n(value: float) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def css_color(value: Any, default: str = "#111") -> str:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        channel = max(0, min(255, round(float(value) * 255)))
        return f"rgb({channel},{channel},{channel})"
    if isinstance(value, (list, tuple)):
        values = [float(v) for v in value]
        if len(values) == 3:
            return "rgb(" + ",".join(str(max(0, min(255, round(v * 255)))) for v in values) + ")"
        if len(values) == 4:  # Basic CMYK to RGB conversion.
            c, m, y, k = values
            return f"rgb({round(255*(1-c)*(1-k))},{round(255*(1-m)*(1-k))},{round(255*(1-y)*(1-k))})"
    return default


def slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return value[:64] or "campo"


def infer_type(label: str, width: float, height: float) -> str:
    text = label.lower()
    rules = [
        (r"e-?mail", "email"),
        (r"telefone|celular|fone|whats", "tel"),
        (r"hor[aá]rio|\bhora\b|minuto", "time"),
        (r"data|nascimento|emiss[aã]o|validade", "date"),
        (r"cpf|cnpj|cep|rg|\bano\b|n[uú]mero|valor|quantidade", "number"),
        (r"senha", "password"),
    ]
    for pattern, kind in rules:
        if re.search(pattern, text):
            return kind
    if height > 34 or (height > 20 and width > 260):
        return "textarea"
    return "text"


def is_email_text(value: str) -> bool:
    return bool(EMAIL_TEXT_RE.search(value.strip(" <>[](){}.,;:")))


def is_url_text(value: str) -> bool:
    return bool(URL_TEXT_RE.search(value.strip(" <>[](){}.,;")))


def hyperlink_text_bboxes(words: list[dict[str, Any]]) -> list[tuple[float, float, float, float]]:
    """Areas de emails e URLs impressos: nunca devem virar campos editaveis."""
    return [
        (float(word["x0"]), float(word["top"]), float(word["x1"]), float(word["bottom"]))
        for word in words
        if is_email_text(str(word.get("text", ""))) or is_url_text(str(word.get("text", "")))
    ]


def underlined_email_bboxes(
    words: list[dict[str, Any]],
    lines: list[dict[str, Any]],
) -> list[tuple[float, float, float, float]]:
    """Retorna areas de enderecos de email impressos com sublinhado visual."""
    bboxes: list[tuple[float, float, float, float]] = []
    email_words = [word for word in words if is_email_text(str(word.get("text", "")))]
    for word in email_words:
        wx0, wtop, wx1, wbottom = (
            float(word["x0"]), float(word["top"]), float(word["x1"]), float(word["bottom"])
        )
        word_width = max(1.0, wx1 - wx0)
        for line in lines:
            lx0, lx1 = sorted((float(line["x0"]), float(line["x1"])))
            ltop = float(line.get("top", 0.0))
            lbottom = float(line.get("bottom", ltop))
            if abs(float(line.get("y1", 0.0)) - float(line.get("y0", 0.0))) > 1.5:
                continue
            overlap = min(wx1, lx1) - max(wx0, lx0)
            if overlap < word_width * 0.6:
                continue
            vertical_gap = ltop - wbottom
            if -1.5 <= vertical_gap <= 6.0:
                bboxes.append((min(wx0, lx0), wtop, max(wx1, lx1), max(wbottom, lbottom)))
    return bboxes


def nearby_label(words: list[dict[str, Any]], x: float, top: float, max_dist: float = 110, allow_right: bool = False) -> str:
    candidates = []
    for word in words:
        gap = x - float(word["x1"])
        same_line = abs(float(word["bottom"]) - top) < 12 and -5 <= gap <= max_dist
        right = allow_right and abs(float(word["bottom"]) - top) < 12 and 0 <= float(word["x0"]) - x <= max_dist
        above = 0 <= top - float(word["bottom"]) < 24 and abs(float(word["x0"]) - x) < max_dist
        if same_line or right or above:
            dist = abs(x - float(word["x1"])) + abs(top - float(word["bottom"])) * 2
            candidates.append((dist, float(word["x0"]), word["text"]))
    candidates.sort()
    selected = sorted(candidates[:4], key=lambda item: item[1])
    return " ".join(item[2] for item in selected).strip(" :.-")


def acro_fields(reader: PdfReader) -> dict[int, list[Field]]:
    result: dict[int, list[Field]] = {}
    for page_no, page in enumerate(reader.pages, 1):
        page_height = float(page.mediabox.height)
        annotations = page.get("/Annots") or []
        for ref in annotations:
            annotation = ref.get_object()
            if annotation.get("/Subtype") != "/Widget":
                continue
            parent = annotation.get("/Parent")
            parent = parent.get_object() if parent else annotation
            raw_name = str(parent.get("/T") or annotation.get("/T") or f"campo_{page_no}")
            ft = str(parent.get("/FT") or annotation.get("/FT") or "/Tx")
            flags = int(parent.get("/Ff", 0))
            rect = [float(v) for v in annotation.get("/Rect", [0, 0, 100, 18])]
            x, bottom, x2, top_pdf = rect
            top = page_height - top_pdf
            kind = "checkbox" if ft == "/Btn" else "select" if ft == "/Ch" else "textarea" if flags & 4096 else infer_type(raw_name, x2-x, top_pdf-bottom)
            result.setdefault(page_no, []).append(Field(raw_name, raw_name.replace("_", " ").title(), kind, page_no, x, top, x2-x, top_pdf-bottom, "acroform", bool(flags & 2)))
    return result


def textual_segmented_fields(
    page: pdfplumber.page.Page,
    words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Separa segmentos de data e hora delimitados por ``/`` e ``:``."""
    fields: list[dict[str, Any]] = []
    underscore_rows = sorted({round(float(char["bottom"]), 1) for char in page.chars if str(char.get("text", "")) == "_"})
    for row_bottom in underscore_rows:
        row_chars = sorted(
            [char for char in page.chars if abs(float(char["bottom"]) - row_bottom) <= 2],
            key=lambda char: float(char["x0"]),
        )
        row_words = [word for word in words if abs(float(word["bottom"]) - row_bottom) <= 2]
        row_text = " ".join(str(word.get("text", "")) for word in row_words).lower()
        slash_count = sum(str(char.get("text", "")) == "/" for char in row_chars)
        colon_count = sum(str(char.get("text", "")) == ":" for char in row_chars)
        is_date = "data" in row_text or slash_count >= 2
        is_time = "horário" in row_text or "horario" in row_text
        if not is_date and not is_time:
            continue

        groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for char in row_chars:
            if str(char.get("text", "")) == "_":
                current.append(char)
            elif current:
                groups.append(current)
                current = []
        if current:
            groups.append(current)

        labels = ("hora", "minuto") if is_time and not is_date else ("dia", "mes", "ano")
        kind = "time" if is_time and not is_date else "date"
        for index, group in enumerate(groups):
            if len(group) < 2:
                continue
            x0 = min(float(char["x0"]) for char in group)
            x1 = max(float(char["x1"]) for char in group)
            bottom = max(float(char["bottom"]) for char in group)
            if x1 - x0 >= 10:
                part = labels[index] if index < len(labels) else str(index + 1)
                fields.append({
                    "bbox": (x0, max(0.0, bottom - 20.0), x1, bottom),
                    "label": f"{'Horário' if kind == 'time' else 'Data'} - {part}",
                    "type": kind,
                })
    return fields


def textual_date_boxes(
    page: pdfplumber.page.Page,
    words: list[dict[str, Any]],
) -> list[tuple[float, float, float, float]]:
    """Compatibilidade para consumidores que precisam apenas das datas."""
    return [field["bbox"] for field in textual_segmented_fields(page, words) if field["type"] == "date"]


def textual_empty_parentheses_fields(
    page: pdfplumber.page.Page,
    words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detecta somente a sequencia textual exata ``( )`` como controle visual."""
    fields: list[dict[str, Any]] = []
    rows: list[list[dict[str, Any]]] = []
    char_top = lambda item: float(item.get("top", item.get("bottom", 0.0)))
    for char in sorted(page.chars, key=lambda item: (round(char_top(item), 1), float(item["x0"]))):
        if not rows or abs(char_top(char) - char_top(rows[-1][0])) > 2.5:
            rows.append([char])
        else:
            rows[-1].append(char)

    for row in rows:
        for index in range(len(row) - 2):
            first = row[index]
            if str(first.get("text", "")) != "(":
                continue
            # Um ou mais espacos entre os parenteses: PDFs variam entre
            # "( )" e "(  )" dependendo do editor que gerou o formulario.
            cursor = index + 1
            while cursor < len(row) and str(row[cursor].get("text", "")) == " ":
                cursor += 1
            if cursor == index + 1 or cursor >= len(row) or str(row[cursor].get("text", "")) != ")":
                continue
            last = row[cursor]
            group = row[index:cursor + 1]
            x0 = float(first["x0"])
            x1 = float(last["x1"])
            top = min(char_top(char) for char in group)
            bottom = max(float(char["bottom"]) for char in group)
            label = (
                nearby_label(words, x1, bottom, allow_right=True)
                or nearby_label(words, x0, bottom)
                or f"Opção {len(fields) + 1}"
            )
            fields.append({
                "bbox": (x0, top, x1, bottom),
                "label": label,
                "type": "checkbox",
            })
    return fields


def textual_label_colon_fields(
    page: pdfplumber.page.Page,
    words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rotulos terminados em ``:`` seguidos de espaco em branco indicam campo.

    Formularios como "Titulo:", "Mestrando:" ou "Local:" frequentemente nao tem
    linha, underscore ou retangulo; o proprio rotulo delimita a area de escrita
    ate a proxima palavra ou a margem direita do texto.
    """
    fields: list[dict[str, Any]] = []
    if not words:
        return fields
    right_margin = max(float(word["x1"]) for word in words)
    lines: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (float(item["top"]), float(item["x0"]))):
        if not lines or abs(float(word["top"]) - float(lines[-1][0]["top"])) > 3:
            lines.append([word])
        else:
            lines[-1].append(word)

    for line_words in lines:
        label_start = 0
        for index, word in enumerate(line_words):
            text = str(word.get("text", ""))
            if not text.endswith(":") or not any(char.isalpha() for char in text):
                continue
            label = " ".join(str(w.get("text", "")) for w in line_words[label_start:index + 1]).rstrip(" :")
            label_start = index + 1
            if is_email_text(label) or is_url_text(label):
                continue
            field_x = float(word["x1"]) + 6
            next_x = (
                float(line_words[index + 1]["x0"]) - 6
                if index + 1 < len(line_words)
                else max(right_margin, field_x)
            )
            width = next_x - field_x
            if width < 45:
                continue
            # A caixa acompanha a altura da propria linha do rotulo: com 20pt
            # fixos, formularios de linhas proximas gerariam campos sobrepostos.
            top = float(word["top"])
            bottom = float(word["bottom"])
            fields.append({
                "bbox": (field_x, max(0.0, top), next_x, bottom),
                "label": label or f"Campo {len(fields) + 1}",
                "type": infer_type(label, width, bottom - top),
            })
    return fields


def textual_dotted_fields(
    page: pdfplumber.page.Page,
    words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Linhas pontilhadas de preenchimento (``....``) sao campos de escrita.

    Documentos como atas usam pontos no lugar de underscores: "Aos .........
    dias do mes de ...............". Agrupamos sequencias de pontos da mesma
    linha, como ja fazemos com underscores em ``textual_segmented_fields``.
    """
    fields: list[dict[str, Any]] = []
    rows: dict[float, list[dict[str, Any]]] = {}
    for char in page.chars:
        if str(char.get("text", "")) != ".":
            continue
        row_key = round(float(char["bottom"]), 1)
        matched = next((key for key in rows if abs(key - row_key) <= 2), None)
        rows.setdefault(matched if matched is not None else row_key, []).append(char)

    for row_chars in rows.values():
        row_chars.sort(key=lambda char: float(char["x0"]))
        groups: list[list[dict[str, Any]]] = []
        for char in row_chars:
            if groups and float(char["x0"]) - float(groups[-1][-1]["x1"]) <= 3:
                groups[-1].append(char)
            else:
                groups.append([char])
        for group in groups:
            if len(group) < 4:
                continue
            x0 = min(float(char["x0"]) for char in group)
            x1 = max(float(char["x1"]) for char in group)
            bottom = max(float(char["bottom"]) for char in group)
            if x1 - x0 < 12:
                continue
            label = nearby_label(words, x0, bottom) or f"Campo {len(fields) + 1}"
            # Altura de linha tipica (12pt) evita invadir a linha de cima em
            # paragrafos compactos como os de atas.
            fields.append({
                "bbox": (x0, max(0.0, bottom - 12.0), x1, bottom),
                "label": label,
                "type": infer_type(label, x1 - x0, 12),
            })
    return fields


def inferred_fields(
    page: pdfplumber.page.Page,
    page_no: int,
    words: list[dict[str, Any]],
    existing: list[Field],
    table_bboxes: list[tuple[float, float, float, float]] | None = None,
) -> list[Field]:
    fields: list[Field] = []
    seen: set[tuple[int, int]] = set()
    table_bboxes = table_bboxes or []
    email_underline_bboxes = underlined_email_bboxes(words, page.lines) + hyperlink_text_bboxes(words)

    def overlaps(x: float, y: float, w: float, h: float) -> bool:
        return any(not (x+w < f.x or f.x+f.width < x or y+h < f.y or f.y+f.height < y) for f in existing + fields)

    def inside_table(x: float, y: float, w: float, h: float) -> bool:
        return any(
            x >= tx0 - 1 and y >= top - 1 and x + w <= tx1 + 1 and y + h <= bottom + 1
            for tx0, top, tx1, bottom in table_bboxes
        )

    def overlaps_underlined_email(x: float, y: float, w: float, h: float) -> bool:
        return any(
            not (x + w < ex0 or ex1 < x or y + h < ey0 or ey1 < y)
            for ex0, ey0, ex1, ey1 in email_underline_bboxes
        )

    # Palavras impressas: um campo de escrita nao pode cobrir conteudo ja
    # existente (ex.: reguas de tabelas estaticas com valores como "R$ 10,00").
    printed_bboxes = [
        (float(word["x0"]), float(word["top"]), float(word["x1"]), float(word["bottom"]))
        for word in words
        if any(char.isalnum() for char in str(word.get("text", "")))
    ]

    def overlaps_printed_text(x: float, y: float, w: float, h: float) -> bool:
        return any(
            not (x + w < tx0 or tx1 < x or y + h < ty0 or ty1 < y)
            for tx0, ty0, tx1, ty1 in printed_bboxes
        )

    # Horizontal writing lines are the most common non-AcroForm field representation.
    for line in page.lines:
        x0, x1 = sorted((float(line["x0"]), float(line["x1"])))
        top = float(line.get("top", page.height - line["y0"]))
        width = x1 - x0
        if (
            width < 45
            or abs(float(line["y1"]) - float(line["y0"])) > 1.5
            or inside_table(x0, top-1, width, 2)
            or overlaps(x0, top-18, width, 20)
            or overlaps_underlined_email(x0, top-18, width, 20)
        ):
            continue
        label = nearby_label(words, x0, top) or f"Campo {len(existing)+len(fields)+1}"
        kind = infer_type(label, width, 20)
        # Linha coberta por texto impresso e sublinhado ou regua de tabela
        # estatica, nao area de preenchimento (mesmo filtro usado no treino).
        if kind not in {"date", "time"} and overlaps_printed_text(x0, top-18, width, 18):
            continue
        key = (round(x0), round(top))
        if key in seen:
            continue
        seen.add(key)
        fields.append(Field(slug(label), label, kind, page_no, x0, max(0, top-20), width, 20))

    # Datas produzidas por editores como o LibreOffice podem ser texto puro, por
    # exemplo: "Data: ___ de __________ de 20___.". Nesse caso nao existe uma
    # linha PDF para a heuristica acima. Agrupamos todos os underscores da mesma
    # linha em um unico campo, incluindo os separadores literais no seu interior.
    for segmented in textual_segmented_fields(page, words):
        x0, top, x1, bottom = segmented["bbox"]
        width = x1 - x0
        key = (round(x0), round(bottom))
        if width < 10 or key in seen or inside_table(x0, top, width, 20) or overlaps(x0, top, width, 20):
            continue
        seen.add(key)
        label = segmented["label"]
        fields.append(Field(slug(label), label, segmented["type"], page_no, x0, top, width, 20))

    # Rotulos "Titulo:" / "Mestrando:" com espaco em branco a direita e linhas
    # pontilhadas "......." tambem representam areas de escrita sem borda.
    for textual in textual_label_colon_fields(page, words) + textual_dotted_fields(page, words):
        x0, top, x1, bottom = textual["bbox"]
        width, height = x1 - x0, bottom - top
        key = (round(x0), round(bottom))
        if (
            width < 12
            or key in seen
            or inside_table(x0, top, width, height)
            or overlaps(x0, top, width, height)
            or overlaps_underlined_email(x0, top, width, height)
        ):
            continue
        seen.add(key)
        label = textual["label"]
        fields.append(Field(slug(label), label, textual["type"], page_no, x0, top, width, height))

    for option in textual_empty_parentheses_fields(page, words):
        x0, top, x1, bottom = option["bbox"]
        width, height = x1 - x0, bottom - top
        key = (round(x0), round(top))
        if width < 4 or height < 4 or key in seen or inside_table(x0, top, width, height) or overlaps(x0, top, width, height):
            continue
        seen.add(key)
        label = option["label"]
        fields.append(normalize_choice_field(Field(slug(label), label, option["type"], page_no, x0, top, max(8, width), max(8, height))))

    # Empty small rectangles usually represent checkboxes; larger ones are inputs/areas.
    for rect in page.rects:
        x, top = float(rect["x0"]), float(rect["top"])
        width, height = float(rect["width"]), float(rect["height"])
        if width < 8 or height < 8 or width > page.width * .9 or height > page.height * .8 or inside_table(x, top, width, height) or overlaps(x, top, width, height):
            continue
        is_checkbox = width <= 24 and height <= 24
        label = nearby_label(words, x + width, top + height, allow_right=is_checkbox) or f"Campo {len(existing)+len(fields)+1}"
        kind = "checkbox" if width <= 24 and height <= 24 else infer_type(label, width, height)
        fields.append(normalize_choice_field(Field(slug(label), label, kind, page_no, x, top, width, height)))
    return fields


def table_layouts(
    page: pdfplumber.page.Page,
    page_no: int,
    words: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[Field]]:
    """Extract ruled-table geometry and turn empty value cells into fields.

    PDF tables are only drawing commands.  pdfplumber reconstructs their rows and
    cells from intersecting edges; keeping that result separate prevents the
    generic line detector from treating every table border as a writing line.
    """
    layouts: list[dict[str, Any]] = []
    fields: list[Field] = []
    for table_index, table in enumerate(page.find_tables(table_settings={"intersection_tolerance": 15}), 1):
        # We need to manually check for rects that should be part of the table grid
        # but aren't because they lack explicit lines.
        x0, top, x1, bottom = (float(value) for value in table.bbox)
        explicit_v = sorted({round(float(x), 3) for row in table.rows for cell in row.cells if cell is not None for x in (cell[0], cell[2])})
        explicit_h = sorted({round(float(y), 3) for row in table.rows for cell in row.cells if cell is not None for y in (cell[1], cell[3])})

        extracted = table.extract()
        # If the table extraction returned empty cells for header areas,
        # we try to fill them using word detection within those rectangles.
        if any(rect.get("non_stroking_color") and rect.get("non_stroking_color") != 1 for rect in page.rects):
            for row_index, row in enumerate(table.rows):
                for column_index, cell_bbox in enumerate(row.cells):
                    if cell_bbox is None: continue
                    # Only if the cell is currently empty in 'extracted'
                    if not (extracted[row_index][column_index] or "").strip():
                        cx0, ctop, cx1, cbottom = cell_bbox
                        # Check if this cell coincides with a colored rect
                        for rect in page.rects:
                            rx0, rtop, rx1, rbottom = (float(rect[k]) for k in ("x0", "top", "x1", "bottom"))
                            color = rect.get("non_stroking_color")
                            if color and color != 1 and color != (1, 1, 1):
                                # If cell is inside or mostly inside the rect
                                if rx0-1 <= cx0 and cx1 <= rx1+1 and rtop-1 <= ctop and cbottom <= rbottom+1:
                                    cell_text = page.within_bbox(cell_bbox).extract_text()
                                    if cell_text:
                                        extracted[row_index][column_index] = cell_text
                                    break

        boundaries = sorted({
            round(float(x), 3)
            for row in table.rows
            for cell in row.cells if cell is not None
            for x in (cell[0], cell[2])
        })
        rows: list[dict[str, Any]] = []
        for row_index, row in enumerate(table.rows):
            values = extracted[row_index] if row_index < len(extracted) else []
            cells: list[dict[str, Any]] = []
            for column_index, bbox in enumerate(row.cells):
                text = values[column_index] if column_index < len(values) else None
                if bbox is None:
                    continue
                x0, top, x1, bottom = (float(value) for value in bbox)
                start_column = min(range(len(boundaries)), key=lambda i: abs(boundaries[i] - x0))
                end_column = min(range(len(boundaries)), key=lambda i: abs(boundaries[i] - x1))
                cells.append({
                    "column": start_column + 1,
                    "colspan": max(1, end_column - start_column),
                    "rowspan": 1,
                    "x": x0,
                    "y": top,
                    "width": x1 - x0,
                    "height": bottom - top,
                    "text": text or "",
                })

                # A blank cell beside a labelled cell is a characteristic
                # layout of registration forms.
                if text in ("", None):
                    labels = [
                        str(value).strip()
                        for value in values[:column_index]
                        if value is not None and str(value).strip()
                    ]
                    if labels:
                        label = " ".join(labels)
                        padding = 2.0
                        fields.append(Field(
                            slug(label), label, infer_type(label, x1 - x0, bottom - top),
                            page_no, x0 + padding, top + padding,
                            max(1, x1 - x0 - 2 * padding), max(1, bottom - top - 2 * padding),
                            "table",
                        ))

                cell_words = [
                    word for word in words
                    if float(word["x0"]) >= x0 - 1 and float(word["x1"]) <= x1 + 1
                    and float(word["top"]) >= top - 1 and float(word["bottom"]) <= bottom + 1
                ]
                word_lines: list[list[dict[str, Any]]] = []
                for word in sorted(cell_words, key=lambda item: (float(item["top"]), float(item["x0"]))):
                    if not word_lines or abs(float(word["top"]) - float(word_lines[-1][0]["top"])) > 2.5:
                        word_lines.append([word])
                    else:
                        word_lines[-1].append(word)

                for line_index, line_words in enumerate(word_lines):
                    tokens = [str(word["text"]) for word in line_words]
                    # Parenthesized blanks in option lists are visual checkboxes.
                    if "(" in tokens and ")" in tokens:
                        open_index, close_index = tokens.index("("), tokens.index(")")
                        if close_index > open_index:
                            label = " ".join(tokens[:open_index]).strip(" :-")
                            if not label:
                                # Opcoes como "( ) Não." tem o rotulo depois
                                # do fecha-parentese.
                                label = " ".join(tokens[close_index + 1:]).strip(" :-.")
                            if label:
                                left = float(line_words[open_index]["x0"])
                                right = float(line_words[close_index]["x1"])
                                line_top = min(float(word["top"]) for word in line_words)
                                line_bottom = max(float(word["bottom"]) for word in line_words)
                                fields.append(normalize_choice_field(Field(
                                    slug(label), label, "checkbox", page_no,
                                    left, line_top, max(8, right - left), max(8, line_bottom - line_top),
                                    "table",
                                )))

                    # Labels ending in ':' inside a tall/merged cell describe
                    # independent writing areas even though no inner borders exist.
                    if not tokens or not tokens[-1].endswith(":"):
                        continue
                    label = " ".join(tokens).rstrip(" :").strip()
                    field_x = max(float(word["x1"]) for word in line_words) + 6
                    if x1 - field_x < 45:
                        continue
                    band_top = max(top, float(line_words[0]["top"]) - 2)
                    next_top = (
                        float(word_lines[line_index + 1][0]["top"]) - 2
                        if line_index + 1 < len(word_lines) else bottom - 2
                    )
                    band_height = next_top - band_top
                    type_height = band_height if band_height > 34 else min(20, band_height)
                    fields.append(Field(
                        slug(label), label, infer_type(label, x1 - field_x, type_height),
                        page_no, field_x, band_top,
                        max(1, x1 - field_x - 3), max(10, band_height),
                        "table",
                    ))
            rows.append({"index": row_index + 1, "cells": cells})

        # Linhas totalmente vazias sob um cabecalho (ex.: "Data | Carga | Descricao"
        # ou "NOME | R.A. | E-MAIL") sao areas de preenchimento: um campo por
        # celula, alinhado ao desenho da tabela e rotulado pela coluna.
        header_values: list[str] | None = None
        if len(boundaries) > 2:  # tabelas com pelo menos duas colunas
            for row_values in extracted:
                if row_values and any(str(v or "").strip() for v in row_values):
                    header_values = [str(v or "").strip() for v in row_values]
                    break
        if header_values:
            for row_index, row in enumerate(table.rows):
                values = extracted[row_index] if row_index < len(extracted) else []
                if any(str(v or "").strip() for v in values):
                    continue
                for column_index, cell_bbox in enumerate(row.cells):
                    if cell_bbox is None:
                        continue
                    cx0, ctop, cx1, cbottom = (float(v) for v in cell_bbox)
                    if cx1 - cx0 < 20 or cbottom - ctop < 10:
                        continue
                    header = (
                        header_values[column_index]
                        if column_index < len(header_values) and header_values[column_index]
                        else f"Coluna {column_index + 1}"
                    )
                    label = f"{header} {row_index + 1}"
                    padding = 2.0
                    fields.append(Field(
                        slug(label), label,
                        infer_type(header, cx1 - cx0, cbottom - ctop),
                        page_no, cx0 + padding, ctop + padding,
                        max(1, cx1 - cx0 - 2 * padding), max(1, cbottom - ctop - 2 * padding),
                        "table",
                    ))

        x0, top, x1, bottom = (float(value) for value in table.bbox)
        layouts.append({
            "id": f"page-{page_no}-table-{table_index}",
            "page": page_no,
            "x": x0,
            "y": top,
            "width": x1 - x0,
            "height": bottom - top,
            "row_count": len(rows),
            "column_count": max(0, len(boundaries) - 1),
            "rows": rows,
        })
    return layouts, fields


def image_key(name: str) -> str:
    """Return the PDF XObject name shared by pypdf and pdfplumber."""
    return Path(str(name)).stem


def extract_images(pdf_path: Path, output: Path = None, job_id: str = None) -> dict[int, dict[str, dict[str, Any]]]:
    from backend.app.db.mongo import db
    LOGGER.info("Extraindo imagens de %s", pdf_path.name)
    reader = PdfReader(str(pdf_path))
    extracted: dict[int, dict[str, dict[str, Any]]] = {}
    fingerprints: dict[str, dict[str, Any]] = {}
    for page_no, page in enumerate(reader.pages, 1):
        for index, image in enumerate(page.images, 1):
            key = image_key(image.name) or f"image-{index}"
            data_hash = hashlib.md5(image.data).hexdigest()
            if data_hash in fingerprints:
                extracted.setdefault(page_no, {})[key] = fingerprints[data_hash]
                continue

            # Convert to PNG for consistent base64 representation
            try:
                img = Image.open(io.BytesIO(image.data))
                out_io = io.BytesIO()
                img.save(out_io, "PNG")
                png_data = out_io.getvalue()
                content_type = "image/png"
            except Exception:
                png_data = image.data
                suffix = Path(image.name).suffix.lower()
                content_type = f"image/{suffix[1:]}" if suffix.startswith(".") else "image/png"

            b64_data = base64.b64encode(png_data).decode("utf-8")
            asset_info = {
                "hash": data_hash,
                "base64": b64_data,
                "content_type": content_type
            }
            
            if job_id and db and db.is_available():
                try:
                    db.save_image(job_id, key, data_hash, b64_data, content_type)
                except Exception as e:
                    LOGGER.error("Erro ao salvar imagem %s no MongoDB: %s", key, str(e))

            extracted.setdefault(page_no, {})[key] = asset_info
            fingerprints[data_hash] = asset_info
    return extracted


def convert(
    pdf_path: str | Path,
    output_dir: str | Path | None = None,
    table_detector: Any | None = None,
    field_detector: Any | None = None,
    job_id: str | None = None,
) -> Path | ConversionResult:
    """Converte um PDF.

    Sem ``output_dir``, devolve todos os artefatos em memoria. O modo com
    diretorio continua disponivel apenas para a CLI e compatibilidade da API
    publica desta funcao.
    """
    pdf_path = Path(pdf_path)
    output = Path(output_dir) if output_dir is not None else None
    LOGGER.info("Iniciando conversão de %s%s", pdf_path.name, f" para {output}" if output else " em memoria")
    if output is not None:
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True)
    reader = PdfReader(str(pdf_path))
    native = acro_fields(reader)
    images = extract_images(pdf_path, output, job_id=job_id)
    all_fields: list[Field] = []
    all_tables: list[dict[str, Any]] = []
    page_sizes: list[dict[str, Any]] = []
    pages_html: list[str] = []

    # Inferência neural de campos (se disponível) para o documento todo de uma vez
    neural_fields_by_page: dict[int, list[dict[str, Any]]] = {}
    if field_detector:
        try:
            neural_fields_data = field_detector.detect(pdf_path)
            for nf in neural_fields_data:
                neural_fields_by_page.setdefault(nf["page"], []).append(nf)
        except Exception as e:
            LOGGER.error("Erro na detecção neural de campos: %s", e)

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            page_width, page_height = float(page.width), float(page.height)
            page_sizes.append({
                "page": page_no,
                "width": page_width,
                "height": page_height,
                "unit": "pt",
                "aspect_ratio": page_width / page_height,
                "orientation": "landscape" if page_width > page_height else "portrait",
            })
            # non_stroking_color permite reproduzir no HTML a cor original do
            # texto (ex.: instrucoes em vermelho em modelos de ata).
            words = page.extract_words(extra_attrs=["fontname", "size", "non_stroking_color"], keep_blank_chars=False)
            fields = native.get(page_no, [])
            layouts, table_fields = table_layouts(page, page_no, words)
            all_tables.extend(layouts)
            fields += table_fields

            table_bboxes = [
                (table["x"], table["y"], table["x"] + table["width"], table["y"] + table["height"])
                for table in layouts
            ]
            fields += inferred_fields(page, page_no, words, fields, table_bboxes)

            if page_no in neural_fields_by_page:
                # Obter bboxes de imagens para filtragem
                image_bboxes = []
                for img in page.images:
                    ix0, iy0, ix1, iy1 = float(img["x0"]), float(img["top"]), float(img["x1"]), float(img["bottom"])
                    image_bboxes.append((ix0, iy0, ix1, iy1))

                # Obter bboxes de texto para filtragem
                text_bboxes = []
                for word in words:
                    text_bboxes.append((float(word["x0"]), float(word["top"]), float(word["x1"]), float(word["bottom"])))

                # Bboxes de cabeçalhos de tabelas
                header_bboxes = []
                for table in layouts:
                    # Assumimos que a primeira linha de cada tabela pode conter cabeçalhos.
                    # Mais seguro: filtrar qualquer área de célula que contenha texto na tabela.
                    for row in table.get("rows", []):
                        for cell in row.get("cells", []):
                            if cell.get("text") and cell["text"].strip():
                                header_bboxes.append((cell["x"], cell["y"], cell["x"] + cell["width"], cell["y"] + cell["height"]))

                # Obter bboxes de linhas para detectar sublinhados
                line_bboxes = []
                for line in page.lines:
                    lx0, ly0, lx1, ly1 = float(line["x0"]), float(line["top"]), float(line["x1"]), float(line["bottom"])
                    # Sublinhados costumam ser linhas horizontais finas
                    line_bboxes.append((lx0, ly0, lx1, ly1))
                # Emails e URLs impressos (com ou sem sublinhado) nao sao campos.
                email_underline_bboxes = underlined_email_bboxes(words, page.lines) + hyperlink_text_bboxes(words)

                # Geometria das celulas para validar deteccoes dentro de tabelas.
                table_rects = [
                    (table["x"], table["y"], table["x"] + table["width"], table["y"] + table["height"])
                    for table in layouts
                ]
                cell_infos = []
                for table in layouts:
                    for row in table.get("rows", []):
                        for cell in row.get("cells", []):
                            cell_infos.append((
                                cell["x"], cell["y"],
                                cell["x"] + cell["width"], cell["y"] + cell["height"],
                                bool((cell.get("text") or "").strip()),
                            ))

                for nf in neural_fields_by_page[page_no]:
                    nx, ny, nw, nh = nf["x"], nf["y"], nf["width"], nf["height"]
                    # Ativacoes minusculas sao ruido do modelo, nao campos uteis.
                    if nw < 25 or nh < 4:
                        continue
                    label = nf.get("label") or nearby_label(words, nx, ny + nh) or f"Campo Neural {len(all_fields) + len(fields) + 1}"
                    if infer_type(label, nw, nh) == "date" and "_" in label:
                        label = "Data"

                    # Padroniza a altura ANTES das checagens de sobreposicao:
                    # a caixa final (base preservada, topo estendido) e a que
                    # nao pode invadir texto ou outros campos.
                    target_h = 20.0
                    if nh != target_h and nf.get("type") not in {"textarea"}:
                        ny = ny + nh - target_h
                        nh = target_h
                    nx1, ny1 = nx + nw, ny + nh

                    # Dentro de tabelas, so aceitamos deteccoes contidas em uma
                    # celula vazia; caixas sobre bordas, cabecalhos ou celulas
                    # preenchidas sao falsos positivos (inicio de tabela, tracos).
                    if any(not (nx1 <= tx0 or tx1 <= nx or ny1 <= ty0 or ty1 <= ny) for (tx0, ty0, tx1, ty1) in table_rects):
                        center_x, center_y = nx + nw / 2, ny + nh / 2
                        containing = next(
                            (cell for cell in cell_infos
                             if cell[0] <= center_x <= cell[2] and cell[1] <= center_y <= cell[3]),
                            None,
                        )
                        if containing is None or containing[4]:
                            continue
                        # Encaixa o campo na celula inteira: a deteccao neural
                        # so indica ONDE ha um campo; a geometria vem do
                        # desenho da tabela, como nos campos de table_layouts.
                        padding = 2.0
                        nx, ny = containing[0] + padding, containing[1] + padding
                        nx1, ny1 = containing[2] - padding, containing[3] - padding
                        nw, nh = nx1 - nx, ny1 - ny
                        if nw < 8 or nh < 6:
                            continue

                    # Evitar sobreposição com imagens
                    if any(not (nx1 <= ix0 or ix1 <= nx or ny1 <= iy0 or iy1 <= ny) for (ix0, iy0, ix1, iy1) in image_bboxes):
                        # LOGGER.debug("Neural field at (%f, %f) filtered by image", nx, ny)
                        continue

                    # Evitar que emails impressos com sublinhado (ex.: hyperlinks)
                    # sejam tratados como campos editáveis pela rede.
                    if any(not (nx1 < ex0 or ex1 < nx or ny1 < ey0 or ey1 < ny) for (ex0, ey0, ex1, ey1) in email_underline_bboxes):
                        continue

                    # Evitar sobreposição com texto
                    # Relaxamos um pouco a margem (usando < em vez de <= para permitir encostar)
                    overlaps_text = any(
                        not (nx1 < tx0 or tx1 < nx or ny1 < ty0 or ty1 < ny)
                        for (tx0, ty0, tx1, ty1) in text_bboxes
                    )
                    # Em datas compostas, "de" e "20" fazem parte da mascara
                    # consolidada e ficam deliberadamente dentro da caixa.
                    if overlaps_text and infer_type(label, nw, nh) not in {"date", "time"}:
                        # LOGGER.debug("Neural field at (%f, %f) filtered by text", nx, ny)
                        continue

                    # Evitar sobreposição com células preenchidas de tabelas (incluindo cabeçalhos)
                    if any(not (nx1 < hx0 or hx1 < nx or ny1 < hy0 or hy1 < ny) for (hx0, hy0, hx1, hy1) in header_bboxes):
                        # LOGGER.debug("Neural field at (%f, %f) filtered by table header", nx, ny)
                        continue

                    # Evitar sobreposição com linhas (possíveis sublinhados)
                    # Um campo não deve estar "atravessado" por uma linha ou muito perto de uma linha de texto.
                    # Se a linha estiver dentro ou muito próxima da base do campo, pode ser um sublinhado.
                    overlaps_line = any(
                        not (nx1 < lx0 or lx1 < nx or ny1 < ly0 or ly1 < ny)
                        for (lx0, ly0, lx1, ly1) in line_bboxes
                    )
                    # O traco e a aparencia esperada de campos como
                    # "Data: ____". A excecao fica restrita ao tipo date para
                    # manter a protecao contra falsos positivos em outras linhas.
                    if overlaps_line and infer_type(label, nw, nh) != "date":
                        continue

                    # Evitar sobreposição com campos já detectados (AcroForms, tabelas ou heurística)
                    # Usamos uma margem pequena para tolerar imprecisões na rede
                    is_overlap = False
                    replace_inferred_date = None
                    for field_index, f in enumerate(fields):
                        # Intersecção simples
                        if not (nx1 < f.x or f.x + f.width < nx or ny1 < f.y or f.y + f.height < ny):
                            if f.source == "inferred" and f.type in {"date", "time"} and infer_type(label, nw, nh) == f.type:
                                replace_inferred_date = field_index
                                continue
                            is_overlap = True
                            break
                    if is_overlap:
                        continue
                    if replace_inferred_date is not None:
                        fields.pop(replace_inferred_date)

                    fields.append(Field(slug(label), label, infer_type(label, nw, nh), page_no, nx, ny, nw, nh, source="neural_field"))
            # Keep names unique across repeated labels.
            used = {f.name for f in all_fields}
            for field in fields:
                normalize_choice_field(field)
                base, counter = field.name, 2
                while field.name in used:
                    field.name = f"{base}_{counter}"; counter += 1
                used.add(field.name)
                field.href = f"index.html#{field.name}"
            all_fields.extend(fields)

            elements: list[str] = []

            for rect in page.rects:
                stroke = css_color(rect.get("stroking_color"), "transparent")
                fill = css_color(rect.get("non_stroking_color"), "transparent") if rect.get("fill") else "transparent"
                elements.append(f'<div class="pdf-rect" style="left:{n(rect["x0"])}px;top:{n(rect["top"])}px;width:{n(rect["width"])}px;height:{n(rect["height"])}px;border-color:{stroke};background:{fill}"></div>')
            for line in page.lines:
                x, top = float(line["x0"]), float(line["top"])
                w = max(1, float(line["x1"])-x)
                h = max(1, float(line["bottom"])-top)
                color = css_color(line.get("stroking_color"))
                elements.append(f'<div class="pdf-line" style="left:{n(x)}px;top:{n(top)}px;width:{n(w)}px;height:{n(h)}px;border-color:{color}"></div>')
            for curve in page.curves:
                points = curve.get("pts") or []
                if len(points) < 2:
                    continue
                coords = " ".join(f'{n(p[0])},{n(page.height-p[1])}' for p in points)
                stroke = css_color(curve.get("stroking_color"), "#111")
                fill = css_color(curve.get("non_stroking_color"), "transparent") if curve.get("fill") else "none"
                elements.append(f'<svg class="pdf-vector" viewBox="0 0 {n(page.width)} {n(page.height)}" aria-hidden="true"><polyline points="{coords}" stroke="{stroke}" fill="{fill}" stroke-width="{n(curve.get("linewidth", 1) or 1)}"/></svg>')
            for image_obj in page.images:
                page_assets = images.get(page_no, {})
                key = image_key(str(image_obj.get("name", "")))
                asset = page_assets.get(key)
                if asset is None:
                    index_key = f"image-{page.images.index(image_obj) + 1}"
                    asset = page_assets.get(index_key)
                if asset is None:
                    continue
                src = f"data:{asset['content_type']};base64,{asset['base64']}"
                elements.append(f'<img class="pdf-image" data-pdf-image="{html.escape(key)}" src="{src}" alt="Imagem extraida do PDF" style="left:{n(image_obj["x0"])}px;top:{n(image_obj["top"])}px;width:{n(image_obj["width"])}px;height:{n(image_obj["height"])}px">')

            for layout in layouts:
                table_html = [f'<table class="pdf-table" id="{layout["id"]}" style="left:{n(layout["x"])}px;top:{n(layout["y"])}px;width:{n(layout["width"])}px;height:{n(layout["height"])}px">']
                for row in layout["rows"]:
                    table_html.append('<tr>')
                    for cell in row["cells"]:
                        style = f'width:{n(cell["width"])}px;height:{n(cell["height"])}px;'
                        colspan = f' colspan="{cell["colspan"]}"' if cell["colspan"] > 1 else ""
                        rowspan = f' rowspan="{cell["rowspan"]}"' if cell["rowspan"] > 1 else ""
                        content = html.escape(cell["text"]).replace("\n", "<br>")
                        table_html.append(f'<td{colspan}{rowspan} style="{style}">{content}</td>')
                    table_html.append('</tr>')
                table_html.append('</table>')
                elements.append("".join(table_html))

            for field in fields:
                style = f"left:{n(field.x)}px;top:{n(field.y)}px;width:{n(field.width)}px;height:{n(field.height)}px"
                elements.append(f'<a href="#{html.escape(field.name)}" class="pdf-field" id="{html.escape(field.name)}" data-name="{html.escape(field.name)}" data-type="{field.type}" style="{style}" title="{html.escape(field.label)}"></a>')

            for word in words:
                font = html.escape(str(word.get("fontname", "Arial")).split("+")[-1])
                # data-w guarda a largura original da palavra no PDF; o script
                # aplica scaleX para a fonte substituta ocupar exatamente esse
                # espaco, evitando que palavras vizinhas se sobreponham.
                word_width = max(0.0, float(word.get("x1", 0)) - float(word.get("x0", 0)))
                color = css_color(word.get("non_stroking_color"), "#111")
                style = f"left:{n(word['x0'])}px;top:{n(word['top'])}px;font-size:{n(word.get('size', 10))}px;font-family:'{font}',Arial,sans-serif;color:{color}"
                elements.append(f'<span class="pdf-text" data-w="{n(word_width)}" style="{style}">{html.escape(word["text"])}</span>')
            pages_html.append(
                f'<div class="pdf-page-shell" id="page-{page_no}" data-page="{page_no}" '
                f'data-page-width="{n(page_width)}" data-page-height="{n(page_height)}" '
                f'style="--page-width:{n(page_width)};--page-height:{n(page_height)};'
                f'--page-width-px:{n(page_width)}px;--page-height-px:{n(page_height)}px">'
                f'<section class="pdf-page" data-page="{page_no}" style="width:{n(page_width)}px;height:{n(page_height)}px">'
                f'{"".join(elements)}</section></div>'
            )

    neural_tables: list[dict[str, Any]] = []
    if table_detector:
        LOGGER.info("Iniciando detecção neural de tabelas integrada")
        try:
            neural_tables = table_detector.detect(pdf_path)
            LOGGER.info("Detecção neural integrada concluída: %d tabelas", len(neural_tables))
        except Exception:
            LOGGER.exception("Falha na detecção neural integrada")
            pass

    if neural_tables:
        pages_with_tables: dict[int, list[dict[str, Any]]] = {}
        for table in neural_tables:
            try:
                p = int(table["page"])
                if p >= 1:
                    pages_with_tables.setdefault(p, []).append(table)
            except (KeyError, ValueError, TypeError):
                continue

        for p, p_tables in pages_with_tables.items():
            if p > len(pages_html):
                continue
            overlays = []
            for table in p_tables:
                confidence = float(table.get("confidence", 0))
                rows = int(table.get("row_count", 0))
                cols = int(table.get("column_count", 0))
                label = f"Tabela neural {confidence:.0%}, {rows} linhas, {cols} colunas"
                table_id = html.escape(str(table.get("id", "neural-table")), quote=True)
                rendered_lines = []
                for line_index, line in enumerate(table.get("lines", []), 1):
                    try:
                        lx, ly = float(line["x"]), float(line["y"])
                        lw, lh = float(line.get("width", 0)), float(line.get("height", 0))
                        line_thickness = max(.25, float(line.get("line_width", .5)))
                    except (KeyError, TypeError, ValueError):
                        continue
                    color = str(line.get("color", "#000000"))
                    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color) or not all(math.isfinite(v) for v in (lx, ly, lw, lh, line_thickness)):
                        continue
                    # No PDF a espessura cresce a partir do centro do traco; o div
                    # cresce a partir do topo/esquerda, entao recua metade da espessura.
                    css_w = lw if lw > 0 else line_thickness
                    css_h = lh if lh > 0 else line_thickness
                    css_x = lx if lw > 0 else lx - line_thickness / 2
                    css_y = ly if lh > 0 else ly - line_thickness / 2
                    rendered_lines.append(
                        f'<div class="neural-table-line" data-neural-line="{line_index}" '
                        f'style="left:{css_x:.2f}px;top:{css_y:.2f}px;width:{css_w:.2f}px;'
                        f'height:{css_h:.2f}px;background:{color}"></div>'
                    )
                overlays.append(
                    f'<div class="neural-table-structure" data-neural-table="{table_id}" '
                    f'aria-label="{html.escape(label, quote=True)}" title="{html.escape(label, quote=True)}">'
                    f'{"".join(rendered_lines)}</div>'
                )
            
            marker = f' data-page="{p}"'
            page_html = pages_html[p-1]
            insert_at = page_html.find("</section>")
            if insert_at > 0:
                pages_html[p-1] = page_html[:insert_at] + "".join(overlays) + page_html[insert_at:]

    title = html.escape(pdf_path.stem)
    document = f'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
:root{{--page-shadow:0 2px 18px #0002}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:#e8ebef;font-family:Arial,sans-serif}}
.document{{padding:24px;display:flex;flex-direction:column;align-items:center;gap:24px;width:100%}}
.pdf-page-shell{{position:relative;width:100%;aspect-ratio:var(--page-width) / var(--page-height)}}
.pdf-page{{position:absolute;inset:0;overflow:hidden;background:white;box-shadow:var(--page-shadow);transform:scale(var(--page-scale,1));transform-origin:top left}}
.pdf-text,.pdf-image,.pdf-line,.pdf-rect,.pdf-vector{{position:absolute}}.pdf-text{{white-space:pre;line-height:1;transform-origin:top left;color:#111}}.pdf-vector{{inset:0;width:100%;height:100%;pointer-events:none}}
.pdf-line{{border-top:1px solid #111;pointer-events:none}}.pdf-rect{{border:1px solid #111;pointer-events:none}}.pdf-image{{object-fit:fill}}
.pdf-field{{position:absolute;z-index:25;border:1px solid rgba(255,0,0,0.2);background:rgba(255,0,0,0.05);scroll-margin-top:24px}}
.pdf-field:hover{{border-color:#ff4444;background:rgba(255,0,0,0.1);cursor:pointer}}
.pdf-field:target{{border-color:#ff4444;background:rgba(255,0,0,0.15);box-shadow:0 0 0 2px #ff444433}}
.pdf-table{{position:absolute;border-collapse:collapse;z-index:20}}.pdf-table td{{border:1px solid transparent;padding:0;vertical-align:top;color:transparent;user-select:none}}
.neural-table-structure{{display:contents}}.neural-table-line{{position:absolute;z-index:30;pointer-events:none}}
@media print{{body{{background:#fff}}.document{{padding:0;gap:0}}.pdf-page-shell{{width:var(--page-width-px);max-width:none;height:var(--page-height-px);aspect-ratio:auto;break-after:page}}.pdf-page{{--page-scale:1;box-shadow:none}}}}
</style></head><body><main class="document">{"".join(pages_html)}</main><script>
const resizePages=()=>document.querySelectorAll('.pdf-page-shell').forEach(shell=>{{
  const width=Number(shell.dataset.pageWidth);
  const page=shell.querySelector('.pdf-page');
  // clientWidth rounds fractional PDF dimensions (for example 842.5 to 843),
  // which can make landscape pages slightly larger than their shell and clip
  // the right/bottom edges. DOMRect preserves the subpixel width.
  const renderedWidth=shell.getBoundingClientRect().width;
  page.style.setProperty('--page-scale',String(renderedWidth/width));
}});
new ResizeObserver(resizePages).observe(document.querySelector('.document'));
resizePages();
// Comprime/expande cada palavra para a largura que ela tinha no PDF: a fonte
// substituta raramente tem as mesmas metricas e, sem isso, palavras vizinhas
// se encostam. A razao e independente do zoom, entao roda uma unica vez.
const fitText=()=>document.querySelectorAll('.pdf-page-shell').forEach(shell=>{{
  const pageWidth=Number(shell.dataset.pageWidth);
  const page=shell.querySelector('.pdf-page');
  const scale=page.getBoundingClientRect().width/pageWidth;
  if(!scale)return;
  shell.querySelectorAll('.pdf-text[data-w]').forEach(el=>{{
    el.style.transform='';
    const target=Number(el.dataset.w);
    const actual=el.getBoundingClientRect().width/scale;
    if(!(target>0&&actual>0))return;
    const ratio=target/actual;
    if(Math.abs(ratio-1)>0.02)el.style.transform=`scaleX(${{ratio.toFixed(4)}})`;
  }});
}});
document.fonts.ready.then(fitText);
</script></body></html>'''
    fields = [asdict(field) for field in all_fields]
    result = ConversionResult(document, fields, all_tables, page_sizes, neural_tables)
    if output is None:
        LOGGER.info("Conversão de %s concluída em memoria", pdf_path.name)
        return result

    (output / "index.html").write_text(result.html_content, encoding="utf-8")
    (output / "fields.json").write_text(json.dumps(result.fields, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "tables.json").write_text(json.dumps(result.tables, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "pages.json").write_text(json.dumps(result.pages, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "neural-tables.json").write_text(json.dumps(result.neural_tables, ensure_ascii=False, indent=2), encoding="utf-8")
    LOGGER.info("Conversão de %s concluída. Resultados salvos em %s", pdf_path.name, output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Converte PDF em HTML fiel e extrai o mapeamento de campos em JSON")
    parser.add_argument("pdf")
    parser.add_argument("-o", "--output", default="output/pdf-html")
    parser.add_argument("-m", "--model", help="Caminho para o modelo de deteccao de tabelas neurais")
    args = parser.parse_args()

    table_detector = None
    if args.model:
        from backend.app.ml.tables import TableDetector
        table_detector = TableDetector(Path(args.model))

    result = convert(args.pdf, args.output, table_detector=table_detector)
    print(result / "index.html")
