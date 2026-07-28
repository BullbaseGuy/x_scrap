# W02 result — Dependency and adapter contract

Status: PASS

## Implemented

- pinned `twscrape==0.19.2` behind `TwscrapeAdapter`;
- recorded MIT/Python/API/raw-page evidence and the no-copy decision;
- kept the upstream import lazy and produced an actionable missing-dependency error;
- forced both `TWS_TELEMETRY=0` and `DO_NOT_TRACK=1` before importing upstream code;
- added exact, non-empty Cookie parsing and single-line account-label validation;
- redacted `auth_token` and `ct0` from account and exception text;
- classified rate-limit, authentication, transient, and upstream-schema failures conservatively;
- retained upstream reset time when exposed by an exception;
- documented that full page-level response and cursor persistence remain W03 work.

## Validation

On commit `3fe42239096580cb21207ef24aad7854480a1e45`:

- compile: PASS;
- Ruff: PASS;
- deterministic tests: PASS;
- repository-full Product Gate: PASS;
- canonical task-state validation: PASS;
- repository secret audit: PASS.

A stale security assertion that still expected the former `setdefault` implementation was diagnosed and updated after the first W02 test run. No failed action was repeated without a changed hypothesis.

## Security and cost

- real X credentials used: 0;
- live authenticated X requests: 0;
- paid API calls: 0;
- paid proxy calls: 0;
- Codex calls: 0.

No human action was required.
