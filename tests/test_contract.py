"""The service conforms to the provider contract it publishes (and the pinned files are current)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from tests.conftest import TOKEN, Call, context
from tool_service.contract import CONTRACT_VERSION, Status
from tool_service.contract_doc import contract_document

ROOT = Path(__file__).resolve().parents[1]
DOC = json.loads((ROOT / "contracts" / "tool-provider.openapi.json").read_text(encoding="utf-8"))


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"#/components/schemas/{name}", "components": DOC["components"]})


def test_the_pinned_contract_files_are_current() -> None:
    spec = importlib.util.spec_from_file_location("export_contract", ROOT / "scripts" / "export_contract.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.main(["--check"]) == 0
    assert contract_document() == DOC
    assert DOC["info"]["version"] == CONTRACT_VERSION
    assert (ROOT / "contracts" / "tool-provider-version.txt").read_text().strip() == CONTRACT_VERSION


def test_the_statuses_in_the_contract_are_the_six_the_engine_knows() -> None:
    declared = set(DOC["components"]["schemas"]["Status"]["enum"])

    assert declared == {s.value for s in Status}
    assert declared == {"ok", "error", "timeout", "denied", "uncertain", "step_up_required"}


def test_a_request_as_the_consumer_builds_it_validates() -> None:
    request = {"tool": "leer_productos@1.0.0", "args": {"limite": 3}, "bound_params": {"customer_id": "CLI-1"},
               "context": context(), "idempotency_key": None}
    advisor = {**request, "context": context(principal="advisor", pid="adv-7", grant_for="CLI-1")}

    for body in (request, advisor):
        assert not list(_validator("ExecuteRequest").iter_errors(body))
    assert list(_validator("ExecuteRequest").iter_errors({"args": {}}))  # context is required


@pytest.mark.parametrize(("tool", "args", "extra", "status"), [
    ("leer_productos", {}, {}, "ok"),
    ("leer_productos", {"limite": 99}, {}, "error"),
    ("leer_productos", {}, {"bound": {"customer_id": "otro"}}, "denied"),
    ("radicar_pqr", {"transaction_id": "TX-4", "descripcion": "x"}, {"key": "k", "level": "session"},
     "step_up_required"),
    ("radicar_pqr", {"transaction_id": "TX-4", "descripcion": "x"}, {"key": "k", "level": "step_up"}, "ok"),
    ("radicar_pqr", {"transaction_id": "TX-4"}, {"key": "k", "level": "step_up"}, "denied"),
])
def test_every_kind_of_answer_validates_against_the_response_schema(
        call: Call, tool: str, args: dict[str, Any], extra: dict[str, Any], status: str) -> None:
    response = call(tool, args, **extra)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == status
    assert not list(_validator("ExecuteResponse").iter_errors(body))


def test_the_error_statuses_validate_too(client: TestClient) -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    unknown = client.post("/v1/tools/borrar_todo/execute", content="{}", headers=headers)
    broken = client.post("/v1/tools/leer_productos/execute", content="[1]", headers=headers)

    assert unknown.status_code == 404 and broken.status_code == 422
    for response in (unknown, broken):
        assert not list(_validator("ExecuteResponse").iter_errors(response.json()))
    assert client.post("/v1/tools/leer_productos/execute", json={}).status_code == 401


def test_the_catalog_validates_and_declares_what_the_contract_says(client: TestClient) -> None:
    body = client.get("/v1/tools", headers={"Authorization": f"Bearer {TOKEN}"}).json()

    assert not list(_validator("ToolList").iter_errors(body))
    assert {t["id"] for t in body["tools"]} >= {"leer_productos", "radicar_pqr", "obtener_pqr"}


def test_the_contract_describes_only_the_provider_routes() -> None:
    assert set(DOC["paths"]) == {"/v1/tools/{tool_id}/execute", "/v1/tools"}
