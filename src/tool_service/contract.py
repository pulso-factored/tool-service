"""The wire contract of ``POST /v1/tools/{id}/execute`` (the same one every tool provider implements).

Statuses are the engine's: reads answer ok|error|timeout|denied|step_up_required, writes answer
ok|denied|uncertain|step_up_required. Anything the model could have written lives in ``args``; the subject
comes only from ``bound_params`` and the verified claims in ``context``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Status(StrEnum):
    ok = "ok"
    error = "error"
    timeout = "timeout"
    denied = "denied"
    uncertain = "uncertain"
    step_up_required = "step_up_required"


class Strict(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class PrincipalClaims(Strict):
    type: str
    id: str | None = None
    roles: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    attrs: dict[str, str] = Field(default_factory=dict)
    auth_level: str = "session"


class SubjectClaim(Strict):
    kind: str
    ref: str


class DelegationClaims(Strict):
    subject: SubjectClaim
    grant_ref: str
    scopes: list[str] = Field(default_factory=list)


class CallContext(Strict):
    run_id: str | None = None
    call_id: str
    release: str | None = None
    turn_id: str | None = None
    principal: PrincipalClaims
    subject: SubjectClaim | None = None
    on_behalf_of: DelegationClaims | None = None


class ExecuteRequest(Strict):
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    bound_params: dict[str, str] = Field(default_factory=dict)
    context: CallContext
    idempotency_key: str | None = None


class ToolError(Strict):
    kind: str
    message: str


class ExecuteResponse(Strict):
    status: Status
    result: Any = None
    source: str | None = None
    error: ToolError | None = None
    dataset_run_id: str | None = None


class ToolInfo(Strict):
    id: str
    version: str
    risk_class: str
    min_auth_level: str
    source: str | None
    idempotent: bool
    args_schema: dict[str, Any]


class ToolList(Strict):
    tools: list[ToolInfo]
