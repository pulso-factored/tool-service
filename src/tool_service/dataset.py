"""The published dataset: which run is current and a read-only connection to ``gold_restricted``.

data-pipeline publishes ``publish/<run_id>/gold_restricted.duckdb`` and flips ``publish/latest.json``
atomically. The pointer is re-read after ``ttl`` seconds; a new run opens a new connection and the previous
one is left to finish whatever is in flight. Nothing falls back to stale data silently: an unreadable pointer
or file is ``DataUnavailable``.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import duckdb

SCHEMA = "gold_restricted.gold_restricted"  # file stem is the catalog; the published tables live in this schema


class DataUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Snapshot:
    run_id: str
    connection: duckdb.DuckDBPyConnection

    def cursor(self) -> duckdb.DuckDBPyConnection:
        """A cursor per call: DuckDB connections are not shared between threads."""
        cursor = self.connection.cursor()
        cursor.execute(f"USE {SCHEMA}")
        return cursor


class Dataset:
    def __init__(self, data_dir: Path, ttl_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._root = data_dir
        self._ttl = ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._snapshot: Snapshot | None = None
        self._checked_at = float("-inf")

    def current(self) -> Snapshot:
        with self._lock:
            now = self._clock()
            if self._snapshot is not None and now - self._checked_at < self._ttl:
                return self._snapshot
            run_id, path = self._read_pointer()
            if self._snapshot is None or self._snapshot.run_id != run_id:
                self._snapshot = self._open(run_id, path)
            self._checked_at = now
            return self._snapshot

    def _read_pointer(self) -> tuple[str, Path]:
        try:
            pointer = json.loads((self._root / "publish" / "latest.json").read_text(encoding="utf-8"))
            run_id, relative = pointer["run_id"], pointer["path"]
            if not isinstance(run_id, str) or not isinstance(relative, str):
                raise TypeError("pointer")
            folder = (self._root / relative).resolve()
            if not folder.is_relative_to(self._root.resolve()):  # a pointer cannot lead out of the data dir
                raise ValueError("pointer outside data dir")
        except (OSError, ValueError, KeyError, TypeError):
            raise DataUnavailable("pointer") from None
        return run_id, folder

    @staticmethod
    def _open(run_id: str, folder: Path) -> Snapshot:
        try:
            connection = duckdb.connect(str(folder / "gold_restricted.duckdb"), read_only=True)
        except duckdb.Error:
            raise DataUnavailable("dataset") from None
        return Snapshot(run_id=run_id, connection=connection)

    def ready(self) -> bool:
        try:
            self.current()
        except DataUnavailable:
            return False
        return True
