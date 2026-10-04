"""Who may call, who the data is about, and what happens when the dataset moves or breaks."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import NATALIA, OTHER, OTHER_TOKEN, TOKEN, Call, build_run, point
from tool_service.app import Service, create_app
from tool_service.dataset import Dataset
from tool_service.settings import ConfigError, Settings


def test_the_bearer_is_required_and_each_consumer_has_its_own(client: TestClient, call: Call) -> None:
    assert client.post("/v1/tools/leer_productos/execute", json={}).status_code == 401
    assert call("leer_productos", token="otro-token").status_code == 401
    assert call("leer_productos", token=OTHER_TOKEN).status_code == 200
    assert call("leer_productos", token=TOKEN).status_code == 200
    assert client.get("/v1/tools").status_code == 401


def test_a_customer_only_reads_its_own_data_even_if_bound_params_say_otherwise(call: Call) -> None:
    body = call("leer_productos", bound={"customer_id": OTHER}).json()

    assert body["status"] == "denied" and body["error"]["kind"] == "subject_mismatch"
    assert body["result"] is None


def test_the_subject_is_never_taken_from_args(call: Call) -> None:
    body = call("leer_productos", {"customer_id": OTHER}).json()

    assert body["status"] == "error" and body["error"]["kind"] == "invalid_args"


def test_an_advisor_reads_the_customer_of_its_delegation_and_nothing_without_one(call: Call) -> None:
    allowed = call("leer_productos", principal="advisor", pid="adv-7", grant_for=NATALIA,
                   bound={"customer_id": NATALIA}).json()
    no_grant = call("leer_productos", principal="advisor", pid="adv-7").json()
    wrong = call("leer_productos", principal="advisor", pid="adv-7", grant_for=NATALIA,
                 bound={"customer_id": OTHER}).json()

    assert allowed["status"] == "ok" and len(allowed["result"]) == 2
    assert no_grant["status"] == "denied" and no_grant["error"]["kind"] == "no_delegation"
    assert wrong["status"] == "denied" and wrong["error"]["kind"] == "subject_mismatch"


def test_an_advisor_cannot_file_a_pqr(call: Call) -> None:
    body = call("radicar_pqr", {"transaction_id": "TX-4", "descripcion": "x"}, key="k", principal="advisor",
                pid="adv-7", grant_for=NATALIA, level="step_up").json()

    assert body["status"] == "denied" and body["error"]["kind"] == "write_not_allowed"


@pytest.mark.parametrize("principal", ["builder", "service"])
def test_other_principals_have_no_data(call: Call, principal: str) -> None:
    body = call("leer_productos", principal=principal, pid="x-1").json()

    assert body["status"] == "denied" and body["error"]["kind"] == "principal_not_served"


def test_unknown_tools_and_bad_bodies_are_typed_answers(client: TestClient) -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}

    unknown = client.post("/v1/tools/borrar_todo/execute", content="{}", headers=headers)
    broken = client.post("/v1/tools/leer_productos/execute", content='{"args": 1}', headers=headers)

    assert unknown.status_code == 404 and unknown.json()["error"]["kind"] == "unknown_tool"
    assert broken.status_code == 422 and broken.json()["error"]["kind"] == "bad_request"


def test_discovery_lists_every_tool_with_its_declaration(client: TestClient) -> None:
    tools = {t["id"]: t for t in client.get("/v1/tools", headers={"Authorization": f"Bearer {TOKEN}"}).json()["tools"]}

    assert {"leer_productos", "leer_perfil", "leer_movimientos", "buscar_transacciones", "leer_pqr_cliente",
            "radicar_pqr", "obtener_pqr"} == set(tools)
    assert tools["radicar_pqr"]["risk_class"] == "write_reversible"
    assert tools["radicar_pqr"]["min_auth_level"] == "step_up"
    assert tools["leer_movimientos"]["source"] == "customer_transactions"


def test_a_new_published_run_is_picked_up_after_the_ttl(data_dir: Path, tmp_path: Path) -> None:
    clock = [0.0]
    dataset = Dataset(data_dir, ttl_s=60.0, clock=lambda: clock[0])
    assert dataset.current().run_id == "run-1"
    build_run(data_dir, "run-2")

    clock[0] = 30.0
    assert dataset.current().run_id == "run-1"  # still trusting the pointer it read
    clock[0] = 61.0
    assert dataset.current().run_id == "run-2"


def test_a_broken_pointer_or_file_is_unavailable_not_stale(settings: Settings, data_dir: Path) -> None:
    client = TestClient(create_app(service=Service(settings)))
    headers = {"Authorization": f"Bearer {TOKEN}"}
    (data_dir / "publish" / "latest.json").write_text("{not json", encoding="utf-8")

    assert client.get("/readyz").status_code == 503
    body = client.post("/v1/tools/leer_productos/execute", headers=headers, json={
        "args": {}, "bound_params": {}, "context": {"call_id": "c", "principal": {"type": "customer",
                                                                                    "id": NATALIA}}}).json()
    assert body["status"] == "error" and body["error"]["kind"] == "data_unavailable"

    point(data_dir, "run-missing")
    assert client.get("/readyz").status_code == 503
    shutil.rmtree(data_dir / "publish" / "run-1")
    assert client.get("/healthz").status_code == 200  # alive even when not ready


def test_a_pointer_cannot_lead_outside_the_data_dir(data_dir: Path) -> None:
    (data_dir / "publish" / "latest.json").write_text(
        json.dumps({"run_id": "x", "path": "../../elsewhere"}), encoding="utf-8")

    assert not Dataset(data_dir, 0.0).ready()


def test_settings_need_data_dir_and_distinct_tokens() -> None:
    ok = Settings.from_env({"TOOL_DATA_DIR": "d", "TOOL_SERVICE_TOKENS": "a:1,b:2"})
    assert set(ok.tokens) == {"a", "b"} and "1" not in repr(ok)
    for env in ({}, {"TOOL_DATA_DIR": "d"}, {"TOOL_DATA_DIR": "d", "TOOL_SERVICE_TOKENS": "a:1,b:1"},
                {"TOOL_DATA_DIR": "d", "TOOL_SERVICE_TOKENS": "sin-dos-puntos"}):
        with pytest.raises(ConfigError):
            Settings.from_env(env)


def test_the_subject_parameter_may_be_named_subject_ref_and_all_names_must_agree(call: Call) -> None:
    same = call("leer_productos", bound={"subject_ref": NATALIA, "customer_id": NATALIA}).json()
    other = call("leer_productos", bound={"subject_ref": OTHER}).json()
    split = call("leer_productos", bound={"subject_ref": NATALIA, "customer_id": OTHER}).json()

    assert same["status"] == "ok"
    assert other["status"] == "denied" and other["error"]["kind"] == "subject_mismatch"
    assert split["status"] == "denied"
