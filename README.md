# x_scrap

`x_scrap` is a local-first, resumable, and auditable framework for collecting public data from X.com.

The first milestone exports the currently publicly retrievable posts authored by one public account. It combines the recent user timelines with date-partitioned search, stores progress in SQLite, preserves page-level JSON evidence, deduplicates by post ID, and resumes after interruption from the next committed cursor.

> [!WARNING]
> This project uses X's web-facing interfaces through an open-source compatibility adapter rather than a supported free official API. X can change those interfaces without notice, and use may be restricted by X's terms or account controls. Use only accounts and data you are authorized to access. The project does not bypass login challenges, CAPTCHAs, protected accounts, or other access controls.

## Current scope

Included by default:

- original posts;
- replies, including self-replies and threads;
- quote posts;
- text, timestamps, IDs, relations, metrics, media metadata, and source provenance;
- a fixed task cutoff, time-window coverage report, and content-addressed page evidence;
- automatic wait/retry for bounded recoverable errors;
- idempotent resume from the latest unfinished job and its next committed page cursor.

Not promised as recoverable:

- deleted, removed, suspended, protected, de-indexed, or search-suppressed content;
- a complete history of native reposts;
- content unavailable to the authenticated account;
- uninterrupted compatibility after X changes its private GraphQL schema.

## Install

Python 3.12 is the supported project runtime.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

All credentials and collected data are stored outside the repository. The default Windows home is `%LOCALAPPDATA%\x_scrap`. Override it with `X_SCRAP_HOME` or `--home`.

```powershell
$env:X_SCRAP_HOME = 'D:\x_scrap_data'
$env:TWS_TELEMETRY = '0'
```

## Add a browser-cookie session

Open X.com in your own browser, copy the `auth_token` and `ct0` cookie values, then add them locally. The command always uses a no-echo prompt so the Cookie is not placed in shell history or process arguments.

```powershell
x-scrap auth add-cookie --label primary
x-scrap auth list
```

The cookie database is never uploaded by the supplied GitHub Actions workflows.

## Export one account

```powershell
x-scrap user export --username xdevelopers
```

Explicit historical range and tuning example:

```powershell
x-scrap user export `
  --username xdevelopers `
  --start 2007-01-01T00:00:00Z `
  --cutoff 2026-07-27T00:00:00Z `
  --initial-window-days 30 `
  --min-window-seconds 3600 `
  --max-posts-per-window 5000
```

Resume is enabled by default. Re-running the same command reuses the latest unfinished job, its fixed cutoff, committed pages, next cursor, completed windows, and deduplicated posts. Use `--no-resume` only when a new independent snapshot is required.

## Output

Each task writes normalized exports:

```text
exports/<username>/<job_id>/
├── manifest.json
├── profile.json
├── tweets.jsonl
├── tweets.csv
├── coverage.json
└── summary.md
```

The corresponding page evidence is stored separately:

```text
raw/<job_id>/pages/<scope>/
└── page-<index>-<content-hash>.json.gz
```

Each gzip file contains only the stable JSON response body returned by the adapter's raw page method. SQLite stores the operation, request cursor, next cursor, page index, capture time, compressed SHA-256, artifact path, and the accepted post IDs linked to that page. Files are content addressed and written atomically, so a rejected retry cannot overwrite already committed evidence. HTTP headers and transport traces are not claimed as preserved.

## Development workflow

The repository follows the Devflow conventions derived from `BullbaseGuy/demo-project` and the evidence-based execution discipline used by `tyxq428/ashare_f10_scrapper`:

```text
Task contract and plan
        ↓
Feature branch + Draft PR
        ↓
Deterministic tests / state validation / secret audit
        ↓
Recoverable failures diagnosed and retried within budget
        ↓
Human gate only for credentials, account challenge, or material decision
        ↓
Merge only after acceptance and security PASS
        ↓
Exact-main post-merge validation
```

Canonical task state is under `docs/implementation/`. Codex/agent execution and automatic merge are disabled by default.

See [usage](docs/USAGE.md), [architecture](docs/architecture/ARCHITECTURE.md), and [Task #1](https://github.com/BullbaseGuy/x_scrap/issues/1).

## Security model

The Cookie is accepted only through a no-echo prompt; the CLI intentionally has no `--cookie` option. `X_SCRAP_HOME` must be outside a Git worktree. POSIX state directories are restricted to `0700` and files to `0600`; Windows relies on the selected directory's inherited ACL. The local `twscrape` account database is plaintext SQLite protected by OS access controls, not encrypted by this project.

Credential-shaped values are centrally redacted before persisted errors, events, account-list output, and top-level CLI errors. GitHub Actions never receive a real Cookie or collected dataset. See [Security policy](docs/security/SECURITY.md) and [Threat model](docs/security/THREAT_MODEL.md).

## Verified bundle and recovery guarantees

Every completed or partial export is assembled in a private staging directory and published only after `inventory.json` verifies the required files, hashes, byte sizes, record counts, JSONL/CSV identity, string IDs, UTC timestamps, and stable ordering. Material disagreements for one post ID are preserved in `conflicts.jsonl` and produce `SOURCE_CONFLICT`; missing or inconsistent window/scope/page/raw evidence cannot be labeled complete.

Rate limits and transient failures follow separate policies. A known 429 reset time is honored with a safety margin and the same scope resumes from its last committed cursor. Transient errors use bounded exponential retry and a same-root-cause limit. Schema changes and login challenges are not retried as empty data.

The authenticated smoke runner is local-only and refuses CI:

```powershell
python scripts/live/run_user_export_smoke.py --home D:\x_scrap_data --preflight-only
python scripts/live/run_user_export_smoke.py xdevelopers --home D:\x_scrap_data --acknowledge-live-x
```

## Local live acceptance evidence

Authenticated live X testing is never performed in GitHub Actions. For the opt-in W09 acceptance run, follow [`W09_plan.md`](docs/implementation/x-user-timeline-v1/W09_plan.md). After a live job, generate a redacted evidence summary with:

```powershell
python scripts/live/collect_w09_evidence.py `
  --home $env:X_SCRAP_HOME `
  --job-id <job_id>
```

The summary omits Cookie values, authorization headers, raw response bodies, local paths, and plaintext cursor values; cursor resume continuity is represented by fingerprints only.
