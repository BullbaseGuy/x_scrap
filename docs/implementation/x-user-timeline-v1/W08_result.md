# W08 result — Fault and automatic recovery matrix

Status: PASS (deterministic local validation)

## Implemented

- `RecoveryBudget` separates `RATE_LIMIT` and `TRANSIENT` categories per harvest scope;
- 429 recovery uses the adapter-provided UTC reset time plus a configurable safety margin, with exponential fallback only when no reset is known;
- rate-limit waits do not consume the transient-infrastructure or same-root-cause budget;
- recent `UserTweets` and `UserTweetsAndReplies` scopes retry automatically from the cursor written by the last committed page;
- historical windows retain independent recovery budgets and resume their own scope cursor;
- transient failures are normalized into redacted root-cause fingerprints; total and unchanged-root budgets are both enforced;
- the default rate-limit budget is deliberately high but finite, preventing an infinite loop if an upstream endpoint continuously reports unusable limits;
- `RATE_LIMIT_WAIT`, `TRANSIENT_RETRY`, and `RECOVERY_EXHAUSTED` events record category, attempt, delay, reset, scope, window, and redacted root cause;
- an exhausted recovery budget marks the affected window failed and terminates with the original typed error;
- `UpstreamChanged`, authentication, and target-unavailable failures remain outside automatic retry.

## Deterministic fault coverage

- timeline stream commits one page, fails transiently, and automatically resumes at the next cursor;
- search receives one 429 with a reset timestamp, waits exactly through reset plus safety margin, then completes;
- three occurrences of one unchanged transient root cause stop after the configured two retries;
- a GraphQL/schema change is attempted once and transitions directly to `UPSTREAM_SCHEMA_CHANGED`;
- existing tests continue to cover repeated cursors, conflicting page payloads, interrupted SQLite transactions, terminal-page interruption, dense child-window resume, immutable artifact protection, and atomic export rollback.

## Validation

- Python compile: PASS;
- pytest: PASS (83 tests across W00-W09 preflight coverage);
- canonical task-state validation: PASS before stage transition;
- repository secret audit: PASS.

Ruff and the complete repository Product Gate are executed by the atomic apply workflow before publication.

## Security and cost

- real X credentials used: 0;
- authenticated live X requests: 0;
- paid API calls: 0;
- paid proxy calls: 0;
- Codex calls: 0.

No human action was required.
