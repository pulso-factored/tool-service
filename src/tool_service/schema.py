"""The closed JSON-Schema subset the tools declare (the same subset agent-core's registry accepts):
``object`` with typed ``properties``, ``required`` and ``additionalProperties: false``. Messages name the
argument, never its value (values can be personal data)."""

from __future__ import annotations

import datetime as dt
from typing import Any


def validate(args: dict[str, Any], schema: dict[str, Any]) -> str | None:
    properties: dict[str, dict[str, Any]] = schema.get("properties", {})
    for name in args:
        if name not in properties:
            return f"argumento desconocido: {name}"
    for name in schema.get("required", []):
        if name not in args:
            return f"falta el argumento: {name}"
    for name, value in args.items():
        problem = _check(name, value, properties[name])
        if problem:
            return problem
    return None


def _check(name: str, value: Any, spec: dict[str, Any]) -> str | None:
    kind = spec.get("type")
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{name} debe ser un entero"
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) and not _is_decimal(value):
            return f"{name} debe ser un número"
    elif kind == "string":
        if not isinstance(value, str):
            return f"{name} debe ser texto"
        if len(value) > spec.get("maxLength", 10_000):
            return f"{name} es demasiado largo"
        if len(value.strip()) < spec.get("minLength", 0):
            return f"{name} es demasiado corto"
        if spec.get("format") == "date" and not _is_date(value):
            return f"{name} debe ser una fecha AAAA-MM-DD"
    else:
        return f"{name}: tipo no soportado"
    if kind in ("integer", "number"):
        if "minimum" in spec and value < spec["minimum"]:
            return f"{name} es menor que el mínimo"
        if "maximum" in spec and value > spec["maximum"]:
            return f"{name} es mayor que el máximo"
    return None


def _is_decimal(value: Any) -> bool:
    from decimal import Decimal

    return isinstance(value, Decimal)


def _is_date(value: str) -> bool:
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True
