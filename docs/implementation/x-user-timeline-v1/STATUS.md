# Status

- Task: `x-user-timeline-v1`
- Branch: `feature/x-user-timeline-v1`
- Control issue: #1
- Draft PR: #2
- Current stage: W05
- Status: RUNNING
- Codex calls: 0
- Paid API calls: 0
- Paid proxy calls: 0

## Completed

- W00 contract, completeness boundary, risks, and master plan.
- W01 Python package, repository structure, Devflow state, deterministic gates, and read-only permanent CI workflows.
- W02 pinned `twscrape==0.19.2`, adapter isolation, telemetry shutdown, Cookie validation, account-output redaction, and upstream error classification.
- W03 raw JSON page evidence, content-addressed immutable artifacts, page-to-post provenance, atomic SQLite page commits, cursor checkpoints, terminal-page recovery, and distinct cross-page statistics.
- W04 removed Cookie argv input, added no-echo acquisition and centralized redaction, rejected state inside Git worktrees, applied private POSIX modes, hardened atomic local writes, and documented Windows/plaintext-SQLite guarantees.
- The W04 apply workflow verified its payload by SHA-256, ran compile, Ruff, 51 tests, state validation, and secret audit, then removed every temporary upload and write-capable workflow surface in the same product commit `919dec3054d2aee16a8e38bd6dd24c145c5c5a61`.

## In progress

- W05 independently resumable `UserTweets` and `UserTweetsAndReplies` scopes.
- Stable-user-ID, fixed-start, and fixed-cutoff filtering.
- Deterministic validation of replies, quote posts, native repost policy, duplicate surfaces, terminal pages, protected users, and interrupted-page resume.

## Known limitations

- No authenticated live X request has been run in GitHub Actions or this development environment.
- Search and timeline completeness describe the currently observable source surface; deleted, protected, suspended, de-indexed, or search-suppressed posts may remain unavailable.
- Real account challenge and rate-limit behavior remains reserved for the later local opt-in W09 E2E gate.
