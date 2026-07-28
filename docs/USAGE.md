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
- Post IDs are the normalized-record idempotency key; material same-ID differences are preserved as conflicts instead of silently overwriting the first canonical payload.
- Raw page bodies are content addressed and cannot overwrite committed evidence.
- A fixed cutoff prevents a long job from chasing newly published posts forever.
- Resume starts at the next committed cursor and page index, not at the beginning of the source or window.
- If a terminal page was committed immediately before interruption, resume finalizes that scope without querying page one again.
- Completed windows are skipped on resume.
- A window that still has a cursor at the configured item budget is recursively split.
- A 429 persists `wait_until`, waits until the upstream reset plus a bounded safety margin, and does not consume the transient retry budget.
- 502/503/504, timeout, and connection failures use bounded exponential backoff with independent total and same-root-cause limits.
- Committing a page resets transient counters because observable progress was made.
- A process restarted during a persisted wait sleeps only the remaining interval and resumes from the committed cursor.
- If an atomic export was already published before the final database status update, resume verifies and finalizes it without a network request.
- Login challenges and expired cookies become a human gate instead of being bypassed.

## 6. Export bundle

A successful finalization publishes the export directory only after a private staging copy passes its inventory and cross-file checks. It contains normalized posts, exact window and scope state, portable page summaries, material conflicts, redacted events/errors, and `inventory.json`. A failed validation leaves any previous valid export directory untouched.

The portable page summary includes the committed artifact filename, hash, byte size, cursor pair, and counts, but not the absolute local raw-store path. The raw gzip files themselves remain under `X_SCRAP_HOME\raw`.

## 7. Raw page evidence

For each committed page, the local raw store contains:

```text
raw/<job_id>/pages/<scope>/page-<index>-<hash>.json.gz
```

The gzip payload is the stable JSON body supplied by the adapter's raw page method. SQLite records its SHA-256, local path, byte size, source operation, request cursor, next cursor, page index, capture time, and accepted post IDs. HTTP headers are not preserved. An unreferenced content-addressed file can remain if the process stops between the file write and SQLite commit; only artifacts referenced from `harvest_pages` are committed evidence.

## 8. Interpreting completeness

`COMPLETE_PUBLICLY_RETRIEVABLE` requires an exact non-overlapping leaf partition of `[start, cutoff)`, terminal matching search scopes, continuous cursor chains, matching page/link/statistics counts, verified raw gzip sizes and SHA-256 values, complete post provenance, and zero material same-ID conflicts. It does not mean deleted or otherwise unavailable posts were recovered.

`PARTIAL_UNRESOLVED_WINDOWS` means one or more leaves, scopes, cursor chains, page artifacts, normalized records, or provenance relationships remain unresolved or inconsistent.

`SOURCE_CONFLICT` means two committed sources returned materially different normalized author, timestamp, text, or relation data for the same post ID. The first canonical payload and every conflicting payload remain auditable in `conflicts.jsonl`; the job is not labeled complete.

Read `coverage.json` and verify `inventory.json` before using a dataset as complete. Re-running the bundle verifier also rejects changed hashes, changed sizes, JSONL/CSV identity drift, non-string IDs, non-UTC timestamps, or untracked files.

## 9. Credential and file protection

The Cookie must be entered through the no-echo prompt. Supplying it as a command-line argument is unsupported and rejected by the parser. This keeps it out of PowerShell history and process metadata.

`X_SCRAP_HOME` cannot be located inside a Git worktree. On POSIX systems, runtime directories are set to `0700` and databases/evidence/exports to `0600`. On Windows, select a directory protected by the current user's ACL; the application does not claim or add encryption.

The session database contains local plaintext browser-session material. Back it up only to an encrypted location, never commit it, and rotate the X session after suspected disclosure.

For the opt-in authenticated validation stage, use `docs/implementation/x-user-timeline-v1/W09_LIVE_RUNBOOK.md`; its tooling writes only sanitized evidence and is never invoked by CI.

## 10. Authorized local W09 validation

The repository's authenticated live validation is local-only. The Windows orchestrator runs a small fixed-range export, a controlled interruption, a checkpoint-bound resume, a higher-volume range, and cross-report acceptance validation:

```powershell
.\scripts\live\run_w09.ps1 `
  -Home D:\x_scrap_private `
  -SmallUsername <PUBLIC_USERNAME> `
  -VolumeUsername <PUBLIC_USERNAME>
```

The runner refuses CI, requires explicit live acknowledgement, forces telemetry off, requires exactly one active account, and creates new jobs for every case except the checkpoint-bound resume. It stores only sanitized reports under `X_SCRAP_HOME\live-evidence`; Cookies, account databases, raw pages, and exports stay private. See `docs/implementation/x-user-timeline-v1/W09_LIVE_RUNBOOK.md`.
