# Status

- Task: `x-user-timeline-v1`
- Branch: `feature/x-user-timeline-v1`
- Control issue: #1
- Draft PR: #2
- Current stage: W07
- Status: RUNNING
- Codex calls: 0
- Paid API calls: 0
- Paid proxy calls: 0

## Completed

- W00 contract, completeness boundary, risks, and master plan.
- W01 Python package, repository structure, Devflow state, deterministic gates, and read-only permanent CI workflows.
- W02 pinned `twscrape==0.19.2`, adapter isolation, telemetry shutdown, Cookie validation, account-output redaction, and upstream error classification.
- W03 raw JSON page evidence, content-addressed immutable artifacts, page-to-post provenance, atomic SQLite page commits, cursor checkpoints, terminal-page recovery, and distinct cross-page statistics.
- W04 no-echo local Cookie acquisition, centralized redaction, Git-worktree refusal, private POSIX modes, hardened atomic local writes, and documented Windows/plaintext-SQLite guarantees.
- W05 independently resumable recent timeline scopes, stable-user-ID and fixed-range filtering, native-repost scope locking, protected/unavailable target handling, suspicious-empty detection, and profile snapshot round-trip hardening.
- W06 canonical resolved-username search, stable-user-ID enforcement, whole-second half-open windows, integer midpoint splits, noisy-result filtering, dense-window recursion, and independent child-scope resume.
- The W06 deterministic suite contains 69 tests; the atomic apply workflow runs compile, Ruff, pytest, state validation, and secret audit before publishing this stage transition.

## In progress

- W07 exact cross-layer coverage consistency across windows, scopes, pages, posts, and raw evidence.
- Same-ID normalized payload conflict detection and explicit `SOURCE_CONFLICT` handling.
- Atomic, reproducible export bundles with inventories, checksums, stable ordering, and redacted error/event summaries.

## Known limitations

- No authenticated live X request has been run in GitHub Actions or this development environment.
- Search and timeline completeness describe the currently observable source surface; deleted, protected, suspended, de-indexed, or search-suppressed posts may remain unavailable.
- Real account challenge and rate-limit reset behavior remains reserved for the later local opt-in W09 E2E gate.
