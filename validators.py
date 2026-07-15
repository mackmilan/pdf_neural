from __future__ import annotations

import math
import re

from auth import Identity
from config import MAX_HTML_JSON_SIZE
from formatting import NORMS

def validate_context_id(value: object, label: str) -> str:
    identifier = str(value or "").strip()
    if not re.fullmatch(r"[0-9a-f]{32}", identifier):
        raise ValueError(f"{label} invalido")
    return identifier


def validate_resource_name(value: object, label: str) -> str:
    name = str(value or "").strip()
    if not 1 <= len(name) <= 120:
        raise ValueError(f"{label} deve possuir entre 1 e 120 caracteres")
    return name


def validate_search_context(query: dict[str, list[str]], identity: Identity | None = None) -> tuple[str | None, str | None]:
    tenant_value = query.get("tenant_id", [""])[0]
    tenant_id = validate_context_id(tenant_value, "tenant_id") if tenant_value else None
    group_value = query.get("group_id", [""])[0]
    group_id = validate_context_id(group_value, "group_id") if group_value else None

    # Se não foi passado na query, tenta obter da identidade (API Key)
    if not tenant_id and identity:
        tenant_id = identity.claims.get("tenant_id")
        # Só pega o group_id da chave se o tenant_id também veio da chave (ou já era o mesmo)
        if not group_id:
            group_id = identity.claims.get("group_id")

    return tenant_id, group_id


def validate_category_query(query: dict[str, list[str]]) -> str | None:
    value = query.get("category_id", [""])[0]
    return validate_context_id(value, "category_id") if value else None


def validate_boolean(value: object, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "sim", "yes", "on"):
            return True
        if normalized in ("0", "false", "nao", "não", "no", "off"):
            return False
    raise ValueError(f"{label} deve ser booleano")


def validate_format_norm(value: object) -> str | None:
    if value in (None, ""):
        return None
    norm = str(value).strip().lower()
    if norm not in NORMS:
        raise ValueError(f"format_norm deve ser um de {sorted(NORMS)}")
    return norm


FIELD_TYPES = {"text", "date", "time", "email", "tel", "number", "password", "checkbox", "radio", "select", "textarea"}
FIELD_ALIGNS = {"left", "center", "justify", "right"}


def optional_number(value: object, label: str, index: int) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} invalido no campo {index}") from None
    if not math.isfinite(number):
        raise ValueError(f"{label} invalido no campo {index}")
    return number


def validate_fields_payload(value: object) -> list[dict]:
    """Valida e normaliza campos editados pela interface."""
    if not isinstance(value, list) or len(value) > 1000:
        raise ValueError("fields deve ser uma lista com no maximo 1000 itens")
    fields = []
    used_names = set()
    for index, raw in enumerate(value, 1):
        if not isinstance(raw, dict):
            raise ValueError(f"Campo {index} invalido")
        name = str(raw.get("name", "")).strip()[:64]
        label = str(raw.get("label", "")).strip()[:160]
        kind = str(raw.get("type", "text"))
        mask = str(raw.get("mask", "")).strip()[:80]
        align = str(raw.get("align", "left"))
        min_value = optional_number(raw.get("min"), "Valor minimo", index)
        max_value = optional_number(raw.get("max"), "Valor maximo", index)
        raw_options = raw.get("options", [])
        if not name or not re.fullmatch(r"[a-zA-Z0-9_\-]+", name) or name in used_names:
            raise ValueError(f"Nome invalido ou duplicado no campo {index}")
        if not label or kind not in FIELD_TYPES or align not in FIELD_ALIGNS:
            raise ValueError(f"Rotulo ou tipo invalido no campo {index}")
        if kind != "number" and (min_value is not None or max_value is not None):
            raise ValueError(f"Valor minimo ou maximo permitido apenas para campo numerico no campo {index}")
        if kind == "radio":
            if not isinstance(raw_options, list) or not 2 <= len(raw_options) <= 100:
                raise ValueError(f"Campo radio deve possuir entre 2 e 100 opcoes no campo {index}")
            if any(not isinstance(option, str) for option in raw_options):
                raise ValueError(f"Opcoes invalidas ou duplicadas no campo {index}")
            options = [option.strip() for option in raw_options]
            if any(not option or len(option) > 160 for option in options) or len(set(options)) != len(options):
                raise ValueError(f"Opcoes invalidas ou duplicadas no campo {index}")
        elif raw_options not in (None, []):
            raise ValueError(f"Opcoes permitidas apenas para campo radio no campo {index}")
        if min_value is not None and max_value is not None and min_value > max_value:
            raise ValueError(f"Valor minimo deve ser menor ou igual ao maximo no campo {index}")
        try:
            page = int(raw.get("page"))
            x, y = float(raw.get("x")), float(raw.get("y"))
            width, height = float(raw.get("width")), float(raw.get("height"))
        except (TypeError, ValueError):
            raise ValueError(f"Coordenadas invalidas no campo {index}") from None
        if page < 1 or not all(math.isfinite(v) for v in (x, y, width, height)):
            raise ValueError(f"Coordenadas invalidas no campo {index}")
        if x < 0 or y < 0 or width <= 0 or height <= 0 or width > 10000 or height > 10000:
            raise ValueError(f"Dimensoes invalidas no campo {index}")
        option_boxes = []
        if kind == "radio":
            raw_boxes = raw.get("option_boxes")
            if not isinstance(raw_boxes, list) or len(raw_boxes) != len(options):
                raise ValueError(f"Cada opcao radio deve possuir uma area no campo {index}")
            seen_box_values = set()
            for raw_box in raw_boxes:
                if not isinstance(raw_box, dict):
                    raise ValueError(f"Area de opcao radio invalida no campo {index}")
                value = raw_box.get("value")
                if not isinstance(value, str) or value not in options or value in seen_box_values:
                    raise ValueError(f"Area de opcao radio invalida no campo {index}")
                try:
                    box_page = int(raw_box.get("page"))
                    box_x, box_y = float(raw_box.get("x")), float(raw_box.get("y"))
                    box_width, box_height = float(raw_box.get("width")), float(raw_box.get("height"))
                except (TypeError, ValueError):
                    raise ValueError(f"Area de opcao radio invalida no campo {index}") from None
                dimensions = (box_x, box_y, box_width, box_height)
                if (box_page < 1 or not all(math.isfinite(item) for item in dimensions)
                        or box_x < 0 or box_y < 0 or box_width <= 0 or box_height <= 0
                        or box_width > 10000 or box_height > 10000):
                    raise ValueError(f"Area de opcao radio invalida no campo {index}")
                seen_box_values.add(value)
                option_boxes.append({
                    "value": value, "page": box_page, "x": box_x, "y": box_y,
                    "width": box_width, "height": box_height,
                })
        used_names.add(name)
        fields.append({
            "name": name, "label": label, "type": kind, "page": page,
            "x": x, "y": y, "width": width, "height": height,
            "source": str(raw.get("source", "manual"))[:32],
            "required": bool(raw.get("required", False)),
            "mask": mask,
            "align": align,
            "href": f"index.html#{name}",
        })
        if kind == "number":
            if min_value is not None:
                fields[-1]["min"] = min_value
            if max_value is not None:
                fields[-1]["max"] = max_value
        elif kind == "radio":
            fields[-1]["options"] = options
            fields[-1]["option_boxes"] = option_boxes
    return fields


def validate_html_payload(value: object) -> str:
    """Valida o HTML editado antes de criar uma nova versao."""
    if not isinstance(value, str):
        raise ValueError("html_content deve ser uma string")
    html_content = value.strip()
    if not html_content:
        raise ValueError("html_content nao pode ser vazio")
    if len(html_content.encode("utf-8")) > MAX_HTML_JSON_SIZE:
        raise ValueError("html_content excede o limite de 8 MB")
    if not re.search(r"<html[\s>]", html_content, re.IGNORECASE) or not re.search(r"</html\s*>", html_content, re.IGNORECASE):
        raise ValueError("html_content deve conter um documento HTML completo")
    if re.search(r"<\s*(?:iframe|object|embed)\b", html_content, re.IGNORECASE):
        raise ValueError("html_content contem elementos nao permitidos")
    for match in re.finditer(r"<script\b([^>]*)>(.*?)</script\s*>", html_content, re.IGNORECASE | re.DOTALL):
        attributes, script_body = match.group(1), match.group(2)
        normalized_script = re.sub(r"\s+", " ", script_body).strip()
        if attributes.strip() or "const resizePages=()" not in normalized_script or "ResizeObserver(resizePages)" not in normalized_script:
            raise ValueError("html_content contem scripts nao permitidos")
    return html_content


def validate_submission_values(value: object, fields: list[dict]) -> dict:
    """Valida os valores enviados pela pagina de preenchimento do documento."""
    if not isinstance(value, dict):
        raise ValueError("values deve ser um objeto")
    definitions = {field.get("name"): field for field in fields if field.get("name")}
    unknown = set(value) - set(definitions)
    if unknown:
        raise ValueError(f"Campos desconhecidos: {', '.join(sorted(unknown))}")
    normalized = {}
    for name, field in definitions.items():
        raw = value.get(name)
        kind = field.get("type", "text")
        if kind == "checkbox":
            if raw is not None and not isinstance(raw, bool):
                raise ValueError(f"O campo {name} deve ser booleano")
            result = bool(raw)
            if field.get("required") and not result:
                raise ValueError(f"O campo {name} e obrigatorio")
        elif kind == "radio":
            result = "" if raw is None else str(raw).strip()
            options = field.get("options", [])
            if result and result not in options:
                raise ValueError(f"O campo {name} deve conter uma opcao valida")
            if field.get("required") and not result:
                raise ValueError(f"O campo {name} e obrigatorio")
        elif kind == "number":
            if raw in (None, ""):
                result = None
            else:
                try:
                    result = float(raw)
                except (TypeError, ValueError):
                    raise ValueError(f"O campo {name} deve ser numerico") from None
                if not math.isfinite(result):
                    raise ValueError(f"O campo {name} deve ser numerico")
                minimum = field.get("min")
                maximum = field.get("max")
                if minimum is not None and result < float(minimum):
                    raise ValueError(f"O campo {name} deve ser maior ou igual a {minimum}")
                if maximum is not None and result > float(maximum):
                    raise ValueError(f"O campo {name} deve ser menor ou igual a {maximum}")
            if field.get("required") and result is None:
                raise ValueError(f"O campo {name} e obrigatorio")
        else:
            result = "" if raw is None else str(raw).strip()
            if len(result) > 10000:
                raise ValueError(f"O campo {name} excede o limite permitido")
            if field.get("required") and not result:
                raise ValueError(f"O campo {name} e obrigatorio")
        if name in value or field.get("required"):
            normalized[name] = result
    return normalized
