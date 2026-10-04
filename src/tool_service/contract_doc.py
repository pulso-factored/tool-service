"""The provider contract as an OpenAPI 3.1 document, generated from the models in ``contract.py``.

It is **provider-neutral**: it describes what any service that exposes tools to agent-core implements
(``POST /v1/tools/{id}/execute`` and ``GET /v1/tools``), not this service's health checks. The consumer
(agent-core's ``HttpToolExecutor``) pins a copy and tests against it; this service tests that it conforms.
"""

from __future__ import annotations

from typing import Any

from pydantic.json_schema import models_json_schema

from tool_service.contract import (
    CONTRACT_VERSION,
    ExecuteRequest,
    ExecuteResponse,
    Status,
    ToolList,
)

_REF = "#/components/schemas/"

_EXECUTE = """\
Runs one tool for one caller.

* `args` is written by the model and never carries the subject. The customer the data is about comes from
  `bound_params` and the verified claims in `context` (a `customer` principal's own id; an `advisor`'s
  delegation `on_behalf_of`). Every source present must agree, otherwise the answer is `denied`.
* Reads answer `ok | error | timeout | denied | step_up_required`. Writes answer
  `ok | denied | uncertain | step_up_required` and never `error`: a write either refused before any effect
  (`denied`) or may have happened (`uncertain`). A consumer treats an unreachable provider on a write as
  `uncertain`.
* A write carries `idempotency_key` (the engine's action id): a replay returns the first result, and the
  tool's read-back (`readback_by: idempotency_key` in its ToolDef) finds what was written.
* `step_up_required` is answered before any effect when `context.principal.auth_level` is below the tool's
  `min_auth_level` (declared in the registry's ToolDef).
* Numbers keep their scale: amounts are JSON numbers (`1342.80`), never strings or floats rounded by the
  provider.
* HTTP statuses: `200` for every tool outcome (including `denied`), `401` for a missing or wrong consumer
  token, `404` for an unknown tool, `422` for a body that is not an `ExecuteRequest`.
"""


def contract_document() -> dict[str, Any]:
    _, definitions = models_json_schema(
        [(ExecuteRequest, "validation"), (ExecuteResponse, "serialization"), (ToolList, "serialization")],
        ref_template=_REF + "{model}",
    )
    schemas: dict[str, Any] = definitions.get("$defs", {})
    schemas["Status"] = {"type": "string", "enum": [s.value for s in Status]}
    execute_response = {"$ref": _REF + "ExecuteResponse"}
    json_response = {"application/json": {"schema": execute_response}}
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Tool provider contract",
            "version": CONTRACT_VERSION,
            "description": "What a service implements to expose tools to agent-core.",
        },
        "paths": {
            "/v1/tools/{tool_id}/execute": {
                "post": {
                    "operationId": "executeTool",
                    "summary": "Run one tool",
                    "description": _EXECUTE,
                    "security": [{"bearer": []}],
                    "parameters": [{"name": "tool_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {"$ref": _REF + "ExecuteRequest"}}},
                    },
                    "responses": {
                        "200": {"description": "A tool outcome, whatever its status", "content": json_response},
                        "401": {"description": "Missing or wrong consumer token"},
                        "404": {"description": "Unknown tool", "content": json_response},
                        "422": {"description": "The body is not an ExecuteRequest", "content": json_response},
                    },
                }
            },
            "/v1/tools": {
                "get": {
                    "operationId": "listTools",
                    "summary": "The tools this provider implements, with their declarations",
                    "security": [{"bearer": []}],
                    "responses": {
                        "200": {
                            "description": "The catalog",
                            "content": {"application/json": {"schema": {"$ref": _REF + "ToolList"}}},
                        },
                        "401": {"description": "Missing or wrong consumer token"},
                    },
                }
            },
        },
        "components": {
            "schemas": dict(sorted(schemas.items())),
            "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
        },
    }
