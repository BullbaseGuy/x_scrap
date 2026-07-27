# Architecture

## Goals

The first product slice must be local-first, resumable at a committed page boundary, deterministic under test, and explicit about source limitations. The upstream X integration is replaceable and unstable.

## Components

```text
CLI
 │
 ▼
UserExportService ──────────────────────────────┐
 │                                              │
 ├─ resolve stable user ID                     ├─ heartbeat / retry policy
 ├─ collect recent timeline pages              │
 ├─ plan historical windows                    │
 ├─ recursively split cursor-limited windows   │
 └─ finalize coverage                          │
 │                                              │
 ▼                                              ▼
CollectorAdapter                           SQLite
 │                                         ├─ jobs / windows / events
 ▼                                         ├─ harvest_scopes / harvest_pages
TwscrapeAdapter                            ├─ harvest_page_posts
 │                                         └─ user snapshots / normalized posts
 ├─ *_raw page methods                           │
 ├─ raw JSON + parsed posts                      ├─ page cursor checkpoint
 └─ stable project exceptions                    └─ page-to-post provenance
 │
 ▼
X web GraphQL/Search

Content-addressed raw JSON pages
 │
 ▼
JSONL / CSV / manifest / profile / coverage / summary
```

## Adapter boundary

`CollectorAdapter` exposes page-level operations:

- resolve a username to a stable user object;
- stream recent user-post pages;
- stream user-post-plus-reply pages;
- stream historical search pages.

Every `CollectorPage` contains the source, operation, request cursor, next cursor, parsed items, raw JSON response body, capture time, and local page index. All `twscrape` imports, private-operation assumptions, raw response parsing, cookie setup, telemetry controls, and upstream exception heuristics live in `TwscrapeAdapter`. A future `twikit`, official archive, or other lawful adapter should not change the harvesting core.

## Job lifecycle

1. Normalize the username and create or resume a job.
2. Freeze the cutoff at job creation.
3. Resolve and persist the profile snapshot and stable user ID.
4. Resume each recent-timeline scope from its committed cursor.
5. Create contiguous historical search windows.
6. Resume one leaf window from its committed cursor and remaining item budget.
7. Write the raw page body to an immutable content-addressed gzip artifact.
8. In one SQLite transaction, commit page metadata, normalized post upserts, page-to-post links, and the next cursor.
9. If a next cursor remains at the window budget, split the window into two children.
10. Audit leaf windows for unresolved states and time gaps.
11. Export only from committed SQLite records.

A crash after the artifact write but before the SQLite transaction can leave an unreferenced content-addressed file. It cannot overwrite committed evidence, and resume safely reuses or supersedes it. SQLite is the authority for whether a page was committed.

## Window and cursor semantics

Windows are half-open intervals `[start, end)`, encoded in search with `since_time` and `until_time`. The planner creates adjacent intervals with no intentional gap. Parsed posts outside the exact interval are rejected even if the upstream search returns them at a boundary.

A window is complete only when its page scope is exhausted and no next cursor remains. If a cursor remains when the configured page-item budget is consumed, the parent becomes `SPLIT` and two child windows are created. If the smallest allowed window still has a remaining cursor, it becomes `PARTIAL_LIMIT_REACHED` and the final coverage result is partial.

Source exhaustion proves traversal of the observable source surface at collection time. It does not prove recovery of deleted, protected, suspended, de-indexed, or search-suppressed content.

## Persistence and idempotency

- `jobs` stores lifecycle, fixed range, output path, and terminal error.
- `windows` stores every historical partition, attempt count, observed range, and terminal reason.
- `harvest_scopes` stores a source/window state, next cursor, and next page index.
- `harvest_pages` stores operation metadata, cursor pair, page counts, raw artifact path, compressed SHA-256, and observed post-time range.
- `harvest_page_posts` links every accepted normalized post to every page where it appeared.
- `posts` uses `(job_id, post_id)` as its primary key.
- `user_snapshots` stores the profile used for the task.
- `events` stores lifecycle and recovery events.

The page row, post upserts, provenance links, and cursor advancement share one SQLite transaction. A duplicate page with the same page index and payload hash is idempotent. A different payload at an already committed index, repeated cursor, mismatched request cursor, or duplicate page payload is rejected. Scope statistics count distinct post IDs across pages, so repeated search results do not inflate window counts.

Scope states distinguish:

- `PENDING`: no page committed yet;
- `RUNNING`: a next cursor is available;
- `EXHAUSTED`: a terminal page was committed but final scope completion may not yet be recorded;
- `LIMIT_REACHED`: traversal paused with a remaining cursor because of the configured budget;
- `FAILED`: the last attempt ended in an error, while its committed cursor remains resumable;
- `COMPLETE`: traversal reached source exhaustion and was finalized.

This distinction prevents a crash immediately after a terminal page from restarting at the first page.

## Raw evidence

Raw files use:

```text
raw/<job_id>/pages/<sanitized-scope>/page-<index>-<sha-prefix>.json.gz
```

Only the stable JSON response body is stored in the gzip artifact. Capture time, operation, cursors, and page index remain in SQLite, so volatile metadata does not change the content hash. The writer uses a temporary file plus atomic replacement and refuses to overwrite a fixed path with different content.

## Error classes

| Class | Outcome |
|---|---|
| Rate limited | Save state, bounded wait/retry, then resume from the committed cursor |
| Transient upstream failure | Exponential backoff within budget, then resume |
| Authentication or challenge | `HUMAN_REQUIRED`; no bypass |
| GraphQL/schema change | `UPSTREAM_SCHEMA_CHANGED`; repair adapter |
| Minimum window still has a cursor | `PARTIAL_UNRESOLVED_WINDOWS` |
| Unknown failure | `FAILED` with type and message |

## Security boundaries

- The Git repository contains no X cookie, password, account DB, collected dataset, or raw JSON capture.
- Local account and job databases live under `X_SCRAP_HOME`.
- Telemetry is forcibly disabled before importing `twscrape`.
- CI never performs an authenticated live X request.
- The project does not automate email verification, CAPTCHA handling, account creation, or protected-content access.
