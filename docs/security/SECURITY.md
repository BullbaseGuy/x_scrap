# Security policy and local credential handling

## Supported credential path

The first release accepts an X browser session only through the interactive, no-echo prompt:

```powershell
x-scrap auth add-cookie --label primary
```

There is no supported `--cookie` argument. This avoids putting `auth_token` and `ct0` in process listings, PowerShell history, terminal transcripts, or task-runner metadata. Do not paste a real Cookie into an Issue, pull request, GitHub Actions secret, command line, `.env` file, or repository document.

## Local storage boundary

`accounts.db`, `jobs.db`, raw JSON evidence, and normalized exports live below `X_SCRAP_HOME`, which must be outside every Git worktree. The supplied `.gitignore` and secret audit provide additional defense, but they are not a substitute for keeping the state directory outside a repository.

On POSIX systems the application applies:

- `0700` to state, raw-evidence, and export directories;
- `0600` to SQLite databases, SQLite sidecars, raw evidence, and export files.

On Windows the application deliberately relies on the ACL inherited from the current user's profile or chosen storage directory. It does not claim portable encryption, does not silently invoke `icacls`, and does not change machine-wide policy.

## Encryption statement

The upstream `twscrape` account database is a local plaintext SQLite session store. `x_scrap` restricts access with operating-system permissions where supported, but it does **not** encrypt the database at rest. Full-disk encryption and a protected Windows account remain the user's responsibility.

## Redaction

Before error data reaches SQLite, events, account-list output, or top-level CLI errors, the application redacts:

- `auth_token` and `ct0` values;
- access and refresh tokens;
- Cookie and Authorization header values;
- Bearer credentials;
- sensitive URL query or fragment values.

Redaction is a defense-in-depth control, not permission to log credentials intentionally.

## CI boundary

GitHub Actions use read-only repository permissions and deterministic synthetic fixtures. They do not receive a real X Cookie, local account database, raw page capture, or normalized export. The authenticated smoke script is local opt-in only and is prohibited from CI workflows.

## Reporting a vulnerability

Do not include working credentials or private datasets in a report. Describe the affected path, expected behavior, reproduction using synthetic values, and the smallest safe patch. Rotate any credential that may have been disclosed before continuing development.
