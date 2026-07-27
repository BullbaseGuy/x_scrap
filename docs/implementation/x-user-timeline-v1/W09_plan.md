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

```powershell
$env:X_SCRAP_HOME = 'D:\x_scrap_data'
$env:TWS_TELEMETRY = '0'

python scripts/live/run_user_export_smoke.py --home $env:X_SCRAP_HOME --preflight-only

python scripts/live/run_user_export_smoke.py xdevelopers `
  --home $env:X_SCRAP_HOME `
  --start 2026-07-01T00:00:00Z `
  --acknowledge-live-x
```

Then run one larger public account over a historical range. During that task, stop the process after at least one page is committed and execute the identical command again. The second run must reuse the same job and continue from the stored cursor without replacing committed raw evidence.

## Evidence to report without secrets

- command options excluding credentials;
- job ID and target username;
- final job and coverage status;
- page/post/window counts;
- whether a real 429 occurred and, if so, the redacted wait event;
- first run's last committed scope/page/cursor position;
- resumed run's first requested scope/page/cursor position;
- `verify_export_bundle()` result and bundle digest;
- any account challenge or upstream operation failure, with credential values removed.

## Exit criteria

- small-account live export passes;
- interrupted historical export resumes from committed evidence;
- any encountered real 429 waits and resumes automatically;
- final bundle verifies successfully;
- no secrets appear in repository or supplied evidence.

This stage is an explicit human gate because the required browser session belongs only on the user's local machine.
