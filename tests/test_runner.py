from collections import Counter
from typing import Any

import pytest

from resumable import RetryPolicy, Runner, Status, Store
from tests.conftest import FakeClock

NO_WAIT = RetryPolicy(max_attempts=3, base_delay=0)


def test_processes_every_pending_item(store: Store) -> None:
    store.add([(k, {"n": n}) for n, k in enumerate("abc")])
    report = Runner(store, lambda p: p["n"] * 10, NO_WAIT).run()
    assert (report.succeeded, report.failed, report.skipped) == (3, 0, 0)
    assert [i.result for i in store.items()] == [0, 10, 20]


def test_rerun_skips_finished_items(store: Store) -> None:
    calls: Counter[str] = Counter()

    def task(p: dict[str, Any]) -> str:
        calls[p["k"]] += 1
        return "ok"

    store.add([(k, {"k": k}) for k in "abc"])
    Runner(store, task, NO_WAIT).run()
    report = Runner(store, task, NO_WAIT).run()
    assert report.skipped == 3 and report.processed == 0
    assert calls == Counter({"a": 1, "b": 1, "c": 1})


def test_flaky_item_succeeds_after_backoff(store: Store, clock: FakeClock) -> None:
    attempts = {"n": 0}

    def flaky(_p: dict[str, Any]) -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("timeout")
        return "ok"

    store.add([("a", {})])
    policy = RetryPolicy(max_attempts=3, base_delay=1, backoff=2)
    report = Runner(store, flaky, policy, sleep=clock.sleep, clock=clock).run()
    item = store.get("a")
    assert report.succeeded == 1
    assert item is not None and item.attempts == 3 and item.last_error is None
    assert clock.sleeps == [1, 2]


def test_item_fails_after_last_attempt(store: Store) -> None:
    def broken(_p: dict[str, Any]) -> None:
        raise ValueError("bad page")

    store.add([("a", {})])
    report = Runner(store, broken, NO_WAIT).run()
    item = store.get("a")
    assert report.failed == 1
    assert item is not None
    assert (item.status, item.attempts, item.last_error) == (
        Status.FAILED,
        3,
        "ValueError: bad page",
    )


def test_resumes_after_interruption(store: Store) -> None:
    def interrupted(p: dict[str, Any]) -> str:
        if p["k"] == "b":
            raise KeyboardInterrupt  # simulates Ctrl+C mid-run
        return "ok"

    store.add([(k, {"k": k}) for k in "abc"])
    with pytest.raises(KeyboardInterrupt):
        Runner(store, interrupted, NO_WAIT).run()
    summary = store.summary()
    assert (summary.done, summary.running, summary.pending) == (1, 1, 1)

    report = Runner(store, lambda _p: "ok", NO_WAIT).run()
    assert (report.skipped, report.succeeded) == (1, 2)
    assert store.summary().done == 3


def test_circuit_breaker_stops_the_run(store: Store) -> None:
    def blocked(_p: dict[str, Any]) -> None:
        raise PermissionError("403 blocked")

    store.add([(str(n), {}) for n in range(10)])
    policy = RetryPolicy(max_attempts=1)
    report = Runner(store, blocked, policy, max_consecutive_failures=3).run()
    assert report.stopped_early and report.failed == 3
    assert store.summary().pending == 7  # untouched items wait for the next run


def test_success_resets_the_breaker(store: Store) -> None:
    outcomes = iter([False, False, True, False, False, True])

    def task(_p: dict[str, Any]) -> str:
        if not next(outcomes):
            raise RuntimeError("nope")
        return "ok"

    store.add([(str(n), {}) for n in range(6)])
    report = Runner(store, task, RetryPolicy(max_attempts=1), max_consecutive_failures=3).run()
    assert not report.stopped_early
    assert (report.succeeded, report.failed) == (2, 4)


def test_limit(store: Store) -> None:
    store.add([(str(n), {}) for n in range(5)])
    report = Runner(store, lambda _p: 1, NO_WAIT).run(limit=2)
    assert report.processed == 2 and store.summary().pending == 3


def test_min_interval_throttles_calls(store: Store, clock: FakeClock) -> None:
    store.add([(str(n), {}) for n in range(3)])
    Runner(store, lambda _p: 1, NO_WAIT, min_interval=0.5, sleep=clock.sleep, clock=clock).run()
    assert clock.sleeps == [0.5, 0.5]


def test_non_json_result_is_a_failure(store: Store) -> None:
    store.add([("a", {})])
    report = Runner(store, lambda _p: object(), NO_WAIT).run()
    item = store.get("a")
    assert report.failed == 1
    assert item is not None and "not JSON-serializable" in (item.last_error or "")


@pytest.mark.parametrize("kwargs", [{"min_interval": -1}, {"max_consecutive_failures": 0}])
def test_rejects_invalid_settings(store: Store, kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        Runner(store, lambda _p: 1, **kwargs)  # type: ignore[arg-type]
