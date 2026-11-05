"""SQLite-backed state for every item in a batch job.

The store is the single source of truth for a run. Because each status change is
committed immediately, a crash or Ctrl+C never loses finished work: the next run
reads the same file and continues from where the last one stopped.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    key        TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    status     TEXT NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    result     TEXT,
    updated_at REAL NOT NULL
)
"""


class Status(StrEnum):
    """Lifecycle of one item: pending -> running -> done | failed."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class Item:
    """One unit of work and everything the store knows about it."""

    key: str
    payload: dict[str, Any]
    status: Status
    attempts: int
    last_error: str | None
    result: Any


@dataclass(frozen=True)
class Summary:
    """Item counts per status."""

    pending: int = 0
    running: int = 0
    done: int = 0
    failed: int = 0

    @property
    def total(self) -> int:
        return self.pending + self.running + self.done + self.failed

    def as_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "pending": self.pending,
            "running": self.running,
            "done": self.done,
            "failed": self.failed,
        }


class Store:
    """Persists item state in a single SQLite file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    # -- lifecycle -----------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- writes --------------------------------------------------------------------

    def add(self, items: Iterable[tuple[str, dict[str, Any]]]) -> int:
        """Register items as pending. Keys that already exist are left untouched.

        Returns the number of newly added items, so adding the same input twice is a no-op.
        """
        now = time.time()
        rows = [(key, json.dumps(payload), Status.PENDING.value, now) for key, payload in items]
        before = self._conn.total_changes
        self._conn.executemany(
            "INSERT OR IGNORE INTO items (key, payload, status, updated_at) VALUES (?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()
        return self._conn.total_changes - before

    def recover(self) -> int:
        """Return items left `running` by an interrupted run to `pending`."""
        return self._set_status_where(Status.PENDING, Status.RUNNING)

    def start(self, key: str) -> None:
        """Mark an item as running and count the attempt."""
        self._update(key, "status = ?, attempts = attempts + 1", Status.RUNNING.value)

    def finish(self, key: str, result: Any) -> None:
        """Mark an item done and keep its result.

        Raises TypeError if the result cannot be stored as JSON; the item state is unchanged.
        """
        encoded = json.dumps(result)
        self._update(key, "status = ?, result = ?, last_error = NULL", Status.DONE.value, encoded)

    def requeue(self, key: str, error: str) -> None:
        """Put an item back to pending after a failed attempt that will be retried."""
        self._update(key, "status = ?, last_error = ?", Status.PENDING.value, error)

    def fail(self, key: str, error: str) -> None:
        """Mark an item failed once it has no attempts left."""
        self._update(key, "status = ?, last_error = ?", Status.FAILED.value, error)

    def retry_failed(self) -> int:
        """Move every failed item back to pending. Returns how many were moved."""
        return self._set_status_where(Status.PENDING, Status.FAILED)

    # -- reads ---------------------------------------------------------------------

    def get(self, key: str) -> Item | None:
        row = self._conn.execute(f"SELECT {_COLUMNS} FROM items WHERE key = ?", (key,)).fetchone()
        return _to_item(row) if row else None

    def items(self, status: Status | None = None) -> list[Item]:
        """Items in insertion order, optionally filtered by status."""
        if status is None:
            rows = self._conn.execute(f"SELECT {_COLUMNS} FROM items ORDER BY rowid").fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT {_COLUMNS} FROM items WHERE status = ? ORDER BY rowid", (status.value,)
            ).fetchall()
        return [_to_item(row) for row in rows]

    def summary(self) -> Summary:
        counts = dict(
            self._conn.execute("SELECT status, COUNT(*) FROM items GROUP BY status").fetchall()
        )
        return Summary(**{s.value: int(counts.get(s.value, 0)) for s in Status})

    # -- helpers -------------------------------------------------------------------

    def _update(self, key: str, assignments: str, *values: Any) -> None:
        cur = self._conn.execute(
            f"UPDATE items SET {assignments}, updated_at = ? WHERE key = ?",
            (*values, time.time(), key),
        )
        if cur.rowcount == 0:
            raise KeyError(key)
        self._conn.commit()

    def _set_status_where(self, new: Status, old: Status) -> int:
        cur = self._conn.execute(
            "UPDATE items SET status = ?, updated_at = ? WHERE status = ?",
            (new.value, time.time(), old.value),
        )
        self._conn.commit()
        return cur.rowcount


_COLUMNS = "key, payload, status, attempts, last_error, result"


def _to_item(row: tuple[Any, ...]) -> Item:
    key, payload, status, attempts, last_error, result = row
    return Item(
        key=key,
        payload=json.loads(payload),
        status=Status(status),
        attempts=attempts,
        last_error=last_error,
        result=json.loads(result) if result is not None else None,
    )
