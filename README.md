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

Resume is enabled by default. Re-running the same command reuses the latest unfinished job, its fixed cutoff, committed pages, next cursor, completed windows, and deduplicated posts. A 429 wait is persisted separately from transient 502/timeout retry counters, so a valid reset wait does not exhaust the infrastructure budget. If an export directory was already atomically published immediately before interruption, resume verifies and finalizes that bundle without another X request. Use `--no-resume` only when a new independent snapshot is required.

## Output

Each task is first written to a private staging directory, validated, and then atomically published as:

```text
exports/<username>/<job_id>/
├── manifest.json
├── profile.json
├── coverage.json
├── windows.json
├── scopes.json
├── tweets.jsonl
├── tweets.csv
├── pages.jsonl
├── conflicts.jsonl
├── events.jsonl
├── errors.jsonl
├── summary.md
└── inventory.json
```

`inventory.json` contains deterministic byte sizes, SHA-256 values, record counts, source counts, scope/window state summaries, and known source limitations. The bundle validator requires JSONL/CSV identity, string IDs, UTC timestamps, stable ordering, matching counts/statuses, and no untracked files before publication.

A material same-ID difference in author, timestamp, text, conversation, reply, quote, or repost relations is preserved in `conflicts.jsonl`; the first canonical payload is not overwritten and coverage becomes `SOURCE_CONFLICT`. Volatile engagement counters do not create false conflicts.

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

For the opt-in authenticated validation stage, use `docs/implementation/x-user-timeline-v1/W09_LIVE_RUNBOOK.md`; its tooling writes only sanitized evidence and is never invoked by CI. On Windows, the complete small/interruption/resume/higher-volume sequence is one command:

```powershell
.\scripts\live\run_w09.ps1 `
  -Home D:\x_scrap_private `
  -SmallUsername <PUBLIC_USERNAME> `
  -VolumeUsername <PUBLIC_USERNAME>
```

The acceptance tool binds resume to a private interruption checkpoint, verifies that committed page hashes were preserved and the first new page used the persisted cursor, then writes `W09_ACCEPTANCE.json` under the private state directory.
