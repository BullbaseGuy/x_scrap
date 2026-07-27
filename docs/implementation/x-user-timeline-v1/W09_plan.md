# W09 plan — Local opt-in authenticated E2E

## Purpose

Validate the remaining behavior that cannot be truthfully proven with sanitized deterministic fixtures: the current X login session, live operation compatibility, real rate-limit reset behavior, and interruption/resume against an authorized public account.

## Preconditions

1. Run only on the user's local machine, never in GitHub Actions or another shared runner.
2. Install Python 3.12 and the project from this branch.
3. Keep `X_SCRAP_HOME` outside every Git worktree.
4. Add the user's own browser session through the no-echo `x-scrap auth add-cookie --label primary` prompt.
5. Do not paste Cookie values into chat, Issues, PRs, logs, screenshots, or shell command arguments.

## Procedure

### 1. Install and preflight

```powershell
git clone https://github.com/BullbaseGuy/x_scrap.git
cd x_scrap
git switch feature/x-user-timeline-v1

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

$env:X_SCRAP_HOME = 'D:\x_scrap_data'
$env:TWS_TELEMETRY = '0'
$env:DO_NOT_TRACK = '1'

python scripts/live/run_user_export_smoke.py `
  --home $env:X_SCRAP_HOME `
  --preflight-only
```

If no active local account is listed, add the user's browser session through the no-echo prompt:

```powershell
x-scrap --home $env:X_SCRAP_HOME auth add-cookie --label primary
```

### 2. Small live export

```powershell
python scripts/live/run_user_export_smoke.py xdevelopers `
  --home $env:X_SCRAP_HOME `
  --start 2026-07-01T00:00:00Z `
  --acknowledge-live-x
```

Record only the returned job ID, status, coverage status, bundle digest, and output directory. Do not copy raw authenticated responses into chat or GitHub.

### 3. Real interruption and cursor resume

Choose a larger public account and a historical range. Start the task with a conservative page budget:

```powershell
python scripts/live/run_user_export_smoke.py <large_public_username> `
  --home $env:X_SCRAP_HOME `
  --start 2025-01-01T00:00:00Z `
  --initial-window-days 30 `
  --max-posts-per-window 5000 `
  --acknowledge-live-x
```

After at least one `PAGE_COMMITTED` event appears, stop the process with `Ctrl+C`. Run the identical command again. The second process must reuse the same job ID and continue from the stored page/cursor position without replacing already committed content-addressed raw evidence.

### 4. Generate a safe evidence summary

Generate a redacted evidence file for each live job. This helper does not include Cookie values, authorization headers, raw response bodies, output paths, or plaintext cursor values. Cursor continuity is represented only by SHA-256 fingerprints.

```powershell
python scripts/live/collect_w09_evidence.py `
  --home $env:X_SCRAP_HOME `
  --job-id <job_id>
```

The default output is:

```text
D:\x_scrap_data\w09-evidence\<job_id>.json
```

Open the JSON and manually review it before sharing. The file should report:

- job ID, target username, fixed start/cutoff, final job and coverage status;
- page, post, scope, window, event, and conflict counts;
- one run segment before interruption and a resumed run segment;
- matching last-page `next_cursor_fingerprint` and resumed first-page `request_cursor_fingerprint`;
- redacted 429/reset wait evidence when a real 429 occurred;
- `verify_export_bundle()` status and bundle digest;
- explicit confirmation that Cookie, authorization header, raw response body, and plaintext cursor values are omitted.

## Exit criteria

- small-account live export passes;
- interrupted historical export resumes from committed evidence;
- any encountered real 429 waits and resumes automatically;
- final bundle verifies successfully;
- no secrets appear in repository or supplied evidence.

This stage is an explicit human gate because the required browser session belongs only on the user's local machine. After the redacted evidence passes review, continue automatically through W10, PR readiness and merge, and exact-main Post-Merge.
