"""What a tool is: its declaration (the same facts agent-core's ``ToolDef`` pins in the registry) and a handler
that receives only validated args and the already-resolved customer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import duckdb

from tool_service.contract import ExecuteRequest, Status
from tool_service.dataset import Snapshot
from tool_service.settings import MAX_ROWS
from tool_service.store import FiledPqrStore


@dataclass(frozen=True)
class Env:
    snapshot: Snapshot
    store: FiledPqrStore

    def cursor(self) -> duckdb.DuckDBPyConnection:
        return self.snapshot.cursor()


@dataclass(frozen=True)
class Outcome:
    status: Status
    result: Any = None
    error_kind: str | None = None
    error_message: str | None = None

    @staticmethod
    def ok(result: Any) -> Outcome:
        return Outcome(Status.ok, result)

    @staticmethod
    def denied(kind: str, message: str) -> Outcome:
        return Outcome(Status.denied, None, kind, message)

    @staticmethod
    def error(kind: str, message: str) -> Outcome:
        return Outcome(Status.error, None, kind, message)


Handler = Callable[[Env, str, dict[str, Any], ExecuteRequest], Outcome]


@dataclass(frozen=True)
class ToolSpec:
    id: str
    description: str
    handler: Handler
    args_schema: dict[str, Any]
    source: str | None
    version: str = "1.0.0"
    risk_class: str = "read"
    min_auth_level: str = "session"
    idempotent: bool = True
    readback_by: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_write(self) -> bool:
        return self.risk_class not in ("read", "compute")


def limit_property(default: int = 10) -> dict[str, Any]:
    return {"type": "integer", "minimum": 1, "maximum": MAX_ROWS, "default": default}


def closed(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": properties}
    if required:
        schema["required"] = required
    return schema


def rows(cursor: duckdb.DuckDBPyConnection, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    result = cursor.execute(sql, params)
    names = [column[0] for column in result.description]
    return [dict(zip(names, row, strict=True)) for row in result.fetchall()]
