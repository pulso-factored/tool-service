"""The HTTP surface: ``POST /v1/tools/{id}/execute``, ``GET /v1/tools``, ``/healthz`` and ``/readyz``."""

import hmac
import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import ValidationError

from tool_service import jsonout, subject
from tool_service.contract import ExecuteRequest, ExecuteResponse, Status, ToolError, ToolInfo, ToolList
from tool_service.dataset import Dataset, DataUnavailable
from tool_service.schema import validate
from tool_service.settings import Settings
from tool_service.store import FiledPqrStore
from tool_service.tools import CATALOG, Env, Outcome, ToolSpec

_LOG = logging.getLogger("tool_service")
_RANK = {"anonymous": 0, "session": 1, "step_up": 2}


class Service:
    def __init__(self, settings: Settings, clock: Callable[[], datetime] | None = None) -> None:
        self.settings = settings
        self.dataset = Dataset(settings.data_dir, settings.pointer_ttl_s)
        self.store = FiledPqrStore(settings.filed_db, clock)

    def consumer_of(self, token: str) -> str | None:
        found: str | None = None
        for name, expected in self.settings.tokens.items():  # every token is compared: no early exit
            if hmac.compare_digest(token.encode(), expected.encode()):
                found = name
        return found

    def execute(self, spec: ToolSpec, request: ExecuteRequest) -> ExecuteResponse:
        def refuse(status: Status, kind: str, message: str) -> ExecuteResponse:
            return ExecuteResponse(status=status, source=spec.source, error=ToolError(kind=kind, message=message))

        # A write never answers `error`: it either refused before any effect (`denied`) or may have happened.
        refused = Status.denied if spec.is_write else Status.error
        problem = validate(request.args, spec.args_schema)
        if problem:
            return refuse(refused, "invalid_args", problem)
        level = _RANK.get(request.context.principal.auth_level, 0)
        if level < _RANK[spec.min_auth_level]:
            return ExecuteResponse(status=Status.step_up_required, source=spec.source)
        who = subject.resolve(request)
        if isinstance(who, subject.Refused):
            return refuse(Status.denied, who.kind, "el sujeto de la llamada no es válido")
        if spec.is_write and not request.idempotency_key:
            return refuse(Status.denied, "idempotency_key_required", "una escritura lleva idempotency_key")
        try:
            snapshot = self.dataset.current()
        except DataUnavailable:
            return refuse(Status.error, "data_unavailable", "los datos no están disponibles")
        outcome: Outcome = spec.handler(Env(snapshot, self.store), who.customer_id, _defaults(spec, request.args),
                                        request)
        error = ToolError(kind=outcome.error_kind or "error", message=outcome.error_message or "") \
            if outcome.status is not Status.ok else None
        return ExecuteResponse(status=outcome.status, result=outcome.result, source=spec.source, error=error,
                               dataset_run_id=snapshot.run_id)


def _defaults(spec: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
    properties = spec.args_schema.get("properties", {})
    return {**{k: v["default"] for k, v in properties.items() if "default" in v}, **args}


def create_app(settings: Settings | None = None, *, service: Service | None = None) -> FastAPI:
    service = service or Service(settings or Settings.from_env())
    app = FastAPI(title="tool-service", version="0.1.0", docs_url=None, redoc_url=None)

    def caller(authorization: Annotated[str | None, Header()] = None) -> str:
        scheme, _, token = (authorization or "").partition(" ")
        consumer = service.consumer_of(token) if scheme.lower() == "bearer" and token else None
        if consumer is None:
            raise HTTPException(status_code=401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"})
        return consumer

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(response: Response) -> dict[str, bool]:
        checks = {"dataset": service.dataset.ready(), "store": service.store.ping()}
        if not all(checks.values()):
            response.status_code = 503
        return checks

    @app.get("/v1/tools", response_model=ToolList)
    def list_tools(_: Annotated[str, Depends(caller)]) -> ToolList:
        return ToolList(tools=[
            ToolInfo(id=s.id, version=s.version, risk_class=s.risk_class, min_auth_level=s.min_auth_level,
                     source=s.source, idempotent=s.idempotent, args_schema=s.args_schema)
            for s in CATALOG.values()])

    @app.post("/v1/tools/{tool_id}/execute", response_model=ExecuteResponse)
    async def execute(tool_id: str, request: Request, consumer: Annotated[str, Depends(caller)]) -> Response:
        started = time.perf_counter()
        spec = CATALOG.get(tool_id)
        if spec is None:
            return _reply(ExecuteResponse(status=Status.error, error=ToolError(
                kind="unknown_tool", message="tool desconocida")), 404)
        try:
            body = ExecuteRequest.model_validate_json(await request.body())
        except ValidationError:
            return _reply(ExecuteResponse(status=Status.error, error=ToolError(
                kind="bad_request", message="cuerpo inválido")), 422)
        try:
            answer = service.execute(spec, body)
        except Exception as exc:  # nothing leaves as a stack trace; the log names the class only
            _LOG.error("tool=%s call=%s consumer=%s failed: %s", tool_id, body.context.call_id, consumer,
                       type(exc).__name__)
            answer = ExecuteResponse(status=Status.error, source=spec.source, error=ToolError(
                kind="internal", message="error interno"))
        _LOG.info("tool=%s call=%s run=%s consumer=%s status=%s dataset=%s ms=%d", tool_id, body.context.call_id,
                  body.context.run_id, consumer, answer.status.value, answer.dataset_run_id,
                  (time.perf_counter() - started) * 1000)
        return _reply(answer, 200)

    return app


def _reply(answer: ExecuteResponse, status_code: int) -> Response:
    return Response(content=jsonout.dumps(answer), status_code=status_code, media_type="application/json")
