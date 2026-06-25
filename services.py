from __future__ import annotations

import html
import json
import math
import re
import tempfile
import threading
from pathlib import Path

from converter import ConversionResult, convert
from neural_field_detector import FieldDetector
from neural_table_detector import TableDetector
from config import (
    FIELD_MODEL, LOGGER, NEURAL_ENABLED, NEURAL_MIN_CONFIDENCE,
    NEURAL_THRESHOLD, TABLE_MODEL,
)

_TABLE_DETECTOR: TableDetector | None = None
_FIELD_DETECTOR: FieldDetector | None = None
_DETECTOR_LOCK = threading.Lock()

def get_detectors() -> tuple[TableDetector | None, FieldDetector | None]:
    """Carrega os modelos uma única vez."""
    global _TABLE_DETECTOR, _FIELD_DETECTOR
    if not NEURAL_ENABLED:
        return None, None
    if _TABLE_DETECTOR is None or _FIELD_DETECTOR is None:
        with _DETECTOR_LOCK:
            if _TABLE_DETECTOR is None and TABLE_MODEL.is_file():
                try:
                    _TABLE_DETECTOR = TableDetector(TABLE_MODEL, NEURAL_THRESHOLD, NEURAL_MIN_CONFIDENCE)
                    LOGGER.info("Modelo neural de tabelas carregado: %s", TABLE_MODEL)
                except Exception:
                    LOGGER.exception("Erro ao carregar detector de tabelas")

            if _FIELD_DETECTOR is None and FIELD_MODEL.is_file():
                try:
                    _FIELD_DETECTOR = FieldDetector(FIELD_MODEL)
                    LOGGER.info("Modelo neural de campos carregado: %s", FIELD_MODEL)
                except Exception:
                    LOGGER.exception("Erro ao carregar detector de campos")
    return _TABLE_DETECTOR, _FIELD_DETECTOR


def render_neural_tables(result: Path, tables: list[dict]) -> None:
    """Projeta a grade detectada nas paginas HTML usando as cores de origem."""
    if not tables:
        return
    index_file = result / "index.html"
    if not index_file.is_file():
        return
    
    pages_with_tables: dict[int, list[dict]] = {}
    for table in tables:
        try:
            p = int(table["page"])
            if p >= 1:
                pages_with_tables.setdefault(p, []).append(table)
        except (KeyError, ValueError, TypeError):
            continue

    if not pages_with_tables:
        return

    import re
    import html
    import math

    document = index_file.read_text(encoding="utf-8")
    
    for p, p_tables in pages_with_tables.items():
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
                css_w = lw if lw > 0 else line_thickness
                css_h = lh if lh > 0 else line_thickness
                rendered_lines.append(
                    f'<div class="neural-table-line" data-neural-line="{line_index}" '
                    f'style="left:{lx:.2f}px;top:{ly:.2f}px;width:{css_w:.2f}px;'
                    f'height:{css_h:.2f}px;background:{color}"></div>'
                )
            overlays.append(
                f'<div class="neural-table-structure" data-neural-table="{table_id}" '
                f'aria-label="{html.escape(label, quote=True)}" title="{html.escape(label, quote=True)}">'
                f'{"".join(rendered_lines)}</div>'
            )
        
        # Inserir no final da seção da página
        pattern = f'data-page="{p}"[^>]*>(.*?)</section>'
        match = re.search(pattern, document, re.DOTALL)
        if match:
            old_section = match.group(0)
            if "</section>" in old_section:
                new_section = old_section.replace("</section>", "".join(overlays) + "</section>")
                document = document.replace(old_section, new_section)

    index_file.write_text(document, encoding="utf-8")


def run_neural_detection(source: Path, result: Path) -> list[dict]:
    """Detecta tabelas e garante que neural-tables.json exista para o ZIP."""
    LOGGER.info("Iniciando detecção neural de tabelas: %s", source.name)
    table_detector, _ = get_detectors()
    if table_detector:
        try:
            tables = table_detector.detect(source, result / "neural-tables.json")
            LOGGER.info("Detecção neural concluída: %d tabelas encontradas", len(tables))
            return tables
        except Exception:
            LOGGER.exception("Falha na detecção neural para %s", source.name)
    
    output = result / "neural-tables.json"
    if output.is_file():
        try:
            return json.loads(output.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []
def convert_pdf_bytes(data: bytes, filename: str, job_id: str) -> ConversionResult:
    """Executa ferramentas que exigem um path em area temporaria e nao gera artefatos persistentes."""
    safe_name = Path(filename).name or "documento.pdf"
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"
    with tempfile.TemporaryDirectory(prefix="pdf-neural-") as temporary:
        source = Path(temporary) / safe_name
        source.write_bytes(data)
        table_detector, field_detector = get_detectors()
        result = convert(source, table_detector=table_detector, field_detector=field_detector, job_id=job_id)
        if not isinstance(result, ConversionResult):
            raise RuntimeError("A conversao nao retornou os artefatos em memoria")
        return result
