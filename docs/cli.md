# CLI reference

```
resumable [--version] COMMAND [options]
```

All commands accept:

| Option | Default | Description |
|---|---|---|
| `--state FILE` | `.resumable.db` | SQLite file that stores progress |
| `--json` | off | Print one JSON object instead of human-readable text |

Exit codes: `0` no pending, running or failed items; `1` some remain; `2` bad arguments or unreadable input.

## `resumable run TASK`

Adds items from `--input` (optional) and processes every pending item.

`TASK` is `module:function` (importable module) or `path/to/file.py:function`.
The function receives one item's payload as a `dict` and must return a JSON-serializable value or raise.

| Option | Default | Description |
|---|---|---|
| `--input FILE` | none | `.csv`, `.jsonl` or `.txt`. Existing keys are ignored. |
| `--key COLUMN` | `id` | Column that identifies an item (`.csv`, `.jsonl`). For `.txt`, each line is the key and the payload is `{"value": line}`. |
| `--max-attempts N` | 3 | Tries per item, including the first |
| `--base-delay S` | 1.0 | Wait after the first failed attempt |
| `--max-delay S` | 30.0 | Upper bound for any wait |
| `--min-interval S` | 0.0 | Minimum seconds between task calls |
| `--max-consecutive-failures N` | off | Stop after N failed items in a row |
| `--limit N` | off | Process at most N items in this run |

JSON output:

```json
{
  "added": 5,
  "report": {"processed": 5, "succeeded": 4, "failed": 1, "skipped": 0,
             "stopped_early": false, "stop_reason": null},
  "summary": {"total": 5, "pending": 0, "running": 0, "done": 4, "failed": 1}
}
```

Per-item progress (`[done]`, `[retry]`, `[failed]`) goes to stderr in text mode.

## `resumable status`

Shows counts by status and up to 10 failures with their last error.

```json
{"summary": {"total": 5, "pending": 0, "running": 0, "done": 4, "failed": 1},
 "failed": [{"key": "missing", "error": "URLError: <urlopen error ...>"}]}
```

## `resumable retry`

Moves every failed item back to pending. Run `resumable run TASK` afterwards to process them.

```json
{"requeued": 1, "summary": {"total": 5, "pending": 1, "running": 0, "done": 4, "failed": 0}}
```

## `resumable export`

Writes one JSON object per item: `key`, `status`, `attempts`, `error`, `result`.

| Option | Description |
|---|---|
| `--status {pending,running,done,failed}` | Only items with this status |
| `-o, --output FILE` | Write to a file instead of stdout |
