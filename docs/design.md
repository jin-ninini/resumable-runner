# Design decisions

## Where state lives: SQLite

**Chosen:** one SQLite file, one row per item, committed after every status change.

**Rejected:** a JSON or CSV "done list" rewritten every N items. A crash during the rewrite can corrupt the file, and anything finished since the last write is lost. SQLite gives atomic updates from the standard library.

## Recovering from interruptions

An item is marked `running` before the task is called. If the process dies, the item stays `running`. On the next start, `Store.recover()` moves every `running` item back to `pending`. The cost is that an interrupted item runs again, so tasks should be safe to repeat. For read-only work such as crawling, they already are.

## Idempotent input

`Store.add()` uses `INSERT OR IGNORE`, so running the same command with the same input file twice adds nothing. Existing items are never overwritten. A later input file can't silently reset finished work.

Duplicate keys inside one input file are rejected instead of being deduplicated. In practice duplicates usually mean a join or export bug upstream, and it is better to find it before spending hours of requests.

## Retries and backoff

Each failed attempt waits `base_delay * backoff ** (attempt - 1)` seconds, capped at `max_delay`. Retries happen immediately for the same item, not at the end of the queue, so the attempt count and the last error stay attached to the item.

Any `Exception` raised by the task counts as a failed attempt. `KeyboardInterrupt` and `SystemExit` are not caught, so Ctrl+C stops the run at once and recovery handles the rest.

## Circuit breaker

When a site starts blocking requests, every remaining item fails, and the retries make it worse. `max_consecutive_failures` stops the run after N failed items in a row. One success resets the count. Untouched items stay `pending`, so `resumable run` continues later.

## Sequential execution

The runner calls the task one item at a time. For crawling and API jobs the limit is the remote rate limit, not local CPU. Concurrency would add locking around SQLite and make throttling harder to reason about. If a job ever needs parallelism, the plan is to run several processes over separate state files, not threads over one.

## Results must be JSON

Results are stored as JSON so `export` can write them as JSON lines and any tool can read them. A result that cannot be serialized marks the item failed with a clear error, instead of crashing the whole run.

## Interface for scripts and agents

Every command takes `--json` and uses fixed exit codes (`0` done, `1` unfinished, `2` usage error). A CI job or an LLM agent can then call `resumable status --json`, read the counts, and decide whether to call `retry`, without parsing English text. `llms.txt` describes the tool in the format LLM tools look for.

## Testing time without waiting

`Runner` accepts `sleep` and `clock` functions. Tests pass a fake clock that records requested sleeps and advances virtual time. Backoff and throttling are verified exactly, and the suite runs in about a second.
