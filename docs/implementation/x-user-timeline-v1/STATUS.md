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
- W09 deterministic preparation now includes a one-command Windows orchestrator, four live cases, an exact committed-cursor resume contract, strict sanitized evidence, and automatic `W09_ACCEPTANCE.json` generation.
- The W09 preparation publication passed SHA-256 reconstruction, Python compilation, Ruff, the complete pytest suite, canonical task-state validation, repository secret audit, diff checks, and temporary-surface removal.
- A subsequent clean repository state passed the permanent Test, Product Gate, State Consistency, and Secret Audit workflows.
- The first authorized local run exposed the `twscrape==0.19.2` empty-page-guard condition: a recent timeline generator can stop after three empty or filtered pages while its last content page still carries a cursor.
- Hotfix `7579f3ed11c608e7a23c784bc2260144a882a067` now records that recent timeline as explicit truncation and keeps exact date-partitioned Search as the authoritative coverage surface; Search cursor exhaustion and recursive splitting remain strict.
- The hotfix and its regression fixture passed compilation, Ruff, the complete pytest suite, state validation, secret audit, diff checks, and temporary-workflow removal.
- All staging payloads, diagnostic workflows, and write-capable preparation/hotfix workflows were removed by their gated publication commits.

## Human gate — W09

Update the local checkout to the latest `feature/x-user-timeline-v1`, reinstall the editable package, and rerun the public-target export or the one-command W09 runner. The previously failed job and raw artifacts may remain in the private state directory; no Cookie re-import or destructive cleanup is required.

```powershell
git fetch origin
git switch feature/x-user-timeline-v1
git pull --ff-only origin feature/x-user-timeline-v1
python -m pip install -e ".[dev]"

.\scripts\live\run_w09.ps1 `
  -Home D:\x_scrap_private `
  -SmallUsername <PUBLIC_USERNAME> `
  -VolumeUsername <PUBLIC_USERNAME>
```

The command performs deterministic preflight, prompts for the Cookie only through the no-echo local path when necessary, runs small/interruption/resume/higher-volume cases, verifies the export bundles, and writes `W09_ACCEPTANCE.json` under the private state directory.

Before sharing, manually inspect the acceptance file. Do not send Cookie values, account databases, authorization headers, raw responses, raw post text, local paths, or plaintext cursor values.

## Remaining after W09

- validate the sanitized `W09_ACCEPTANCE.json` and write `W09_result.md`;
- W10 final documentation and acceptance reconciliation;
- mark PR #2 ready and merge after all checks pass;
- run exact-main Post-Merge validation;
- set final acceptance, security, and post-merge states to PASS and close Task #1.

## Known source limitations

- Search and timeline completeness describe the currently observable source surface; deleted, protected, suspended, de-indexed, or search-suppressed posts may remain unavailable.
- Recent timeline endpoints may stop after an upstream empty-page guard while a cursor remains; this is reported explicitly and does not weaken Search-window completeness requirements.
- Historical native repost indexing is not guaranteed.
- X may change its internal web GraphQL operations without notice.
