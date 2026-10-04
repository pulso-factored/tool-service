"""The tools over the synthetic dataset, through the HTTP contract."""

from __future__ import annotations

from decimal import Decimal

from tests.conftest import NATALIA, OTHER, Call


def test_products_come_newest_first_with_exact_decimals_and_only_curated_columns(call: Call) -> None:
    response = call("leer_productos")

    body = response.json()
    assert response.status_code == 200 and body["status"] == "ok"
    assert body["source"] == "customer_products" and body["dataset_run_id"] == "run-1"
    assert [p["product_id"] for p in body["result"]] == ["PRD-2", "PRD-1"]
    assert b'"current_balance":1342.80' in response.content  # a number with its scale, not "1342.8"
    assert "customer_id" not in body["result"][0]


def test_movements_are_latest_first_and_leave_internal_scores_out(call: Call) -> None:
    body = call("leer_movimientos", {"limite": 2}).json()

    assert [t["transaction_id"] for t in body["result"]] == ["TX-2", "TX-1"]
    assert not {"is_fraud", "fraud_score", "response_code", "product_quarantined", "customer_id"} & set(
        body["result"][0])


def test_the_default_limit_applies_and_the_maximum_is_enforced(call: Call) -> None:
    assert len(call("leer_movimientos").json()["result"]) == 4
    over = call("leer_movimientos", {"limite": 51}).json()
    assert over["status"] == "error" and over["error"]["kind"] == "invalid_args"


def test_search_filters_by_text_dates_and_amount_with_literal_wildcards(call: Call) -> None:
    def ids(**args: object) -> list[str]:
        return [t["transaction_id"] for t in call("buscar_transacciones", args).json()["result"]]

    assert ids(texto="cafe") == ["TX-2"]
    assert ids(texto="restaurants") == ["TX-2", "TX-3"]
    assert ids(desde="2026-09-01", hasta="2026-09-27") == ["TX-1", "TX-4"]
    assert ids(monto_min=100) == ["TX-1", "TX-4"]
    assert ids(texto="%") == []  # a wildcard is a literal character, not "everything"
    assert ids(texto="_") == []


def test_search_never_returns_another_customers_rows(call: Call) -> None:
    ids = [t["transaction_id"] for t in call("buscar_transacciones", {"texto": "aurora"}).json()["result"]]

    assert ids == ["TX-1"]  # TX-9 is also "Tienda Aurora" but belongs to someone else


def test_profile_returns_the_curated_fields(call: Call) -> None:
    result = call("leer_perfil").json()["result"]

    assert result["first_name"] == "Natalia" and result["customer_id"] == NATALIA
    assert "credit_score" not in result and "email" not in result and "document_number" not in result


def test_cases_list_the_datasets_and_the_filed_pqrs_together(call: Call) -> None:
    call("radicar_pqr", {"transaction_id": "TX-4", "descripcion": "No reconozco este cargo"},
         key="action-1", level="step_up")

    rows = call("leer_pqr_cliente").json()["result"]

    assert [r["case_id"] for r in rows][1:] == ["CASE-1"]
    assert rows[0]["case_id"].startswith("PQR-") and rows[0]["complaint_status"] == "Open"
    assert "assigned_analyst_id" not in rows[0] and "csat" not in rows[1]


def test_filing_is_idempotent_and_the_readback_finds_it(call: Call) -> None:
    args = {"transaction_id": "TX-4", "descripcion": "No reconozco este cargo"}
    first = call("radicar_pqr", args, key="action-1", level="step_up").json()
    again = call("radicar_pqr", args, key="action-1", level="step_up").json()
    read = call("obtener_pqr", {"idempotency_key": "action-1"}).json()

    assert first["status"] == "ok" and first["result"]["status"] == "Open"
    assert again["result"]["id"] == first["result"]["id"] == read["result"]["id"]
    assert read["result"]["transaction_id"] == "TX-4"
    assert len(call("leer_pqr_cliente").json()["result"]) == 2  # filed once, not twice


def test_the_readback_of_an_unknown_key_is_ok_and_empty(call: Call) -> None:
    body = call("obtener_pqr", {"idempotency_key": "nunca"}).json()

    assert body["status"] == "ok" and body["result"] is None


def test_a_filing_needs_step_up_and_a_key_and_the_customers_own_transaction(call: Call) -> None:
    args = {"transaction_id": "TX-4", "descripcion": "No reconozco este cargo"}

    assert call("radicar_pqr", args, key="k", level="session").json()["status"] == "step_up_required"
    assert call("radicar_pqr", args, level="step_up").json()["error"]["kind"] == "idempotency_key_required"
    foreign = call("radicar_pqr", {**args, "transaction_id": "TX-9"}, key="k2", level="step_up").json()
    assert foreign["status"] == "denied" and foreign["error"]["kind"] == "transaction_not_found"
    assert call("obtener_pqr", {"idempotency_key": "k"}).json()["result"] is None  # nothing was filed


def test_a_write_with_bad_args_is_denied_never_error(call: Call) -> None:
    body = call("radicar_pqr", {"transaction_id": "TX-4"}, key="k", level="step_up").json()

    assert body["status"] == "denied" and body["error"]["kind"] == "invalid_args"


def test_another_customer_cannot_read_back_or_collide_with_a_key(call: Call) -> None:
    args = {"transaction_id": "TX-4", "descripcion": "No reconozco este cargo"}
    call("radicar_pqr", args, key="shared", level="step_up")

    read = call("obtener_pqr", {"idempotency_key": "shared"}, pid=OTHER).json()
    clash = call("radicar_pqr", {"transaction_id": "TX-9", "descripcion": "x"}, key="shared",
                 pid=OTHER, level="step_up").json()

    assert read["result"] is None
    assert clash["status"] == "denied" and clash["error"]["kind"] == "idempotency_key_in_use"


def test_decimals_are_never_floats_on_the_wire(call: Call) -> None:
    result = call("leer_movimientos").json(parse_float=Decimal)["result"]

    assert {t["amount"] for t in result} == {Decimal("120.50"), Decimal("8.75"), Decimal("64.20"),
                                             Decimal("640.00")}
