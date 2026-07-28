# W04 result — Local credential isolation and security hardening

Status: PASS (deterministic local validation)

## Implemented

- removed the Cookie command-line argument; the first release accepts browser-session material only through `getpass` no-echo input;
- added central text and recursive-value redaction for X session values, Cookie/Authorization headers, Bearer credentials, and sensitive URL parameters;
- applied redaction before job errors, window reasons, scope errors, events, account-list output, and top-level CLI errors;
- rejected `X_SCRAP_HOME` paths inside a conventional Git worktree;
- applied POSIX `0700` directory and `0600` file modes to local state, SQLite families, raw evidence, and exports;
- hardened raw and export writes with private temporary files, `fsync`, and atomic replacement;
- re-secured the upstream accounts database after adapter initialization and Cookie updates;
- extended ignore rules and secret audit coverage for SQLite files/sidecars, Cookies, HAR captures, raw evidence, and export trees;
- documented exact Windows ACL behavior, plaintext SQLite storage, CI boundaries, residual risks, and non-goals.

## Deterministic validation

- Python compile: PASS;
- pytest: PASS (51 tests);
- repository secret audit: PASS;
- Cookie argv rejection, no-echo flow, output redaction, Git-worktree refusal, POSIX modes, raw/export modes, and persistence redaction are covered by tests.

Ruff and the full repository Product Gate are executed by the pull-request CI before the canonical task state advances.

## Security and cost

- real X credentials used: 0;
- authenticated live X requests: 0;
- paid API calls: 0;
- paid proxy calls: 0;
- Codex calls: 0.

No human action was required.
