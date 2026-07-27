# Architecture

## Goals

The first product slice must be local-first, resumable, deterministic under test, and explicit about source limitations. The upstream X integration is treated as replaceable and unstable.

## Components

```text
CLI
 │
 ▼
UserExportService ───────────────┐
 │                              │
 ├─ resolve stable user ID      ├─ heartbeat / retry policy
 ├─ collect recent timelines    │
 ├─ plan historical windows     │
 ├─ recursively split saturation│
 └─ finalize coverage           │
 │                              │
 ▼                              ▼
CollectorAdapter             SQLite jobs/windows/posts/events
 │                              │
 ▼                              ├─ idempotent post upsert
TwscrapeAdapter                 ├─ fixed cutoff
 │                              └─ resumable window state
 ▼
X web GraphQL/Search

SQLite + normalized artifacts
 │
 ▼
JSONL / CSV / manifest / profile / coverage / summary
```

## Adapter boundary

`CollectorAdapter` is deliberately small:

- resolve a username to a stable user object;
- stream user posts;
- stream user posts plus replies;
- stream search results.

All imports, exception heuristics, cookie setup, and upstream object assumptions for `twscrape` live in `TwscrapeAdapter`. A future `twikit` or official-archive adapter should not change the harvesting core.

## Job lifecycle

1. Normalize the username and create or resume a job.
2. Freeze the cutoff at job creation.
3. Resolve and persist the profile snapshot and stable user ID.
4. Collect both recent timeline surfaces.
5. Create contiguous historical search windows.
6. Process one leaf window at a time.
7. If the source budget is reached, split the window into two child windows.
8. Upsert every post by string ID and merge source provenance.
9. Audit leaf windows for unresolved states and time gaps.
10. Export only from committed SQLite records.

## Window semantics

Windows are half-open intervals `[start, end)`, encoded in search with `since_time` and `until_time`. The planner creates adjacent intervals with no intentional gap. A saturated window is replaced by two children; the parent is retained as `SPLIT` for audit history but excluded from leaf coverage.

The current implementation uses source exhaustion below the configured limit as the terminal signal. Because X search can silently omit content, this proves traversal of the observable source surface, not recovery of deleted or unindexed data.

## Persistence and idempotency

- `jobs` stores the lifecycle, fixed range, output path, and terminal error.
- `windows` stores every historical partition, attempt count, observed range, and terminal reason.
- `posts` uses `(job_id, post_id)` as its primary key.
- `user_snapshots` stores the profile used for the task.
- `events` stores lifecycle and recovery events.

A duplicate post updates its latest normalized payload and merges the sorted source set. This makes replay safe after an interrupted page or window.

## Error classes

| Class | Outcome |
|---|---|
| Rate limited | Save state, bounded wait/retry, then resume |
| Transient upstream failure | Exponential backoff within budget |
| Authentication or challenge | `HUMAN_REQUIRED`; no bypass |
| GraphQL/schema change | `UPSTREAM_SCHEMA_CHANGED`; repair adapter |
| Minimum window still saturated | `PARTIAL_UNRESOLVED_WINDOWS` |
| Unknown failure | `FAILED` with type and message |

## Security boundaries

- The Git repository contains no X cookie, password, account DB, collected dataset, or raw network capture.
- Local account and job databases live under `X_SCRAP_HOME`.
- Telemetry is disabled before importing `twscrape`.
- CI never performs an authenticated live X request.
- The project does not automate email verification, CAPTCHA handling, account creation, or protected-content access.
