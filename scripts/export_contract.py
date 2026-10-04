"""Writes ``contracts/tool-provider.openapi.json`` (+ ``contracts/tool-provider-version.txt``) from the models.

``uv run python scripts/export_contract.py`` regenerates; ``--check`` fails if the files drifted (CI). The
consumer (agent-core) copies both files into ``tests/contracts/`` and checks its client against them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tool_service.contract import CONTRACT_VERSION
from tool_service.contract_doc import contract_document

OUT = Path(__file__).resolve().parents[1] / "contracts"
FILES = {
    "tool-provider.openapi.json": json.dumps(contract_document(), indent=2, ensure_ascii=False) + "\n",
    "tool-provider-version.txt": CONTRACT_VERSION + "\n",
}


def main(argv: list[str]) -> int:
    if "--check" in argv:
        stale = [n for n, text in FILES.items()
                 if not (OUT / n).exists() or (OUT / n).read_text(encoding="utf-8") != text]
        if stale:
            print(f"contracts/ desactualizado ({', '.join(stale)}): corre scripts/export_contract.py")
            return 1
        return 0
    OUT.mkdir(exist_ok=True)
    for name, text in FILES.items():
        (OUT / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"contrato {CONTRACT_VERSION} en {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
