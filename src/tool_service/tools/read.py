"""Read tools over ``gold_restricted``. Every query is parameterized and filtered by the customer the caller
is allowed to see; the columns are a curated subset (no internal scores, no analyst ids). Order is explicit:
the copilot does not sort by itself, so "latest first" has to come from here. ``source`` is the table name,
which is the key the FieldClassification catalog uses, so agent-core decides what the model may see."""

from __future__ import annotations

from typing import Any

from tool_service.contract import ExecuteRequest
from tool_service.tools.base import Env, Outcome, ToolSpec, closed, limit_property, rows

PRODUCT_COLUMNS = (
    "product_id, product_type, product_number, currency, current_balance, credit_limit, interest_rate, "
    "product_status, opening_date, expiration_date, days_past_due, credit_limit_applicable, "
    "is_missing_credit_limit")
TRANSACTION_COLUMNS = (
    "transaction_id, product_id, transaction_ts, transaction_type, transaction_category, amount, currency, "
    "amount_usd, channel, merchant_name, merchant_category, transaction_country_iso2, transaction_city, "
    "transaction_status, amount_usd_source")
PROFILE_COLUMNS = (
    "customer_id, first_name, last_name, document_type, segment, customer_status, city, state, "
    "country_iso2, registration_date")
CASE_COLUMNS = (
    "case_id, opened_at, channel, topic, priority, complaint_status, is_open, claimed_amount, "
    "claimed_currency, complaint_description, closed_at, resolved, resolution_code")


def leer_productos(env: Env, customer_id: str, args: dict[str, Any], request: ExecuteRequest) -> Outcome:
    data = rows(
        env.cursor(),
        f"SELECT {PRODUCT_COLUMNS} FROM customer_products WHERE customer_id = ? "
        "ORDER BY opening_date DESC NULLS LAST, product_id LIMIT ?",
        [customer_id, args.get("limite", 20)])
    return Outcome.ok(data)


def leer_perfil(env: Env, customer_id: str, args: dict[str, Any], request: ExecuteRequest) -> Outcome:
    data = rows(env.cursor(), f"SELECT {PROFILE_COLUMNS} FROM customer_profile WHERE customer_id = ?",
                [customer_id])
    return Outcome.ok(data[0] if data else None)


def leer_movimientos(env: Env, customer_id: str, args: dict[str, Any], request: ExecuteRequest) -> Outcome:
    clauses, params = ["customer_id = ?"], [customer_id]
    if "product_id" in args:
        clauses.append("product_id = ?")
        params.append(args["product_id"])
    params.append(args.get("limite", 10))
    data = rows(
        env.cursor(),
        f"SELECT {TRANSACTION_COLUMNS} FROM customer_transactions WHERE {' AND '.join(clauses)} "
        "ORDER BY transaction_ts DESC, transaction_id LIMIT ?", params)
    return Outcome.ok(data)


def buscar_transacciones(env: Env, customer_id: str, args: dict[str, Any], request: ExecuteRequest) -> Outcome:
    clauses, params = ["customer_id = ?"], [customer_id]
    if "texto" in args:
        clauses.append("(merchant_name ILIKE ? ESCAPE '\\' OR transaction_category ILIKE ? ESCAPE '\\' "
                       "OR merchant_category ILIKE ? ESCAPE '\\')")
        pattern = "%" + _like(args["texto"]) + "%"
        params += [pattern, pattern, pattern]
    if "desde" in args:
        clauses.append("event_date >= CAST(? AS DATE)")
        params.append(args["desde"])
    if "hasta" in args:
        clauses.append("event_date <= CAST(? AS DATE)")
        params.append(args["hasta"])
    if "monto_min" in args:
        clauses.append("abs(amount) >= ?")
        params.append(args["monto_min"])
    if "monto_max" in args:
        clauses.append("abs(amount) <= ?")
        params.append(args["monto_max"])
    params.append(args.get("limite", 10))
    data = rows(
        env.cursor(),
        f"SELECT {TRANSACTION_COLUMNS} FROM customer_transactions WHERE {' AND '.join(clauses)} "
        "ORDER BY transaction_ts DESC, transaction_id LIMIT ?", params)
    return Outcome.ok(data)


def leer_pqr_cliente(env: Env, customer_id: str, args: dict[str, Any], request: ExecuteRequest) -> Outcome:
    """The dataset's cases plus the PQRs filed through this service, newest first."""
    limit = args.get("limite", 10)
    data = rows(
        env.cursor(),
        f"SELECT {CASE_COLUMNS} FROM customer_cases WHERE customer_id = ? ORDER BY opened_at DESC, case_id LIMIT ?",
        [customer_id, limit])
    filed = [pqr.as_row() for pqr in env.store.of_customer(customer_id, limit)]
    merged = sorted(filed + data, key=lambda row: str(row["opened_at"] or ""), reverse=True)
    return Outcome.ok(merged[:limit])


def _like(text: str) -> str:
    """Escapes LIKE wildcards: the model's text is a literal to look for, not a pattern."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_LIMIT = {"limite": limit_property(10)}

READ_TOOLS = (
    ToolSpec(
        id="leer_productos", source="customer_products", handler=leer_productos,
        description="Lista los productos del cliente atendido (tipo, saldo, cupo, tasa, estado, mora). "
                    "Un credit_limit nulo con credit_limit_applicable=false significa que el producto no tiene cupo "
                    "(no aplica); con credit_limit_applicable=true significa que el cupo se desconoce "
                    "(is_missing_credit_limit): no lo digas como 'sin cupo'.",
        args_schema=closed({"limite": limit_property(20)})),
    ToolSpec(
        id="leer_perfil", source="customer_profile", handler=leer_perfil,
        description="Datos básicos del cliente atendido (nombre, documento, segmento, estado, ciudad).",
        args_schema=closed({})),
    ToolSpec(
        id="leer_movimientos", source="customer_transactions", handler=leer_movimientos,
        description="Lista los últimos movimientos del cliente atendido, del más reciente al más antiguo "
                    "(monto, comercio, fecha, estado). amount_usd es aproximado cuando amount_usd_source es "
                    "'derived_fx'; 'reported' es el valor original.",
        args_schema=closed({"limite": limit_property(10), "product_id": {"type": "string", "maxLength": 64}})),
    ToolSpec(
        id="buscar_transacciones", source="customer_transactions", handler=buscar_transacciones,
        description="Busca movimientos del cliente atendido por texto (comercio o categoría), rango de fechas "
                    "o monto, del más reciente al más antiguo. amount_usd es aproximado cuando amount_usd_source "
                    "es 'derived_fx'.",
        args_schema=closed({
            "texto": {"type": "string", "minLength": 1, "maxLength": 100},
            "desde": {"type": "string", "format": "date"}, "hasta": {"type": "string", "format": "date"},
            "monto_min": {"type": "number", "minimum": 0}, "monto_max": {"type": "number", "minimum": 0},
            **_LIMIT})),
    ToolSpec(
        id="leer_pqr_cliente", source="customer_cases", handler=leer_pqr_cliente,
        description="Lista las PQR y casos del cliente atendido y su estado, del más reciente al más antiguo.",
        args_schema=closed(_LIMIT)),
)
