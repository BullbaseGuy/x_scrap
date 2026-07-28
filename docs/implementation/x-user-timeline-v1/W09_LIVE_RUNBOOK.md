# W09 authorized local live E2E runbook

This stage uses a real browser session owned by the operator. Run it only on the operator's computer. The Cookie, `accounts.db`, `jobs.db`, raw JSON pages, and exported posts remain under `X_SCRAP_HOME` outside Git. The only shareable artifact is the sanitized `W09_ACCEPTANCE.json` after manual inspection.

## 1. Update and install

```powershell
Set-Location D:\Download\x_scrap
git fetch origin
git switch feature/x-user-timeline-v1
git pull --ff-only origin feature/x-user-timeline-v1

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## 2. Choose private state storage

Use a directory outside this and every other Git worktree:

```powershell
$PrivateHome = 'D:\x_scrap_private'
```

On Windows, confidentiality depends on the selected directory's inherited ACL. The local `twscrape` account database is plaintext SQLite; the project does not claim encryption at rest.

## 3. Run the complete W09 sequence

Choose public targets. The report stores only a 16-character SHA-256 target fingerprint, not the username.

```powershell
.\scripts\live\run_w09.ps1 `
  -Home $PrivateHome `
  -SmallUsername <PUBLIC_USERNAME> `
  -VolumeUsername <PUBLIC_USERNAME>
```

The script automatically:

- forces `TWS_TELEMETRY=0` and `DO_NOT_TRACK=1`;
- refuses CI;
- refuses an implicit proxy environment;
- runs compile and all deterministic tests;
- checks for exactly one active local account;
- opens a no-echo Cookie prompt only when no active account exists;
- executes the small, interruption, resume, and higher-volume cases;
- verifies the committed cursor-resume contract;
- writes and validates `W09_ACCEPTANCE.json`.

Do not paste Cookie values into the command. The only accepted Cookie path is:

```powershell
x-scrap --home $PrivateHome auth add-cookie --label primary
```

If the machine intentionally requires a non-paid system proxy, review that condition explicitly. Passing `-AllowProxyEnvironment` permits execution but automatic W09 acceptance still rejects the report until the proxy condition is manually adjudicated.

## 4. Default ranges

The orchestrator defaults to:

| Case | Range | Purpose |
|---|---|---|
| small fixed range | 2026-07-01 to 2026-07-08 UTC | basic live compatibility and bundle verification |
| interruption/resume | 2026-01-01 to 2026-07-01 UTC | committed page, remaining cursor, and exact resume |
| higher volume | 2024-01-01 to 2026-07-01 UTC | multiple pages and historical windows |

Override them with `-SmallStart`, `-SmallCutoff`, `-ResumeStart`, `-ResumeCutoff`, `-VolumeStart`, and `-VolumeCutoff` when the selected target has insufficient activity. All timestamps must be whole-second ISO-8601 UTC values.

The interruption case must capture a page whose response still has a next cursor. If it reports no resumable cursor, choose a more active target or wider range and rerun; do not weaken the validator.

## 5. Private output

Expected private files:

```text
D:\x_scrap_private\live-evidence\
├── small-fixed-range.json
├── interruption-resume.json
├── interruption-resume-final.json
├── higher-volume.json
└── W09_ACCEPTANCE.json
```

Before sharing the acceptance file, open it and confirm it contains none of the following:

- username or account label;
- Cookie, `auth_token`, `ct0`, or authorization value;
- absolute local path;
- raw cursor;
- raw response or post text;
- account database or export content.

The validator already rejects these structures, but manual inspection remains required before moving any evidence out of the private directory.

## 6. Manual fallback

The individual runner remains available for diagnosis:

```powershell
python scripts/live/run_e2e_case.py `
  --case-name small-fixed-range `
  --username <PUBLIC_USERNAME> `
  --start 2026-07-01T00:00:00Z `
  --cutoff 2026-07-08T00:00:00Z `
  --home $PrivateHome `
  --acknowledge-live-x
```

Controlled interruption:

```powershell
python scripts/live/run_e2e_case.py `
  --case-name interruption-resume `
  --username <PUBLIC_USERNAME> `
  --start 2026-01-01T00:00:00Z `
  --cutoff 2026-07-01T00:00:00Z `
  --home $PrivateHome `
  --interrupt-after-pages 1 `
  --acknowledge-live-x
```

Resume is tied to the private checkpoint file rather than a loose boolean:

```powershell
python scripts/live/run_e2e_case.py `
  --case-name interruption-resume-final `
  --username <PUBLIC_USERNAME> `
  --start 2026-01-01T00:00:00Z `
  --cutoff 2026-07-01T00:00:00Z `
  --home $PrivateHome `
  --resume-from-report "$PrivateHome\live-evidence\interruption-resume.json" `
  --acknowledge-live-x
```

Validate the four reports and produce acceptance evidence:

```powershell
python scripts/live/validate_e2e_report.py `
  --acceptance-output "$PrivateHome\live-evidence\W09_ACCEPTANCE.json" `
  "$PrivateHome\live-evidence\small-fixed-range.json" `
  "$PrivateHome\live-evidence\interruption-resume.json" `
  "$PrivateHome\live-evidence\interruption-resume-final.json" `
  "$PrivateHome\live-evidence\higher-volume.json"
```
