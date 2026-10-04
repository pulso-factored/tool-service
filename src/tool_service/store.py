"""PQRs filed through this service. ``gold_restricted`` is read-only, so a filing lands here; it is keyed by
the engine's ``idempotency_key`` (the action id), which makes a replay return the first result and lets the
engine read back what it wrote (ADR 0007)."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_DDL = """
CREATE TABLE IF NOT EXISTS filed_pqrs (
    idempotency_key TEXT PRIMARY KEY,
    pqr_id          TEXT NOT NULL UNIQUE,
    customer_id     TEXT NOT NULL,
    transaction_id  TEXT NOT NULL,
    description     TEXT NOT NULL,
    status          TEXT NOT NULL,
    filed_at        TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class FiledPqr:
    pqr_id: str
    customer_id: str
    transaction_id: str
    description: str
    status: str
    filed_at: datetime

    def as_row(self) -> dict[str, object]:
        """The shape of ``customer_cases`` so a filed PQR reads like any other case."""
        return {
            "case_id": self.pqr_id, "opened_at": self.filed_at, "channel": "agent", "topic": "dispute",
            "priority": None, "complaint_status": self.status, "is_open": self.status == "Open",
            "claimed_amount": None, "claimed_currency": None, "complaint_description": self.description,
            "closed_at": None, "resolved": None, "resolution_code": None, "transaction_id": self.transaction_id}


class FiledPqrStore:
    def __init__(self, path: Path, clock: Callable[[], datetime] | None = None) -> None:
        self._path = path
        self._clock = clock or (lambda: datetime.now(UTC))
        with closing(self._connect()) as db, db:
            db.execute(_DDL)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=10)

    def file(self, key: str, customer_id: str, transaction_id: str, description: str) -> FiledPqr | None:
        """Files once per key. A replay returns the first filing; the same key for another customer is
        refused (``None``) instead of leaking the other customer's PQR."""
        pqr_id = "PQR-" + hashlib.sha256(key.encode()).hexdigest()[:12].upper()
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO filed_pqrs VALUES (?,?,?,?,?,?,?)",
                (key, pqr_id, customer_id, transaction_id, description, "Open", self._clock().isoformat()))
        return self.get(key, customer_id)

    def get(self, key: str, customer_id: str) -> FiledPqr | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT pqr_id, customer_id, transaction_id, description, status, filed_at "
                "FROM filed_pqrs WHERE idempotency_key = ? AND customer_id = ?", (key, customer_id)).fetchone()
        return _pqr(row) if row else None

    def of_customer(self, customer_id: str, limit: int) -> list[FiledPqr]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT pqr_id, customer_id, transaction_id, description, status, filed_at "
                "FROM filed_pqrs WHERE customer_id = ? ORDER BY filed_at DESC LIMIT ?",
                (customer_id, limit)).fetchall()
        return [_pqr(row) for row in rows]

    def ping(self) -> bool:
        try:
            with closing(self._connect()) as db:
                db.execute("SELECT 1 FROM filed_pqrs LIMIT 1")
        except sqlite3.Error:
            return False
        return True


def _pqr(row: tuple[str, str, str, str, str, str]) -> FiledPqr:
    return FiledPqr(pqr_id=row[0], customer_id=row[1], transaction_id=row[2], description=row[3],
                    status=row[4], filed_at=datetime.fromisoformat(row[5]))
