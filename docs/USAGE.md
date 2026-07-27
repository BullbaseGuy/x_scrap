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

The prompt accepts a one-line cookie header containing `auth_token=...; ct0=...`. The command rejects missing fields and embedded newlines. `x-scrap auth list` shows only label, active state, last-used time, and redacted error state; it does not print cookie material.

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
| `--max-posts-per-window` | Page-item budget; a remaining cursor triggers a split |
| `--timeline-limit` | Optional recent-timeline limit; `-1` means source exhaustion |

## 4. Inspect jobs

```powershell
x-scrap jobs list
x-scrap jobs show <job_id>
```

Typical states include `RUNNING`, `WAITING_RATE_LIMIT`, `HUMAN_REQUIRED`, `COMPLETED`, `PARTIAL`, `FAILED`, and `UPSTREAM_SCHEMA_CHANGED`.

## 5. Recovery behavior

- SQLite WAL and transactional page commits protect committed state.
- The page row, accepted post upserts, page-to-post links, and next cursor commit together.
- Post IDs are the normalized-record idempotency key.
- Raw page bodies are content addressed and cannot overwrite committed evidence.
- A fixed cutoff prevents a long job from chasing newly published posts forever.
- Resume starts at the next committed cursor and page index, not at the beginning of the source or window.
- If a terminal page was committed immediately before interruption, resume finalizes that scope without querying page one again.
- Completed windows are skipped on resume.
- A window that still has a cursor at the configured item budget is recursively split.
- Repeated infrastructure errors stop after the bounded retry budget.
- Login challenges and expired cookies become a human gate instead of being bypassed.

## 6. Raw page evidence

For each committed page, the local raw store contains:

```text
raw/<job_id>/pages/<scope>/page-<index>-<hash>.json.gz
```

The gzip payload is the stable JSON body supplied by the adapter's raw page method. SQLite records its SHA-256, local path, byte size, source operation, request cursor, next cursor, page index, capture time, and accepted post IDs. HTTP headers are not preserved. An unreferenced content-addressed file can remain if the process stops between the file write and SQLite commit; only artifacts referenced from `harvest_pages` are committed evidence.

## 7. Interpreting completeness

`COMPLETE_PUBLICLY_RETRIEVABLE` means every planned search leaf window reached a terminal complete state, every committed page has an auditable cursor transition, and there are no time gaps. It does not mean deleted or otherwise unavailable posts were recovered.

`PARTIAL_UNRESOLVED_WINDOWS` means one or more leaf windows are failed, still have a cursor at the minimum size, or are otherwise unresolved. Read `coverage.json` before using the dataset as complete.

## 8. Credential and file protection

The Cookie must be entered through the no-echo prompt. Supplying it as a command-line argument is unsupported and rejected by the parser. This keeps it out of PowerShell history and process metadata.

`X_SCRAP_HOME` cannot be located inside a Git worktree. On POSIX systems, runtime directories are set to `0700` and databases/evidence/exports to `0600`. On Windows, select a directory protected by the current user's ACL; the application does not claim or add encryption.

The session database contains local plaintext browser-session material. Back it up only to an encrypted location, never commit it, and rotate the X session after suspected disclosure.
