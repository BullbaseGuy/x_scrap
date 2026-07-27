# Status

- Task: `x-user-timeline-v1`
- Branch: `feature/x-user-timeline-v1`
- Control issue: #1
- Draft PR: #2
- Current stage: W09
- Status: WAITING_HUMAN
- Codex calls: 0
- Paid API calls: 0
- Paid proxy calls: 0
- Authenticated live X calls from development/CI: 0

## Completed

- W00 contract, completeness boundary, risks, and master plan.
- W01 Python package, repository structure, Devflow state, deterministic gates, and read-only permanent CI workflows.
- W02 pinned `twscrape==0.19.2`, adapter isolation, telemetry shutdown, Cookie validation, account-output redaction, and upstream error classification.
- W03 raw JSON page evidence, content-addressed immutable artifacts, page-to-post provenance, atomic SQLite page commits, cursor checkpoints, terminal-page recovery, and distinct cross-page statistics.
- W04 no-echo local Cookie acquisition, centralized redaction, Git-worktree refusal, private POSIX modes, hardened atomic local writes, and documented Windows/plaintext-SQLite guarantees.
- W05 independently resumable recent timeline scopes, stable-user-ID and fixed-range filtering, native-repost scope locking, protected/unavailable target handling, suspicious-empty detection, and profile snapshot round-trip hardening.
- W06 canonical resolved-username search, stable-user-ID enforcement, whole-second half-open windows, integer midpoint splits, noisy-result filtering, dense-window recursion, and independent child-scope resume.
- W07 exact evidence-graph coverage validation, same-ID material conflict preservation, `SOURCE_CONFLICT`, immutable raw verification, and atomic self-verifying export bundles.
- W08 reset-aware 429 waits, automatic cursor resume for timelines and search, root-cause retry budgets, explicit recovery events, and non-recoverable error separation.
- W09 now includes a redacted evidence collector that verifies the export bundle, summarizes page/window/recovery counts, and proves cursor continuity with SHA-256 fingerprints rather than plaintext cursor values.
- Deterministic validation currently contains 85 tests; compile, pytest, task-state validation, and secret audit pass locally. Permanent Ruff and Product Gate validation are pending for this helper update.

## Human gate — W09

The remaining acceptance evidence requires the user's authorized browser Cookie and live X traffic on the user's local machine. Run the commands and interruption/resume procedure in `W09_plan.md`, then generate the shareable summary with `scripts/live/collect_w09_evidence.py`. Do not send Cookie values, local account databases, raw authorization headers, raw response bodies, or plaintext cursor values.

## Remaining after W09

- W10 final documentation and acceptance reconciliation;
- mark PR #2 ready, merge after all checks pass;
- run exact-main Post-Merge validation;
- set final acceptance, security, and post-merge states to PASS and close Task #1.

## Known source limitations

- Search and timeline completeness describe the currently observable source surface; deleted, protected, suspended, de-indexed, or search-suppressed posts may remain unavailable.
- Historical native repost indexing is not guaranteed.
- X may change its internal web GraphQL operations without notice.
