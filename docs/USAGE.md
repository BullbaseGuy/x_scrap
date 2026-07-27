# Usage

## 1. Local state

The application resolves its home in this order:

1. `--home PATH`;
2. `X_SCRAP_HOME`;
3. `%LOCALAPPDATA%\x_scrap` on Windows;
4. `~/.local/share/x_scrap` elsewhere.

The home contains `accounts.db`, `jobs.db`, `exports/`, and `raw/`. None belong in Git.

## 2. Authentication

Use a browser session that you own and are authorized to use:

```powershell
x-scrap auth add-cookie --label primary
```

The prompt accepts a one-line cookie header containing `auth_token=...; ct0=...`. The command rejects missing fields and embedded newlines. `x-scrap auth list` shows only label, active state, last-used time, and error state; it does not print cookie material.

## 3. Export

```powershell
x-scrap user export --username <public_username>
```

Important options:

| Option | Meaning |
|---|---|
| `--start` | Inclusive UTC start; defaults to account creation or X's launch boundary |
| `--cutoff` | Exclusive fixed UTC cutoff; defaults to job start |
| `--no-resume` | Start a new job instead of reusing the latest unfinished job |
| `--include-retweets` | Include native reposts without claiming historical completeness |
| `--initial-window-days` | Initial historical search partition size |
| `--min-window-seconds` | Smallest allowed recursive partition |
| `--max-posts-per-window` | Saturation threshold that triggers a split |
| `--timeline-limit` | Optional recent-timeline limit; `-1` means source exhaustion |

## 4. Inspect jobs

```powershell
x-scrap jobs list
x-scrap jobs show <job_id>
```

Typical states include `RUNNING`, `WAITING_RATE_LIMIT`, `HUMAN_REQUIRED`, `COMPLETED`, `PARTIAL`, `FAILED`, and `UPSTREAM_SCHEMA_CHANGED`.

## 5. Recovery behavior

- SQLite WAL and transactional upserts protect committed state.
- Post IDs are the idempotency key.
- A fixed cutoff prevents a long job from chasing newly published posts forever.
- Completed windows are skipped on resume.
- A window that reaches the configured result budget is recursively split.
- Repeated infrastructure errors stop after the bounded retry budget.
- Login challenges and expired cookies become a human gate instead of being bypassed.

## 6. Interpreting completeness

`COMPLETE_PUBLICLY_RETRIEVABLE` means every planned search window has a terminal complete state and there are no time gaps. It does not mean deleted or otherwise unavailable posts were recovered.

`PARTIAL_UNRESOLVED_WINDOWS` means one or more leaf windows are failed, saturated at the minimum size, or otherwise unresolved. Read `coverage.json` before using the dataset as complete.
