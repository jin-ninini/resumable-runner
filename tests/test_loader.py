from pathlib import Path

import pytest

from resumable.loader import LoadError, load_task, read_items


def test_load_task_from_module() -> None:
    task = load_task("json:dumps")
    assert task({"a": 1}) == '{"a": 1}'


def test_load_task_from_file(tmp_path: Path) -> None:
    f = tmp_path / "jobs.py"
    f.write_text("def double(p):\n    return p['n'] * 2\n", encoding="utf-8")
    assert load_task(f"{f}:double")({"n": 4}) == 8


@pytest.mark.parametrize("spec", ["no_colon", ":func", "json:", "json:not_there", "nope_mod:f"])
def test_load_task_errors(spec: str) -> None:
    with pytest.raises(LoadError):
        load_task(spec)


def test_load_task_missing_file(tmp_path: Path) -> None:
    with pytest.raises(LoadError, match="not found"):
        load_task(f"{tmp_path / 'missing.py'}:f")


def test_read_csv(tmp_path: Path) -> None:
    f = tmp_path / "items.csv"
    f.write_text("id,url\n1,https://a\n2,https://b\n", encoding="utf-8")
    assert read_items(f) == [
        ("1", {"id": "1", "url": "https://a"}),
        ("2", {"id": "2", "url": "https://b"}),
    ]


def test_read_jsonl_with_custom_key(tmp_path: Path) -> None:
    f = tmp_path / "items.jsonl"
    f.write_text('{"place": 7, "name": "x"}\n\n{"place": 8, "name": "y"}\n', encoding="utf-8")
    assert [k for k, _ in read_items(f, key="place")] == ["7", "8"]


def test_read_txt(tmp_path: Path) -> None:
    f = tmp_path / "items.txt"
    f.write_text("alpha\n\n beta \n", encoding="utf-8")
    assert read_items(f) == [("alpha", {"value": "alpha"}), ("beta", {"value": "beta"})]


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("items.csv", "url\nhttps://a\n", "no 'id'"),
        ("items.csv", "id\n1\n1\n", "duplicate key"),
        ("items.jsonl", "[1, 2]\n", "JSON object"),
        ("items.jsonl", "{bad\n", "not valid JSON"),
        ("items.xlsx", "", "unsupported"),
    ],
)
def test_read_errors(tmp_path: Path, name: str, content: str, message: str) -> None:
    f = tmp_path / name
    f.write_text(content, encoding="utf-8")
    with pytest.raises(LoadError, match=message):
        read_items(f)


def test_read_missing_file(tmp_path: Path) -> None:
    with pytest.raises(LoadError, match="not found"):
        read_items(tmp_path / "nope.csv")
