# W09 deterministic preparation result

Status: **PASS — authorized local session still required**

## Prepared

- `scripts/live/run_w09.ps1` provides one-command Windows orchestration for preflight, Cookie prompt, four live cases, report validation, and acceptance generation.
- `scripts/live/run_e2e_case.py` refuses CI, requires explicit live acknowledgement, pins Python 3.12 and `twscrape==0.19.2`, disables telemetry, requires one active account, and rejects an implicit proxy environment.
- Non-resume cases always create new jobs, preventing an unrelated stale `PARTIAL` job for the same target from being selected.
- Resume requires the private interruption report and verifies the exact job ID, target fingerprint, frozen start/cutoff, committed page hashes, page metadata, next page index, and nonempty request cursor.
- Report paths are fixed beneath `X_SCRAP_HOME/live-evidence`; case-name traversal and arbitrary report destinations are rejected.
- Sanitized evidence rejects credential fields, raw content, cursor fields, target names, account labels, proxy values, and absolute private paths.
- `scripts/live/validate_e2e_report.py` validates individual reports and the four-case W09 acceptance contract.
- Automatic acceptance requires complete observable coverage, no conflicts or integrity findings, multiple-page higher-volume traversal, preserved committed evidence, exact cursor continuation, zero paid usage, and verified export digests.

## Deterministic validation

- Python compile: PASS;
- pytest: PASS in local preparation;
- task-state validation: PASS before publication;
- secret audit: PASS before publication;
- authenticated live X requests: 0;
- paid API calls: 0;
- paid proxy calls: 0;
- Codex calls: 0.

W09 remains a real human gate because only the repository owner can provide the authorized local browser session and execute live traffic. The prepared tools minimize the required manual work to one PowerShell command and produce only a reviewable sanitized acceptance file.
