# Upstream dependency decision

## Decision

Use `twscrape==0.19.2` behind `TwscrapeAdapter` for the first product slice. Keep `twikit` as a possible secondary adapter, not a runtime dependency.

## Evidence reviewed

The runtime version is exactly pinned in `pyproject.toml`. The source review on 2026-07-27 also inspected upstream `main` at commit `e51d9ad043c8bb15284ca86178740004fa0fc9de` to identify current compatibility behavior without silently changing the runtime pin.

At the reviewed upstream revision, `twscrape`:

- is MIT licensed and supports Python 3.12;
- exposes asynchronous `user_by_login`, `user_tweets`, `user_tweets_and_replies`, and `search` methods;
- exposes page-level `user_tweets_raw`, `user_tweets_and_replies_raw`, and `search_raw` methods;
- supports browser-cookie account setup with `auth_token` and `ct0`;
- stores account sessions and operation locks in SQLite;
- waits for or rotates operation-specific accounts when they are temporarily locked;
- can disable telemetry with `TWS_TELEMETRY=0` or `DO_NOT_TRACK=1`.

## Why not copy the implementation

X's private operation IDs, feature flags, transaction headers, and response shapes change frequently. Copying those internals would create a second maintenance burden and lose upstream fixes. `x_scrap` therefore owns only:

- the stable adapter contract;
- resumable orchestration;
- time partitioning and page checkpoints;
- persistence and deduplication;
- completeness auditing;
- exports and security policy.

## Adapter safeguards

`TwscrapeAdapter` now:

- imports `twscrape` lazily inside adapter construction;
- forces both supported telemetry opt-out variables before the upstream import;
- requires exact, non-empty `auth_token` and `ct0` cookie fields;
- rejects multiline labels and cookie headers;
- never includes cookie fields in account-list output;
- redacts cookie values from upstream account and exception text;
- maps rate limit, authentication/challenge, transient, and schema/operation failures to stable project exceptions;
- preserves a usable upstream rate-limit reset timestamp when one is available.

## Pinned version and upgrade policy

The initial pin is exact so a passing task is reproducible. An upgrade requires:

1. adapter contract tests;
2. sanitized fixture tests;
3. secret audit;
4. a local opt-in live smoke test;
5. a documented upstream change note.

An upstream operation or schema failure must not be interpreted as an empty timeline.

## Known gap after W02

The collector currently stores the normalized source payload for every accepted post. Full page-level HTTP response preservation and next-cursor checkpoints through the upstream `_raw` methods are assigned to W03. Until that is complete, repository documentation must call existing files "normalized model artifacts," not raw HTTP responses.
