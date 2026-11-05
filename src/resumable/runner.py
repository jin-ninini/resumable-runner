"""Runs a task over every pending item, with retries, throttling and a circuit breaker."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from resumable.retry import RetryPolicy
from resumable.store import Item, Status, Store

Task = Callable[[dict[str, Any]], Any]
"""A task takes one item's payload and returns a JSON-serializable result, or raises."""


@dataclass(frozen=True)
class RunReport:
    """What one call to Runner.run did."""

    succeeded: int
    failed: int
    skipped: int
    """Items already done before this run started (the cache hits)."""
    stopped_early: bool
    stop_reason: str | None = None

    @property
    def processed(self) -> int:
        return self.succeeded + self.failed

    def as_dict(self) -> dict[str, Any]:
        return {
            "processed": self.processed,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "stopped_early": self.stopped_early,
            "stop_reason": self.stop_reason,
        }


class Runner:
    """Processes pending items one at a time and records every outcome in the store.

    Items run sequentially on purpose: the typical job (crawling, API calls) is limited
    by the remote side's rate limits, and a single writer keeps SQLite simple and safe.
    """

    def __init__(
        self,
        store: Store,
        task: Task,
        policy: RetryPolicy | None = None,
        *,
        min_interval: float = 0.0,
        max_consecutive_failures: int | None = None,
        log: Callable[[str], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if min_interval < 0:
            raise ValueError("min_interval must not be negative")
        if max_consecutive_failures is not None and max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be at least 1")
        self.store = store
        self.task = task
        self.policy = policy or RetryPolicy()
        self.min_interval = min_interval
        self.max_consecutive_failures = max_consecutive_failures
        self._log = log or (lambda _msg: None)
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None

    def run(self, limit: int | None = None) -> RunReport:
        """Process pending items until none are left, `limit` is reached or the breaker trips."""
        recovered = self.store.recover()
        if recovered:
            self._log(f"recovered {recovered} item(s) left running by an interrupted run")
        skipped = self.store.summary().done

        succeeded = failed = consecutive = 0
        for item in self.store.items(Status.PENDING):
            if limit is not None and succeeded + failed >= limit:
                break
            if self._run_item(item):
                succeeded += 1
                consecutive = 0
            else:
                failed += 1
                consecutive += 1
                if self.max_consecutive_failures and consecutive >= self.max_consecutive_failures:
                    reason = f"{consecutive} consecutive failures"
                    self._log(f"stopping: {reason}")
                    return RunReport(succeeded, failed, skipped, True, reason)
        return RunReport(succeeded, failed, skipped, False)

    def _run_item(self, item: Item) -> bool:
        for attempt in range(1, self.policy.max_attempts + 1):
            self._throttle()
            self.store.start(item.key)
            try:
                result = self.task(dict(item.payload))
            except Exception as exc:  # the task's own errors are data, not crashes
                error = f"{type(exc).__name__}: {exc}"
                if attempt < self.policy.max_attempts:
                    self.store.requeue(item.key, error)
                    wait = self.policy.delay(attempt)
                    self._log(
                        f"[retry] {item.key} attempt {attempt} failed ({error}), wait {wait}s"
                    )
                    self._sleep(wait)
                    continue
                self.store.fail(item.key, error)
                self._log(f"[failed] {item.key} after {attempt} attempt(s): {error}")
                return False
            try:
                self.store.finish(item.key, result)
            except TypeError as exc:
                self.store.fail(item.key, f"result is not JSON-serializable: {exc}")
                self._log(f"[failed] {item.key}: result is not JSON-serializable")
                return False
            self._log(f"[done] {item.key}")
            return True
        return False  # unreachable: max_attempts >= 1

    def _throttle(self) -> None:
        if self.min_interval and self._last_call is not None:
            wait = self.min_interval - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()
