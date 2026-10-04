"""The service's hand-written column lists against data-pipeline's read-model contract.

The tools select a curated subset of columns by name. data-pipeline publishes, with every run, a
``read_model_contract.json`` that says which columns exist, what a NULL means and which flag columns go with a value
(``related_flags``). Two hand-maintained descriptions of the same tables will drift, and one did: the service returned
``credit_limit`` and ``amount_usd`` without the flags that say whether a NULL is "not applicable" or "unknown" and
whether an amount is exact or derived. These tests make that drift fail here instead of in a customer's answer.

``contracts/read-model-contract.json`` is a pinned copy (refresh it with ``scripts/sync_contract.py``). When a real
publication is available (``TOOL_CONTRACT_DATA_DIR``) one test also compares the pin against it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from tool_service.tools import CATALOG, read

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "contracts" / "read-model-contract.json"
CONTRACT: dict[str, Any] = json.loads(PIN.read_text(encoding="utf-8"))
TABLES: dict[str, Any] = CONTRACT["zones"]["restricted"]["tables"]

SELECTED = {
    "customer_products": read.PRODUCT_COLUMNS,
    "customer_transactions": read.TRANSACTION_COLUMNS,
    "customer_profile": read.PROFILE_COLUMNS,
    "customer_cases": read.CASE_COLUMNS,
}

# (table, column, flag) a tool leaves out ON PURPOSE, with the reason. Empty today: add an entry, with its reason,
# instead of silently dropping a flag. A flag changes how the value next to it must be read.
INTENTIONALLY_OMITTED: dict[tuple[str, str, str], str] = {}

# Columns the service returns although the contract classifies them as direct identifiers: agent-core's
# FieldClassifier decides what the model sees (see README), so returning them is the design, not a leak.
# Adding a column to a read tool is a decision: this list makes it visible.
KNOWN_DIRECT_IDENTIFIERS = {
    ("customer_products", "product_number"),
    ("customer_profile", "customer_id"),
    ("customer_profile", "first_name"),
    ("customer_profile", "last_name"),
}


def columns(text: str) -> list[str]:
    return [c.strip() for c in text.split(",")]


def test_the_pinned_contract_is_a_known_version() -> None:
    assert CONTRACT["contract_version"].split(".")[0] == "1", "a new major version needs a review of every tool"
    assert CONTRACT["as_of"], "the cut-off date of the data travels with the contract"


@pytest.mark.parametrize("table", sorted(SELECTED))
def test_every_selected_column_exists_in_the_published_read_model(table: str) -> None:
    published = set(TABLES[table]["columns"])
    missing = [c for c in columns(SELECTED[table]) if c not in published]
    assert not missing, f"{table}: the service selects columns the pipeline does not publish: {missing}"


@pytest.mark.parametrize("table", sorted(SELECTED))
def test_a_flag_that_changes_how_a_value_is_read_is_never_dropped(table: str) -> None:
    selected = set(columns(SELECTED[table]))
    dropped = [
        f"{col} -> {flag}"
        for col in sorted(selected)
        for flag in TABLES[table]["columns"][col].get("related_flags", [])
        if flag not in selected and (table, col, flag) not in INTENTIONALLY_OMITTED
    ]
    assert not dropped, (
        f"{table}: a value is returned without the flag that says how to read it: {dropped}. "
        "Return the flag, or list it in INTENTIONALLY_OMITTED with the reason."
    )


def test_the_omissions_list_does_not_rot() -> None:
    for table, col, flag in INTENTIONALLY_OMITTED:
        assert flag in TABLES[table]["columns"][col].get("related_flags", []), "stale entry: the contract changed"
        assert flag not in columns(SELECTED[table]), "stale entry: the flag is returned now"


def test_every_read_tool_source_is_a_published_read_model_with_the_customer_as_subject() -> None:
    for spec in CATALOG.values():
        if spec.source is None:
            continue
        assert spec.source in TABLES, f"{spec.id}: source {spec.source!r} is not a published read-model"
        assert TABLES[spec.source]["subject_column"] == "customer_id", "the queries filter by customer_id"


def test_returning_a_direct_identifier_is_a_visible_decision() -> None:
    returned = {
        (table, col)
        for table, selected in SELECTED.items()
        for col in columns(selected)
        if TABLES[table]["columns"][col].get("class") == "pii_direct"
    }
    unexpected = sorted(returned - KNOWN_DIRECT_IDENTIFIERS)
    assert not unexpected, f"new direct identifiers returned by a tool: {unexpected}; confirm it is intended"
    assert not (KNOWN_DIRECT_IDENTIFIERS - returned), "KNOWN_DIRECT_IDENTIFIERS has a stale entry"


@pytest.mark.skipif(not os.environ.get("TOOL_CONTRACT_DATA_DIR"), reason="needs a real publication (TOOL_CONTRACT_DATA_DIR)")
def test_the_pin_matches_the_current_publication() -> None:
    data_dir = Path(os.environ["TOOL_CONTRACT_DATA_DIR"])
    run = json.loads((data_dir / "publish" / "latest.json").read_text(encoding="utf-8"))["run_id"]
    live = json.loads((data_dir / "publish" / run / "read_model_contract.json").read_text(encoding="utf-8"))
    live.pop("run_id")
    pinned = {k: v for k, v in CONTRACT.items() if k != "run_id"}
    assert live == pinned, "the pipeline's contract changed: run scripts/sync_contract.py and review the diff"
