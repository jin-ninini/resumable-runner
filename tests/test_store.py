from pathlib import Path

import pytest

from resumable import Status, Store


def test_add_is_idempotent(store: Store) -> None:
    assert store.add([("a", {"n": 1}), ("b", {"n": 2})]) == 2
    assert store.add([("a", {"n": 99}), ("c", {"n": 3})]) == 1
    item = store.get("a")
    assert item is not None
    assert item.payload == {"n": 1}  # existing items are never overwritten
    assert store.summary().total == 3


def test_status_transitions(store: Store) -> None:
    store.add([("a", {})])
    store.start("a")
    assert store.summary().running == 1
    store.finish("a", {"title": "ok"})
    item = store.get("a")
    assert item is not None
    assert (item.status, item.attempts, item.result) == (Status.DONE, 1, {"title": "ok"})


def test_recover_returns_running_items_to_pending(store: Store) -> None:
    store.add([("a", {}), ("b", {})])
    store.start("a")
    assert store.recover() == 1
    assert store.summary().pending == 2


def test_retry_failed(store: Store) -> None:
    store.add([("a", {}), ("b", {})])
    store.fail("a", "boom")
    assert store.retry_failed() == 1
    assert [i.key for i in store.items(Status.PENDING)] == ["a", "b"]


def test_non_json_result_leaves_state_unchanged(store: Store) -> None:
    store.add([("a", {})])
    store.start("a")
    with pytest.raises(TypeError):
        store.finish("a", object())
    item = store.get("a")
    assert item is not None
    assert item.status is Status.RUNNING


def test_unknown_key_raises(store: Store) -> None:
    with pytest.raises(KeyError):
        store.start("missing")


def test_state_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    with Store(path) as s:
        s.add([("a", {})])
        s.start("a")
        s.finish("a", 42)
    with Store(path) as s:
        assert s.summary().done == 1
        item = s.get("a")
        assert item is not None and item.result == 42
