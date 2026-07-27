# Upstream dependency decision

## Decision

Use `twscrape==0.19.2` behind `TwscrapeAdapter` for the first product slice. Keep `twikit` as a possible secondary adapter, not a runtime dependency.

## Evidence reviewed

At the reviewed upstream revision, `twscrape`:

- is MIT licensed and supports Python 3.12;
- exposes asynchronous user lookup, user timeline, user timeline-with-replies, and search methods;
- supports browser-cookie account setup with `auth_token` and `ct0`;
- stores account sessions in SQLite;
- exposes parsed models and raw-response variants;
- waits or rotates when an operation-specific account is rate limited;
- can disable telemetry with `TWS_TELEMETRY=0` or `DO_NOT_TRACK=1`.

## Why not copy the implementation

X's private operation IDs, feature flags, transaction headers, and response shapes change frequently. Copying those internals would create a second maintenance burden and lose upstream fixes. `x_scrap` therefore owns only:

- the stable adapter contract;
- resumable orchestration;
- time partitioning;
- persistence and deduplication;
- completeness auditing;
- exports and security policy.

## Pinned version and upgrade policy

The initial pin is exact so a passing task is reproducible. An upgrade requires:

1. adapter contract tests;
2. sanitized fixture tests;
3. secret audit;
4. a local opt-in live smoke test;
5. a documented upstream change note.

An upstream operation or schema failure must not be interpreted as an empty timeline.

## Known gap at this stage

The implemented collector stores the normalized source payload for every accepted post. Full page-level HTTP response preservation through the upstream `_raw` methods remains a tracked hardening task. Until that is complete, repository documentation must call these files "normalized model artifacts," not raw HTTP responses.
