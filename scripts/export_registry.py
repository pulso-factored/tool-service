"""Writes ``registry/tools/<id>@<version>.yaml`` (the ``ToolDef`` agent-core's registry pins) from the catalog.

``uv run python scripts/export_registry.py`` regenerates them; ``--check`` fails if they drifted (CI).
The service implements a tool by name; the registry owns its risk, auth level, idempotence and read-back,
so the two must say the same thing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from tool_service.tools import CATALOG, ToolSpec

OUT = Path(__file__).resolve().parents[1] / "registry" / "tools"

# agent-core's registry accepts a closed JSON-Schema subset (domain/schema.py): anything else fails validation.
# The service keeps the stricter constraints (ranges, lengths, formats) and enforces them itself.
SUPPORTED = {"type", "enum", "properties", "required", "additionalProperties", "items"}
ANNOTATIONS = {"description", "title", "default", "examples"}


def registry_schema(schema: dict[str, object]) -> dict[str, object]:
    kept: dict[str, object] = {}
    for key, value in schema.items():
        if key not in SUPPORTED and key not in ANNOTATIONS:
            continue
        if key == "properties" and isinstance(value, dict):
            kept[key] = {name: registry_schema(child) for name, child in value.items()}
        elif key == "items" and isinstance(value, dict):
            kept[key] = registry_schema(value)
        else:
            kept[key] = value
    return kept


def render(spec: ToolSpec) -> str:
    doc: dict[str, object] = {
        "id": spec.id, "version": spec.version, "risk_class": spec.risk_class,
        "min_auth_level": spec.min_auth_level, "idempotent": spec.idempotent}
    if spec.readback_by:
        doc["readback_by"] = spec.readback_by
    if spec.source:
        doc["source"] = spec.source
    doc["description"] = spec.description
    doc["args_schema"] = registry_schema(spec.args_schema)
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=110)


def main(argv: list[str]) -> int:
    expected = {f"{s.id}@{s.version}.yaml": render(s) for s in CATALOG.values()}
    if "--check" in argv:
        found = {p.name: p.read_text(encoding="utf-8") for p in OUT.glob("*.yaml")}
        if found != expected:
            print("registry/tools está desactualizado: corre scripts/export_registry.py")
            return 1
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.yaml"):
        stale.unlink()
    for name, text in expected.items():
        (OUT / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"{len(expected)} tools en {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
