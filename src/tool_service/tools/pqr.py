"""Filing a PQR (write) and reading it back (ADR 0007: confirm, act, verify; idempotent by the action id)."""

from __future__ import annotations

from typing import Any

from tool_service.contract import ExecuteRequest
from tool_service.tools.base import Env, Outcome, ToolSpec, closed, rows


def radicar_pqr(env: Env, customer_id: str, args: dict[str, Any], request: ExecuteRequest) -> Outcome:
    key = request.idempotency_key
    if not key:  # the engine always sends one; a write without it cannot be replayed or read back
        return Outcome.denied("idempotency_key_required", "una escritura lleva idempotency_key")
    if request.context.principal.type != "customer":  # advisors and the copilot only look and suggest
        return Outcome.denied("write_not_allowed", "solo el cliente radica su PQR")
    belongs = rows(env.cursor(),
                   "SELECT 1 AS ok FROM customer_transactions WHERE customer_id = ? AND transaction_id = ? LIMIT 1",
                   [customer_id, args["transaction_id"]])
    existing = env.store.get(key, customer_id)
    if not belongs and existing is None:  # a replay of a filed PQR does not depend on the data version
        return Outcome.denied("transaction_not_found", "el movimiento no es del cliente")
    pqr = existing or env.store.file(key, customer_id, args["transaction_id"], args["descripcion"].strip())
    if pqr is None:
        return Outcome.denied("idempotency_key_in_use", "la clave de idempotencia ya se usó")
    return Outcome.ok(_view(pqr.pqr_id, pqr.status, pqr.transaction_id, pqr.description, pqr.filed_at))


def obtener_pqr(env: Env, customer_id: str, args: dict[str, Any], request: ExecuteRequest) -> Outcome:
    """Read-back of ``radicar_pqr`` by the same idempotency key; ``None`` if nothing was filed for the caller."""
    pqr = env.store.get(args["idempotency_key"], customer_id)
    if pqr is None:
        return Outcome.ok(None)
    return Outcome.ok(_view(pqr.pqr_id, pqr.status, pqr.transaction_id, pqr.description, pqr.filed_at))


def _view(pqr_id: str, status: str, transaction_id: str, description: str, filed_at: Any) -> dict[str, Any]:
    return {"id": pqr_id, "status": status, "transaction_id": transaction_id, "description": description,
            "filed_at": filed_at}


WRITE_TOOLS = (
    ToolSpec(
        id="radicar_pqr", source="customer_cases", handler=radicar_pqr, risk_class="write_reversible",
        min_auth_level="step_up", readback_by="idempotency_key",
        description="Radica una PQR de disputa por un movimiento del cliente atendido (requiere confirmación).",
        args_schema=closed({"transaction_id": {"type": "string", "minLength": 1, "maxLength": 64},
                            "descripcion": {"type": "string", "minLength": 1, "maxLength": 2000}},
                           ["transaction_id", "descripcion"])),
    ToolSpec(
        id="obtener_pqr", source="customer_cases", handler=obtener_pqr,
        description="Lee la PQR radicada con una clave de idempotencia (verificación de radicar_pqr).",
        args_schema=closed({"idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128}},
                           ["idempotency_key"])),
)
