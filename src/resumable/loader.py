"""Load the task function and the input items named on the command line."""

from __future__ import annotations

import csv
import importlib
import importlib.util
import json
from pathlib import Path
from typing import Any

from resumable.runner import Task


class LoadError(Exception):
    """The task spec or the input file could not be used."""


def load_task(spec: str) -> Task:
    """Resolve "package.module:function" or "path/to/file.py:function" to a callable."""
    target, sep, name = spec.rpartition(":")
    if not sep or not target or not name:
        raise LoadError(
            f"task must look like 'module:function' or 'file.py:function', got {spec!r}"
        )

    if target.endswith(".py"):
        path = Path(target)
        if not path.is_file():
            raise LoadError(f"task file not found: {path}")
        module_spec = importlib.util.spec_from_file_location(path.stem, path)
        if module_spec is None or module_spec.loader is None:
            raise LoadError(f"cannot import {path}")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
    else:
        try:
            module = importlib.import_module(target)
        except ImportError as exc:
            raise LoadError(f"cannot import module {target!r}: {exc}") from exc

    func = getattr(module, name, None)
    if not callable(func):
        raise LoadError(f"{target!r} has no callable named {name!r}")
    task: Task = func
    return task


def read_items(path: str | Path, key: str = "id") -> list[tuple[str, dict[str, Any]]]:
    """Read (key, payload) pairs from a .csv, .jsonl or .txt file.

    - .csv and .jsonl: every row is a payload; the `key` column identifies the item.
    - .txt: every non-empty line is one item; the line is both key and payload["value"].

    Duplicate keys are rejected so a typo in the input never silently drops work.
    """
    path = Path(path)
    if not path.is_file():
        raise LoadError(f"input file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".txt":
        lines = path.read_text(encoding="utf-8").splitlines()
        pairs = [(line.strip(), {"value": line.strip()}) for line in lines if line.strip()]
    elif suffix in (".csv", ".jsonl"):
        rows = _read_csv(path) if suffix == ".csv" else _read_jsonl(path)
        pairs = []
        for lineno, row in enumerate(rows, start=1):
            if key not in row or row[key] in (None, ""):
                raise LoadError(f"{path.name} row {lineno} has no {key!r} value")
            pairs.append((str(row[key]), row))
    else:
        raise LoadError(f"unsupported input type {suffix!r}; use .csv, .jsonl or .txt")

    seen: set[str] = set()
    for item_key, _ in pairs:
        if item_key in seen:
            raise LoadError(f"duplicate key {item_key!r} in {path.name}")
        seen.add(item_key)
    return pairs


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LoadError(f"{path.name} line {lineno} is not valid JSON: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise LoadError(f"{path.name} line {lineno} must be a JSON object")
        rows.append(row)
    return rows
