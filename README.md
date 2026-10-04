# tool-service

HTTP service that exposes **tools** over the data published by `data-pipeline` (`gold_restricted`), so that
`agent-core` (and any other consumer) can read a customer's products, movements, profile and cases and file a PQR.
It is a *tool provider*: it implements one contract, `POST /v1/tools/{id}/execute`, that any other service can also
implement to expose its own tools to agent-core (ADR 0025 in agent-core; design in support-platform ADR 0004).

- Read-only on the dataset: the `latest.json` pointer is followed, the DuckDB file is opened read-only, and a new
  published run is picked up after `TOOL_POINTER_TTL_S` (60 s). An unreadable pointer or file is
  `data_unavailable`, never stale data.
- The only write is filing a PQR, kept in a small SQLite table (`filed_pqrs`), idempotent by the engine's action id.
- Thin by design: it returns the table rows (curated columns). **What the model may see is decided by agent-core's
  `FieldClassifier`**, using the `source` (table name) the service returns and the FieldClassification catalog that
  data-pipeline exports.

## Tools

| Tool | Kind | Level | Source | Args |
|---|---|---|---|---|
| `leer_productos` | read | session | `customer_products` | `limite` (1–50, 20) |
| `leer_perfil` | read | session | `customer_profile` | – |
| `leer_movimientos` | read | session | `customer_transactions` | `limite` (1–50, 10), `product_id` |
| `buscar_transacciones` | read | session | `customer_transactions` | `texto`, `desde`, `hasta` (AAAA-MM-DD), `monto_min`, `monto_max`, `limite` |
| `leer_pqr_cliente` | read | session | `customer_cases` | `limite` (1–50, 10) |
| `radicar_pqr` | `write_reversible` | **step_up** | `customer_cases` | `transaction_id`, `descripcion` (both required) |
| `obtener_pqr` | read (read-back of `radicar_pqr`) | session | `customer_cases` | `idempotency_key` |

Movements and cases come **newest first** with an explicit order (the copilot does not sort by itself). Amounts are
JSON numbers with their scale (`1342.80`), never strings or floats. Internal columns (fraud score, response code,
assigned analyst, CSAT, credit score, email, document number) are not returned.

`leer_pqr_cliente` merges the dataset's cases with the PQRs filed through this service, so a PQR filed today is
visible today. `radicar_pqr` is refused (`denied`) for an advisor (the copilot only looks and suggests), without an
`idempotency_key`, with a transaction that is not the customer's, or with bad args; it never answers `error`.

Not here (they are agent-core's own or pure compute): `obtener_handoff`, `leer_transcript`, `seleccionar`,
`convertir_moneda` (needs an FX source).

## The contract

```
POST /v1/tools/{id}/execute            Authorization: Bearer <consumer token>
{ "tool": "leer_productos@1.0.0",
  "args": {...},                        # written by the model; never carries the subject
  "bound_params": {"customer_id": "…"}, # fixed by the engine
  "context": { "run_id", "call_id", "release", "turn_id",
               "principal": {type, id, roles, scopes, attrs, auth_level},
               "subject": {kind, ref} | null,
               "on_behalf_of": {subject, grant_ref, scopes} | null },
  "idempotency_key": "<action id>" | null }

200 { "status": "ok|denied|step_up_required|error|timeout|uncertain",
      "result": …, "source": "<table>", "error": {"kind","message"} | null, "dataset_run_id": "…" }
```

Other answers: `401` (bad or missing token), `404 unknown_tool`, `422 bad_request`. `GET /v1/tools` lists every tool
with its declaration and full args schema; `GET /healthz` (alive) and `GET /readyz` (dataset + store reachable).
The models are in `src/tool_service/contract.py`.

**Who the data is about** (`subject.py`): a `customer` principal reads its own id; an `advisor` reads the customer in
its delegation (`on_behalf_of`) and nothing without one; every source present (principal, delegation, `context.subject`,
`bound_params.customer_id`) must agree, otherwise `denied` (`subject_mismatch`). Other principal types have no data.
The customer id is the dataset's `customer_id` (the platform's `bank_customer_id`).

## How agent-core calls these tools

1. **Registry.** `registry/tools/*.yaml` are the `ToolDef`s (generated from the catalog: `uv run python
   scripts/export_registry.py`; `--check` fails on drift). They keep to agent-core's closed schema subset; the service
   enforces the stricter limits (ranges, lengths, date format) itself. Import them into agent-core's registry.
2. **Wiring.** Run `agentcore serve` with the tool executor over HTTP:

   ```
   AGENTCORE_TOOL_SERVICE_URL=http://tool-service:8080
   AGENTCORE_TOOL_SERVICE_TOKEN=<this consumer's token>
   agentcore serve … --tools agent_core.adapters.tools:http_tool_executor
   ```
3. **Subject.** agent-core's real `AuthzPort.bind_params` must return `{"customer_id": <bank customer id>}`; until it
   exists the service derives the subject from the verified claims (principal / delegation) and agrees with it.
4. **Step-up.** `radicar_pqr` needs `step_up`: agent-core answers `step_up_required` itself below that level, and this
   service checks again.
5. **Writes.** The engine sends `idempotency_key = action_id`; a replay returns the first filing; `obtener_pqr` with the
   same key is the read-back. A transport failure on a write is `uncertain` on agent-core's side (ADR 0007).
6. **Classification.** Load the FieldClassification catalog that data-pipeline exports (`field_classification.json` next
   to each published run) as agent-core's `FieldClassifier`: result rows are keyed by `source` (e.g.
   `customer_products.current_balance`).

Another service can expose its tools the same way: implement the contract above, give agent-core its URL and token,
and list its `ToolDef`s in the registry.

## Run

```
uv sync
TOOL_DATA_DIR=../data-pipeline/data TOOL_SERVICE_TOKENS=agent-core:<token> uv run tool-service
```

| Variable | Meaning |
|---|---|
| `TOOL_DATA_DIR` | data-pipeline's `data` folder (has `publish/latest.json`) – required |
| `TOOL_SERVICE_TOKENS` | `consumer:token,consumer2:token2`; one token per consumer, all distinct – required |
| `TOOL_FILED_DB` | SQLite file for filed PQRs (default `filed_pqrs.db`) |
| `TOOL_POINTER_TTL_S` | seconds the pointer is trusted before re-reading (default 60) |
| `HOST` / `PORT` | bind address (default `127.0.0.1:8080`) |

Logs carry tool, call id, run id, consumer, status, dataset run and latency; never args, results or claims.
Keep the service on the private network: the bearer is what lets it trust the claims agent-core sends.

## Develop

```
uv run pytest        # synthetic dataset with the published layout; no network
uv run ruff check . && uv run mypy
```

Measured on the published dataset (4.4 M transactions): each call takes 0–30 ms.

## Not done yet

- S3 source for the dataset (today a local folder), caching tuned for a deployment, tokens from a secret manager.
- A shared contract schema file checked from both repos (the models live in `contract.py`).
- `filed_pqrs` is SQLite; the bank's real case system is not integrated (a filed PQR is not reconciled with it).
- Per-role field policy for `leer_perfil` (needs data governance).
