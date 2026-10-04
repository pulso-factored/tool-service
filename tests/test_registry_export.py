"""The registry yamls shipped with the service say what the catalog says (and stay in agent-core's subset)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _script():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("export_registry", ROOT / "scripts" / "export_registry.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_registry_yamls_are_current() -> None:
    assert _script().main(["--check"]) == 0


def test_the_registry_schema_keeps_only_the_closed_subset() -> None:
    from tool_service.tools import CATALOG

    export = _script()
    allowed = export.SUPPORTED | export.ANNOTATIONS

    def keys(schema: dict[str, object]) -> set[str]:
        found = set(schema)
        for child in dict(schema.get("properties", {})).values():  # type: ignore[call-overload]
            found |= keys(child)
        return found

    for spec in CATALOG.values():
        assert keys(export.registry_schema(spec.args_schema)) <= allowed
