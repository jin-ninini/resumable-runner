# resumable-runner

[![CI](https://github.com/jin-ninini/resumable-runner/actions/workflows/ci.yml/badge.svg)](https://github.com/jin-ninini/resumable-runner/actions/workflows/ci.yml)

Run a Python function over many items. Stop any time, rerun the same command, and it picks up where it left off.

```bash
resumable run examples/tasks.py:fetch_title --input examples/urls.csv --min-interval 1
```

## Why this exists

During a data internship I collected place, menu and review data for hundreds of thousands of outlets. A plain loop kept breaking the same way:

- **A crash meant starting over.** Hours of finished requests were lost or had to be redone.
- **Retry logic leaked into every script.** Each crawler reinvented backoff, failure lists and "where was I?" files.
- **Blocking went unnoticed.** When a site started refusing requests, the loop kept failing thousands of items in a row.

I solved this inside that project with a match cache, saved stages, retries and status tracking. This repository rebuilds the pattern from scratch as a small, dependency-free library and CLI, so any batch job gets it for free. No company code or data is included.

## Install

Requires Python 3.11+. No runtime dependencies.

```bash
pip install git+https://github.com/jin-ninini/resumable-runner
# or, for development
git clone https://github.com/jin-ninini/resumable-runner && cd resumable-runner
uv sync
```

## Quick start

1. Write a task: a function that takes one item (a `dict`) and returns something JSON-serializable, or raises.

   ```python
   # tasks.py
   def word_stats(item):
       word = item["word"]
       return {"letters": len(word)}
   ```

2. Run it over a file of items. `--key` names the column that identifies each item (default `id`).

   ```bash
   resumable run tasks.py:word_stats --input examples/items.csv
   # added 5, processed 5: 5 done, 0 failed, 0 skipped (already done)
   ```

3. Interrupt it, rerun it, inspect it.

   ```bash
   resumable run tasks.py:word_stats --input examples/items.csv   # done items are skipped
   resumable status                                               # counts + recent failures
   resumable retry && resumable run tasks.py:word_stats           # give failed items another go
   resumable export --status done -o results.jsonl                # collect results
   ```

Progress lives in one SQLite file (`.resumable.db` by default, change it with `--state`).

### As a library

```python
from resumable import RetryPolicy, Runner, Store

with Store("crawl.db") as store:
    store.add((row["id"], row) for row in rows)  # existing keys are ignored
    report = Runner(
        store,
        fetch_place,
        RetryPolicy(max_attempts=5, base_delay=2),
        min_interval=0.5,
        max_consecutive_failures=20,
    ).run()
print(report.as_dict())
```

## CLI reference

| Command | What it does |
|---|---|
| `resumable run TASK [--input FILE]` | Add new items from FILE (if given), then process every pending item |
| `resumable status` | Item counts by status and the first failures |
| `resumable retry` | Move failed items back to pending |
| `resumable export [--status S] [-o FILE]` | Write items with results and errors as JSON lines |

Every command takes `--state FILE` and `--json`. Exit codes: `0` nothing left to do, `1` failed or unfinished items remain, `2` bad arguments or unreadable input. Full options: [docs/cli.md](docs/cli.md).

`--json` and the exit codes are there so shell scripts, CI jobs and LLM agents can drive the tool without parsing human text. [llms.txt](llms.txt) is a short summary written for LLMs.

## Architecture

```
input file ──► loader ──► Store (SQLite) ◄──► Runner ──► your task(item)
 .csv/.jsonl/.txt         one row per item        retry, backoff,
                          status, attempts,       throttle, breaker
                          error, result
```

| Module | Responsibility |
|---|---|
| [`store.py`](src/resumable/store.py) | Item state machine `pending → running → done / failed`, committed on every change |
| [`runner.py`](src/resumable/runner.py) | Loops over pending items, retries with backoff, throttles calls, stops on a failure streak |
| [`retry.py`](src/resumable/retry.py) | `RetryPolicy`: attempts and exponential backoff |
| [`loader.py`](src/resumable/loader.py) | Resolves `module:function` / `file.py:function` and reads input files |
| [`cli.py`](src/resumable/cli.py) | Thin argparse layer over the library |

## Configuration

| Option | Default | Meaning |
|---|---|---|
| `--max-attempts` | 3 | Tries per item, counting the first |
| `--base-delay` / `--max-delay` | 1s / 30s | Backoff doubles from base up to max |
| `--min-interval` | 0 | Minimum seconds between task calls, for polite crawling |
| `--max-consecutive-failures` | off | Stop the run after N failed items in a row |
| `--limit` | off | Process at most N items, handy for a dry run |

## Testing

```bash
uv run pytest           # unit and CLI tests, with coverage
uv run ruff check .     # lint
uv run ruff format --check .
uv run mypy             # strict type check of src/
```

CI runs all four on Ubuntu and Windows with Python 3.11, 3.12 and 3.13, then smoke-tests the CLI. Time-based behavior (backoff, throttling) is tested with a fake clock, so the suite never sleeps.

## Design decisions

Short version below. Reasons and rejected alternatives are in [docs/design.md](docs/design.md).

- **SQLite, not a JSON progress file.** Every status change is one committed transaction, so Ctrl+C or a crash can never corrupt progress.
- **Items left `running` are recovered on the next start.** An interrupted item is simply tried again.
- **Adding input is idempotent.** Rerunning with the same file never duplicates work, and duplicate keys inside one file are rejected loudly.
- **Sequential by design.** Rate limits on the remote side are the bottleneck for crawling and API jobs. One writer keeps the state simple and correct.
- **A circuit breaker instead of silent failure.** `--max-consecutive-failures` stops the run when a site starts blocking you, leaving untouched items pending for later.
- **Standard library only.** Nothing to install beyond Python, which keeps the tool easy to drop into any environment.

## License

MIT
