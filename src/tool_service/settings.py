"""Configuration from the environment. Secrets (the consumer tokens) never appear in a repr or a log."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR_ENV = "TOOL_DATA_DIR"
TOKENS_ENV = "TOOL_SERVICE_TOKENS"
FILED_DB_ENV = "TOOL_FILED_DB"
POINTER_TTL_ENV = "TOOL_POINTER_TTL_S"
MAX_ROWS = 50


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    #: The ``data`` folder of data-pipeline: it holds ``publish/latest.json`` and ``publish/<run_id>/``.
    data_dir: Path
    #: ``consumer name -> bearer token``; one token per consumer so each can be audited and revoked alone.
    tokens: Mapping[str, str] = field(repr=False)
    #: SQLite file of the PQRs filed through this service (the dataset itself is read-only).
    filed_db: Path
    #: How long the ``latest.json`` pointer is trusted before it is read again.
    pointer_ttl_s: float = 60.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        problems: list[str] = []
        data_dir = (env.get(DATA_DIR_ENV) or "").strip()
        if not data_dir:
            problems.append(f"falta {DATA_DIR_ENV}")
        tokens = _parse_tokens(env.get(TOKENS_ENV) or "", problems)
        try:
            ttl = float(env.get(POINTER_TTL_ENV) or 60.0)
        except ValueError:
            ttl = -1.0
        if ttl < 0:
            problems.append(f"{POINTER_TTL_ENV} debe ser un número >= 0")
        if problems:
            raise ConfigError("; ".join(problems))
        filed = env.get(FILED_DB_ENV) or "filed_pqrs.db"
        return cls(data_dir=Path(data_dir), tokens=tokens, filed_db=Path(filed), pointer_ttl_s=ttl)


def _parse_tokens(raw: str, problems: list[str]) -> dict[str, str]:
    """``agent-core:tokenA,otro:tokenB``. At least one; no empty names or tokens; no repeated token."""
    tokens: dict[str, str] = {}
    for part in (p.strip() for p in raw.split(",") if p.strip()):
        name, sep, token = part.partition(":")
        if not sep or not name.strip() or not token.strip():
            problems.append(f"{TOKENS_ENV}: cada entrada es nombre:token")
            continue
        tokens[name.strip()] = token.strip()
    if not tokens:
        problems.append(f"falta {TOKENS_ENV} (nombre:token, separados por coma)")
    if len(set(tokens.values())) != len(tokens):
        problems.append(f"{TOKENS_ENV}: dos consumidores comparten token")
    return tokens
