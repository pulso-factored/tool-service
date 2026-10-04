"""JSON out with exact decimals (``500.00`` stays ``500.00``: the engine parses numbers as ``Decimal``)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


def dumps(value: Any) -> str:
    out: list[str] = []
    _write(value, out)
    return "".join(out)


def _string(text: str) -> str:
    import json

    return json.dumps(text, ensure_ascii=False)


def _write(value: Any, out: list[str]) -> None:
    if isinstance(value, BaseModel):
        _write(value.model_dump(mode="python"), out)
    elif value is None:
        out.append("null")
    elif isinstance(value, bool):
        out.append("true" if value else "false")
    elif isinstance(value, int):
        out.append(str(value))
    elif isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("decimal no finito")
        out.append(format(value, "f"))
    elif isinstance(value, float):
        raise TypeError("los float no salen de este servicio: usa Decimal")
    elif isinstance(value, str):
        out.append(_string(value))
    elif isinstance(value, (dt.datetime, dt.date)):
        out.append(_string(value.isoformat()))
    elif isinstance(value, dict):
        out.append("{")
        for index, (key, item) in enumerate(value.items()):
            if index:
                out.append(",")
            out.append(_string(str(key)) + ":")
            _write(item, out)
        out.append("}")
    elif isinstance(value, (list, tuple)):
        out.append("[")
        for index, item in enumerate(value):
            if index:
                out.append(",")
            _write(item, out)
        out.append("]")
    else:
        raise TypeError(f"tipo no serializable: {type(value).__name__}")
