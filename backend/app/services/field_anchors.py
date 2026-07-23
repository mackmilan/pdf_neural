from __future__ import annotations

import html
import re

# O converter.py grava uma ancora <a class="pdf-field"> vazia por campo dentro
# de cada <section class="pdf-page">. Quando os campos sao revisados via
# PUT /api/documents/{job_id}/fields, o html_content persistido precisa ser
# ressincronizado: sem isso, campos excluidos deixam ancoras orfas no HTML e
# campos movidos/criados ficam com geometria divergente da lista de fields.
_FIELD_ANCHOR_PATTERN = re.compile(
    r'<a\b[^>]*class="[^"]*\bpdf-field\b[^"]*"[^>]*>\s*</a>'
)
_PAGE_SECTION_PATTERN = re.compile(r'(<section class="pdf-page" data-page="(\d+)"[^>]*>)')


def _n(value: float) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def _anchor_for_field(field: dict) -> str:
    name = html.escape(str(field.get("name", "")))
    label = html.escape(str(field.get("label", "")))
    kind = html.escape(str(field.get("type", "text")))
    style = (
        f"left:{_n(field.get('x', 0))}px;top:{_n(field.get('y', 0))}px;"
        f"width:{_n(field.get('width', 1))}px;height:{_n(field.get('height', 1))}px"
    )
    return (
        f'<a href="#{name}" class="pdf-field" id="{name}" data-name="{name}" '
        f'data-type="{kind}" style="{style}" title="{label}"></a>'
    )


def sync_field_anchors(html_content: str, fields: list[dict]) -> str:
    """Regenera as ancoras .pdf-field do HTML a partir da lista atual de campos."""
    if not html_content:
        return html_content
    cleaned = _FIELD_ANCHOR_PATTERN.sub("", html_content)
    anchors_by_page: dict[str, list[str]] = {}
    for field in fields:
        try:
            page = str(int(field.get("page")))
        except (TypeError, ValueError):
            continue
        anchors_by_page.setdefault(page, []).append(_anchor_for_field(field))

    def _inject(match: re.Match) -> str:
        return match.group(1) + "".join(anchors_by_page.get(match.group(2), []))

    return _PAGE_SECTION_PATTERN.sub(_inject, cleaned)
