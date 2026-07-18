from __future__ import annotations

import re

# A pagina gerada por converter.py reproduz o PDF original com elementos em
# position:absolute dentro de .pdf-page, sem DPI fixo (o shell e responsivo).
# Por isso as normas abaixo sao uma camada visual aditiva e aproximada (margem
# como padding percentual, numeracao injetada, tipografia aplicada apenas ao
# texto editavel) e nao uma reformatacao metrica exata do conteudo original.
NORMS: dict[str, dict] = {
    "abnt": {
        "label": "ABNT (NBR 14724)",
        "margin": {"top": "11%", "right": "7.5%", "bottom": "7.5%", "left": "11%"},
        "font_family": "'Times New Roman', Times, serif",
        "font_size": "12pt",
        "line_height": "1.5",
        "page_number": {"top": "6%", "right": "7.5%"},
    },
    "apa": {
        "label": "APA (7th edition)",
        "margin": {"top": "10%", "right": "10%", "bottom": "10%", "left": "10%"},
        "font_family": "'Times New Roman', Times, serif",
        "font_size": "12pt",
        "line_height": "2",
        "page_number": {"top": "5%", "right": "9%"},
    },
}

_STYLE_TAG_PATTERN = re.compile(
    r'<style id="pdf-neural-format-norm">.*?</style>', re.DOTALL,
)
_PAGE_NUMBER_PATTERN = re.compile(
    r'<span class="pdf-page-number"[^>]*>.*?</span>', re.DOTALL,
)
_HTML_TAG_PATTERN = re.compile(r"<html\b[^>]*>")
_PAGE_SECTION_PATTERN = re.compile(r'(<section class="pdf-page" data-page="(\d+)"[^>]*>)')


def strip_format_norm(html_content: str) -> str:
    """Remove qualquer formatacao de norma previamente injetada (idempotente)."""
    html_content = _STYLE_TAG_PATTERN.sub("", html_content)
    html_content = _PAGE_NUMBER_PATTERN.sub("", html_content)

    def _strip_attribute(match: re.Match) -> str:
        tag = match.group(0)
        return re.sub(r'\s*data-format-norm="[^"]*"', "", tag)

    return _HTML_TAG_PATTERN.sub(_strip_attribute, html_content, count=1)


def _build_style_block(norm: str, config: dict) -> str:
    margin = config["margin"]
    page_number = config["page_number"]
    return f'''<style id="pdf-neural-format-norm">
[data-format-norm="{norm}"] .pdf-page-shell {{ padding: {margin["top"]} {margin["right"]} {margin["bottom"]} {margin["left"]}; box-sizing: border-box }}
[data-format-norm="{norm}"] .pdf-page-number {{ position: absolute; top: {page_number["top"]}; right: {page_number["right"]}; z-index: 95; font: 10pt Arial, sans-serif; color: #111 }}
[data-format-norm="{norm}"] [data-pdf-text-editable="true"],
[data-format-norm="{norm}"] .pdf-field-value {{
  font-family: {config["font_family"]};
  font-size: {config["font_size"]};
  line-height: {config["line_height"]};
  text-align: justify;
}}
</style>'''


def apply_format_norm(html_content: str, norm: str | None) -> str:
    """Aplica (ou remove, se norm for None) a formatacao visual da norma escolhida."""
    cleaned = strip_format_norm(html_content)
    if not norm:
        return cleaned
    config = NORMS.get(norm)
    if not config:
        return cleaned

    def _set_attribute(match: re.Match) -> str:
        tag = match.group(0)
        return tag[:-1] + f' data-format-norm="{norm}">'

    with_attribute = _HTML_TAG_PATTERN.sub(_set_attribute, cleaned, count=1)

    def _add_page_number(match: re.Match) -> str:
        page_number = match.group(2)
        return f'{match.group(1)}<span class="pdf-page-number">{page_number}</span>'

    with_page_numbers = _PAGE_SECTION_PATTERN.sub(_add_page_number, with_attribute)

    style_block = _build_style_block(norm, config)
    return with_page_numbers.replace("</head>", f"{style_block}</head>", 1)
