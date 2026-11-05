# 🔁 resumable-runner

> Python library and CLI that runs a function over many items, survives interruptions, and resumes where it stopped.

[![CI](https://github.com/jin-ninini/resumable-runner/actions/workflows/ci.yml/badge.svg)](https://github.com/jin-ninini/resumable-runner/actions/workflows/ci.yml)

<br>

## Overview

Collecting place, menu and review data for hundreds of thousands of outlets during a data internship, a plain crawling loop kept failing the same way: a crash meant starting over, every script reinvented retry logic, and a blocked site produced thousands of failures in a row. resumable-runner turns the cache, resume, retry and status tracking I built inside that project into a small, dependency-free tool that any batch job can reuse. It contains no company code or data.

<br>

## Approach

- **State**: Stores every item in one SQLite file and commits each status change (`pending → running → done / failed`) immediately
- **Resume**: Returns items left `running` by a crash or Ctrl+C to `pending` on the next run and skips items already `done`
- **Retry**: Retries failed attempts with exponential backoff (`RetryPolicy`: attempts, base delay, cap)
- **Throttle**: Keeps a minimum interval between calls for polite crawling and API rate limits
- **Circuit Breaker**: Stops the run after N failed items in a row and leaves untouched items `pending`
- **Interface**: Exposes `run / status / retry / export` commands with `--json` output and fixed exit codes, so scripts, CI jobs and LLM agents can drive it

<br>

## Results

| Check | Tool | Result |
|---|---|---|
| Unit and CLI tests | pytest | 52 passed |
| Coverage | pytest-cov | 97% |
| Type check | mypy (strict) | No issues |
| Lint and format | Ruff | No issues |
| CI | GitHub Actions | Ubuntu and Windows, Python 3.11 to 3.13 |

- Rerunning the same command adds no items and skips finished work, verified by `test_rerun_skips_finished_items`
- An interrupted item is picked up again on the next run, verified by `test_resumes_after_interruption`
- Backoff and throttling are tested with a fake clock, so the whole suite runs in about 2 seconds

<br>

## Tech Stack

| Category | Stack |
|---|---|
| Languages | ![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white) |
| Database | ![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white) |
| Testing & Quality | ![pytest](https://img.shields.io/badge/pytest-0A9EDC?style=flat-square&logo=pytest&logoColor=white)  ![Ruff](https://img.shields.io/badge/Ruff-D7FF64?style=flat-square&logo=ruff&logoColor=black)  ![mypy](https://img.shields.io/badge/mypy-2A6DB2?style=flat-square&logoColor=white) |
| Development & Environment | ![Git](https://img.shields.io/badge/Git-F05032?style=flat-square&logo=git&logoColor=white)  ![GitHub](https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=github&logoColor=white)  ![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-2088FF?style=flat-square&logo=githubactions&logoColor=white)  ![uv](https://img.shields.io/badge/uv-DE5FE9?style=flat-square&logo=uv&logoColor=white) |

<br>

## Project Structure

```text
resumable-runner/
├── src/resumable/
│   ├── store.py        # SQLite item state: pending, running, done, failed
│   ├── runner.py       # Retry, backoff, throttling and circuit breaker loop
│   ├── retry.py        # RetryPolicy: attempts and exponential backoff
│   ├── loader.py       # Loads module:function tasks and .csv/.jsonl/.txt inputs
│   └── cli.py          # run, status, retry and export commands
├── tests/              # pytest suite with a fake clock for time-based behavior
├── examples/           # Sample tasks and input files
├── docs/
│   ├── cli.md          # Every option and JSON output shape
│   └── design.md       # Design decisions and rejected alternatives
├── .github/workflows/
│   └── ci.yml          # Lint, type check and tests on every push
├── llms.txt            # Short tool summary for LLM agents
├── pyproject.toml
└── README.md
```

<br>

## Getting Started

Requires Python 3.11+ and has no runtime dependencies.

```bash
pip install git+https://github.com/jin-ninini/resumable-runner
resumable run examples/tasks.py:word_stats --input examples/items.csv
resumable status
resumable retry
resumable export --status done -o results.jsonl
```

A task is a function that takes one item (a `dict`) and returns a JSON-serializable result, or raises.

```python
def word_stats(item):
    return {"letters": len(item["word"])}
```

| Command | What it does |
|---|---|
| `resumable run TASK [--input FILE]` | Adds new items from FILE, then processes every pending item |
| `resumable status` | Shows item counts by status and the first failures |
| `resumable retry` | Moves failed items back to pending |
| `resumable export [--status S] [-o FILE]` | Writes items with results and errors as JSON lines |

- Every command takes `--state FILE` (default `.resumable.db`) and `--json`
- Exit codes: `0` nothing left to do, `1` failed or unfinished items remain, `2` bad arguments or unreadable input
- Run options such as `--max-attempts`, `--min-interval` and `--max-consecutive-failures` are listed in [docs/cli.md](docs/cli.md)

For development:

```bash
git clone https://github.com/jin-ninini/resumable-runner && cd resumable-runner
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

<br>

## Notes

- SQLite replaces a JSON progress file because one committed transaction per status change cannot be corrupted by a crash
- Items run sequentially on purpose: remote rate limits are the bottleneck, and one writer keeps the state simple
- Duplicate keys in one input file are rejected, since they usually point to an upstream join or export bug
- Future improvements: parallel workers over separate state files, and per-item timeouts
- Full reasoning for each decision is in [docs/design.md](docs/design.md)

<br>

## License

MIT License. Copyright © 2026 Hyunjin Hwang. See [LICENSE](LICENSE).
