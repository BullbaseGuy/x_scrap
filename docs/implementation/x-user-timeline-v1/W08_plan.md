# W08 plan — Fault and automatic recovery matrix

1. Separate expected rate-limit waits from bounded transient-infrastructure retries.
2. Use upstream reset timestamps when available, adding a small safety margin instead of repeatedly probing before reset.
3. Resume both recent timeline scopes and historical search windows from their last atomically committed cursor.
4. Track normalized root causes so one unchanged transient failure cannot be retried blindly beyond policy.
5. Preserve a high but finite per-scope rate-limit wait budget to avoid an infinite loop caused by a broken upstream response.
6. Persist wait, retry, and exhausted-budget events without credential leakage.
7. Verify that schema changes, authentication challenges, and unavailable targets are not treated as recoverable empty results.
8. Re-run transaction rollback, cursor-loop, immutable evidence, export rollback, and process-resume coverage.

Exit criteria: rate limits wait and resume automatically, recoverable transient failures resume from committed cursors, unchanged failures stop within policy, and non-recoverable classes are never blindly retried.
