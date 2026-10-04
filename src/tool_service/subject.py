"""Who the data is about. Never taken from ``args``: only from the engine's ``bound_params`` and the verified
claims, and every source that is present must agree (a mismatch is ``denied``, not an empty result).

- a ``customer`` principal reads its own data (its id is the customer id);
- an ``advisor`` reads the customer named by its delegation (``on_behalf_of``) and nothing without one;
- any other principal type has no data here.
"""

from __future__ import annotations

from dataclasses import dataclass

from tool_service.contract import ExecuteRequest

# agent-core's AuthzPort names the subject parameter (``AGENTCORE_AUTHZ_BIND_KEYS``); either name is accepted.
SUBJECT_PARAMS = ("customer_id", "subject_ref")


@dataclass(frozen=True)
class Subject:
    customer_id: str


@dataclass(frozen=True)
class Refused:
    kind: str


def resolve(request: ExecuteRequest) -> Subject | Refused:
    context = request.context
    principal = context.principal
    if principal.type == "customer":
        own = principal.id
        if not own:
            return Refused("no_subject")
        claimed = [own]
    elif principal.type == "advisor":
        delegation = context.on_behalf_of
        if delegation is None or delegation.subject.kind != "customer" or not delegation.subject.ref:
            return Refused("no_delegation")
        claimed = [delegation.subject.ref]
    else:
        return Refused("principal_not_served")
    if context.subject is not None and context.subject.kind == "customer":
        claimed.append(context.subject.ref)
    claimed.extend(value for name in SUBJECT_PARAMS if (value := request.bound_params.get(name)))
    if len(set(claimed)) != 1:
        return Refused("subject_mismatch")
    return Subject(customer_id=claimed[0])
