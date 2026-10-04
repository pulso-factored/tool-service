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
JSON numbers with their scale (`1342.80`), never strings or floats. A nullable value that depends on the product or the source comes with the flag that says why: `credit_limit` with
`credit_limit_applicable` / `is_missing_credit_limit` (not applicable vs unknown) and `amount_usd` with
`amount_usd_source` (`reported`, `derived_identity` or the approximate `derived_fx`); see data-pipeline's
`read_model_contract.json`. Internal columns (fraud score, response code,
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
`bound_params.customer_id` / `subject_ref`) must agree, otherwise `denied` (`subject_mismatch`). Other principal types have no data.
The customer id is the dataset's `customer_id` (the platform's `bank_customer_id`).

## The shared contract

`contracts/tool-provider.openapi.json` (OpenAPI 3.1, version in `contracts/tool-provider-version.txt`, currently 1.0.0)
is the contract **every** tool provider implements and every consumer pins: the two routes, the request and response
models, the six statuses and the rules around them (subject, writes, idempotency, step-up). It is provider-neutral
(no health checks) and is generated from `src/tool_service/contract.py`:

```
uv run python scripts/export_contract.py          # regenerate
uv run python scripts/export_contract.py --check  # CI: fails if the files drifted
```

- **This service** tests that its real answers (every kind of status, 401/404/422, the catalog) validate against it.
- **agent-core** copies both files into `tests/contracts/` and tests that what `HttpToolExecutor` sends validates
  against the request schema and that each response shape maps to the right `ToolResult`.
- Changing it: a new optional field is a minor version; anything a consumer or another provider could trip over is a
  major. Regenerate here, then copy the two files to agent-core in the same change set (its test names the version).
- Another provider (a payments or CRM service) implements the same document and can reuse these schemas to check itself.

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
3. **Subject.** agent-core's `PolicyAuthz` returns the subject in `bound_params` under the names in
   `AGENTCORE_AUTHZ_BIND_KEYS` (set `subject_ref,customer_id`); the service accepts either name, derives the subject
   from the verified claims too, and refuses (`denied`) if any of them disagree.
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
- `filed_pqrs` is SQLite; the bank's real case system is not integrated (a filed PQR is not reconciled with it).
- Per-role field policy for `leer_perfil` (needs data governance).

## Staying in step with data-pipeline

The tools select columns by name; data-pipeline publishes, with every run, a `read_model_contract.json` (which columns
exist, what a NULL means, which flags go with a value). `contracts/read-model-contract.json` is a **pinned copy**, and
`tests/test_read_model_contract.py` checks the tools against it: every selected column is published, a value is never
returned without the flag that says how to read it (`related_flags`), every tool `source` is a published read-model,
and returning a new direct identifier is a visible decision.

```
python scripts/sync_contract.py --from <data dir>           # refresh the pin from the latest publication
python scripts/sync_contract.py --from <data dir> --check   # fail if it drifted (ignores run_id)
TOOL_CONTRACT_DATA_DIR=<data dir> pytest tests/test_read_model_contract.py   # also compares the pin with a real run
```

A diff after a refresh means the pipeline changed what a read-model contains or means; the failing test names the tool.

