"""Refreshes (or checks) ``contracts/read-model-contract.json`` from a data-pipeline publication.

    python scripts/sync_contract.py --from <data dir>            # copy the latest publication's contract
    python scripts/sync_contract.py --from <data dir> --check     # fail if the pin drifted (ignores run_id)

The copy is reviewed like code: a diff here means the pipeline changed what a read-model contains or means, and the
tests in tests/test_read_model_contract.py say which tool has to change.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PIN = Path(__file__).resolve().parents[1] / "contracts" / "read-model-contract.json"


def load_latest(data_dir: Path) -> dict[str, object]:
    run = json.loads((data_dir / "publish" / "latest.json").read_text(encoding="utf-8"))["run_id"]
    return json.loads((data_dir / "publish" / run / "read_model_contract.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="source", required=True, type=Path, help="data dir holding publish/latest.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    live = load_latest(args.source)
    if args.check:
        pinned = json.loads(PIN.read_text(encoding="utf-8"))
        same = {k: v for k, v in live.items() if k != "run_id"} == {k: v for k, v in pinned.items() if k != "run_id"}
        print("the pinned contract is current" if same else "the pinned contract DRIFTED from the publication")
        return 0 if same else 1
    PIN.write_text(json.dumps(live, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"pinned contract {live['contract_version']} from run {live['run_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
