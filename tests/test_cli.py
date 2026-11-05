import json
from pathlib import Path

import pytest

from resumable.cli import EXIT_OK, EXIT_UNFINISHED, EXIT_USAGE, main

TASKS = """
def ok(p):
    return {"id": p["id"], "len": len(p["id"])}

def fail_odd(p):
    if int(p["id"]) % 2:
        raise ValueError("odd")
    return "even"
"""


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tasks.py").write_text(TASKS, encoding="utf-8")
    (tmp_path / "items.csv").write_text("id\n1\n2\n3\n4\n", encoding="utf-8")
    return tmp_path


def run_json(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:  # type: ignore[type-arg]
    code = main([*argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_run_all_done(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run_json(["run", "tasks.py:ok", "--input", "items.csv"], capsys)
    assert code == EXIT_OK
    assert out["added"] == 4 and out["summary"]["done"] == 4


def test_rerun_adds_nothing_and_skips_done(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["run", "tasks.py:ok", "--input", "items.csv", "--json"])
    capsys.readouterr()
    code, out = run_json(["run", "tasks.py:ok", "--input", "items.csv"], capsys)
    assert code == EXIT_OK
    assert out["added"] == 0 and out["report"]["skipped"] == 4 and out["report"]["processed"] == 0


def test_failures_then_retry(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["run", "tasks.py:fail_odd", "--input", "items.csv", "--max-attempts", "1"]
    code, out = run_json(argv, capsys)
    assert code == EXIT_UNFINISHED and out["summary"]["failed"] == 2

    code, out = run_json(["status"], capsys)
    assert code == EXIT_UNFINISHED
    assert {f["key"] for f in out["failed"]} == {"1", "3"}

    code, out = run_json(["retry"], capsys)
    assert out["requeued"] == 2

    code, out = run_json(["run", "tasks.py:ok"], capsys)  # fixed task, no new input
    assert code == EXIT_OK and out["report"]["succeeded"] == 2


def test_export_filters_by_status(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["run", "tasks.py:fail_odd", "--input", "items.csv", "--max-attempts", "1", "--json"])
    capsys.readouterr()
    assert main(["export", "--status", "done", "-o", "done.jsonl"]) == EXIT_OK
    rows = [json.loads(line) for line in (workdir / "done.jsonl").read_text().splitlines()]
    assert [(r["key"], r["result"]) for r in rows] == [("2", "even"), ("4", "even")]


def test_human_output(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["run", "tasks.py:ok", "--input", "items.csv"])
    captured = capsys.readouterr()
    assert "added 4, processed 4: 4 done" in captured.out
    assert "[done] 1" in captured.err


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "tasks.py:missing", "--input", "items.csv"],
        ["run", "tasks.py:ok", "--input", "nope.csv"],
        ["run", "tasks.py:ok", "--max-attempts", "0"],
        ["status"],
    ],
)
def test_usage_errors(workdir: Path, argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv) == EXIT_USAGE
    assert "error:" in capsys.readouterr().err
