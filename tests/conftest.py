"""A tiny synthetic dataset with the published layout (``publish/latest.json`` + ``gold_restricted.duckdb``)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient

from tool_service.app import Service, create_app
from tool_service.settings import Settings

TOKEN = "token-agent-core-0001"
OTHER_TOKEN = "token-otro-0002"
NATALIA = "CLI-0000000001"
OTHER = "CLI-0000000002"
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)

SCHEMA_SQL = """
CREATE SCHEMA gold_restricted.gold_restricted;
CREATE TABLE gold_restricted.gold_restricted.customer_profile (
  customer_id VARCHAR, document_type VARCHAR, document_number VARCHAR, first_name VARCHAR, last_name VARCHAR,
  email VARCHAR, segment VARCHAR, customer_status VARCHAR, city VARCHAR, state VARCHAR, country_iso2 VARCHAR,
  registration_date TIMESTAMP, credit_score INTEGER);
CREATE TABLE gold_restricted.gold_restricted.customer_products (
  product_id VARCHAR, customer_id VARCHAR, product_type VARCHAR, product_number VARCHAR, currency VARCHAR,
  current_balance DECIMAL(15,2), credit_limit DECIMAL(15,2), interest_rate DECIMAL(5,2), product_status VARCHAR,
  opening_date DATE, expiration_date DATE, days_past_due INTEGER);
CREATE TABLE gold_restricted.gold_restricted.customer_transactions (
  transaction_id VARCHAR, customer_id VARCHAR, product_id VARCHAR, transaction_ts TIMESTAMP, event_date DATE,
  transaction_type VARCHAR, transaction_category VARCHAR, amount DECIMAL(15,2), currency VARCHAR,
  amount_usd DECIMAL(18,2), channel VARCHAR, merchant_name VARCHAR, merchant_category VARCHAR,
  transaction_country_iso2 VARCHAR, transaction_city VARCHAR, transaction_status VARCHAR, response_code VARCHAR,
  is_fraud BOOLEAN, fraud_score DECIMAL(5,2), product_quarantined BOOLEAN);
CREATE TABLE gold_restricted.gold_restricted.customer_cases (
  case_id VARCHAR, customer_id VARCHAR, source_system VARCHAR, opened_at TIMESTAMP, channel VARCHAR,
  origin VARCHAR, topic VARCHAR, priority VARCHAR, assigned_analyst_id VARCHAR, complaint_status VARCHAR,
  is_open BOOLEAN, sla_breached BOOLEAN, is_repeat_complainer BOOLEAN, claimed_amount DECIMAL(15,2),
  claimed_currency VARCHAR, complaint_description VARCHAR, closed_at TIMESTAMP, resolved BOOLEAN,
  resolution_code VARCHAR, csat INTEGER);
INSERT INTO gold_restricted.gold_restricted.customer_profile VALUES
  ('CLI-0000000001','CC','1000000001','Natalia','Prueba','natalia@example.test','premium','Active','Bogota','DC','CO','2020-01-01 00:00:00',700),
  ('CLI-0000000002','CC','1000000002','Otro','Cliente','otro@example.test','basic','Active','Cali','VAC','CO','2021-01-01 00:00:00',650);
INSERT INTO gold_restricted.gold_restricted.customer_products VALUES
  ('PRD-1','CLI-0000000001','credit_card','4111000011112222','USD',1342.80,5000.00,2.10,'Active','2022-03-01',NULL,0),
  ('PRD-2','CLI-0000000001','checking_account','7720229470','USD',250.00,NULL,0.10,'Active','2023-05-10',NULL,NULL),
  ('PRD-9','CLI-0000000002','credit_card','4111000099998888','USD',99.00,1000.00,2.10,'Active','2022-01-01',NULL,0);
INSERT INTO gold_restricted.gold_restricted.customer_transactions VALUES
  ('TX-1','CLI-0000000001','PRD-1','2026-09-27 10:00:00','2026-09-27','purchase','retail',120.50,'USD',120.50,'pos','Tienda Aurora','retail','CO','Bogota','posted','00',false,0.10,false),
  ('TX-2','CLI-0000000001','PRD-1','2026-09-28 18:30:00','2026-09-28','purchase','food',8.75,'USD',8.75,'pos','Cafe Sol','restaurants','CO','Bogota','posted','00',false,0.00,false),
  ('TX-3','CLI-0000000001','PRD-1','2026-08-14 20:00:00','2026-08-14','purchase','food',64.20,'USD',64.20,'pos','Restaurante Mar','restaurants','CO','Bogota','posted','00',false,0.00,false),
  ('TX-4','CLI-0000000001','PRD-2','2026-09-01 09:00:00','2026-09-01','purchase','retail',640.00,'USD',640.00,'online','Electro Norte','electronics','CO','Bogota','posted','00',false,0.70,false),
  ('TX-9','CLI-0000000002','PRD-9','2026-09-29 09:00:00','2026-09-29','purchase','retail',55.00,'USD',55.00,'pos','Tienda Aurora','retail','CO','Cali','posted','00',false,0.00,false);
INSERT INTO gold_restricted.gold_restricted.customer_cases VALUES
  ('CASE-1','CLI-0000000001','crm','2026-07-01 08:00:00','phone','customer','card_dispute','medium','AN-1','Closed',false,false,false,300.00,'USD','Cargo duplicado','2026-07-05 10:00:00',true,'REFUND',5),
  ('CASE-9','CLI-0000000002','crm','2026-07-02 08:00:00','web','customer','fees','low',NULL,'Open',true,false,false,NULL,NULL,'Comision',NULL,NULL,NULL,NULL);
"""


def build_run(data_dir: Path, run_id: str, *, extra_sql: str = "") -> None:
    folder = data_dir / "publish" / run_id
    folder.mkdir(parents=True)
    connection = duckdb.connect(str(folder / "gold_restricted.duckdb"))
    connection.execute(SCHEMA_SQL + extra_sql)
    connection.close()
    point(data_dir, run_id)


def point(data_dir: Path, run_id: str) -> None:
    (data_dir / "publish" / "latest.json").write_text(
        json.dumps({"run_id": run_id, "path": f"publish/{run_id}"}), encoding="utf-8")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    build_run(root, "run-1")
    return root


@pytest.fixture
def settings(data_dir: Path, tmp_path: Path) -> Settings:
    return Settings(data_dir=data_dir, tokens={"agent-core": TOKEN, "otro": OTHER_TOKEN},
                    filed_db=tmp_path / "filed.db", pointer_ttl_s=0.0)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(service=Service(settings, clock=lambda: NOW)))


Call = Callable[..., Any]


def context(*, principal: str = "customer", pid: str | None = NATALIA, level: str = "session",
            grant_for: str | None = None, call_id: str = "call-1") -> dict[str, Any]:
    ctx: dict[str, Any] = {"run_id": "run-x", "release": "rel-1", "call_id": call_id, "turn_id": "turn-1",
                           "principal": {"type": principal, "id": pid, "roles": [], "scopes": [], "attrs": {},
                                         "auth_level": level},
                           "subject": None, "on_behalf_of": None}
    if grant_for is not None:
        ctx["on_behalf_of"] = {"subject": {"kind": "customer", "ref": grant_for}, "grant_ref": "case-1:adv-7",
                               "scopes": ["read"]}
    return ctx


@pytest.fixture
def call(client: TestClient) -> Call:
    def make(tool: str, args: dict[str, Any] | None = None, *, token: str = TOKEN, key: str | None = None,
             bound: dict[str, str] | None = None, **ctx: Any) -> Any:
        body = {"tool": f"{tool}@1.0.0", "args": args or {}, "bound_params": bound if bound is not None else {},
                "context": context(**ctx), "idempotency_key": key}
        return client.post(f"/v1/tools/{tool}/execute", json=body, headers={"Authorization": f"Bearer {token}"})

    return make
