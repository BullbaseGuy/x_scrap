# W04 plan — Local credential isolation and security hardening

1. Remove plaintext Cookie values from command-line arguments; browser cookies may enter only through a no-echo prompt in the first release.
2. Add centralized redaction for `auth_token`, `ct0`, Cookie headers, authorization values, and URL query fragments before messages enter SQLite, events, logs, or CLI output.
3. Harden local paths: reject a state home located inside a Git worktree, create data directories with private POSIX modes, and restrict SQLite, raw evidence, and normalized export files where the platform supports it.
4. Keep Windows behavior explicit: rely on the current Windows user profile/inherited ACL rather than claiming portable file encryption or silently invoking `icacls`.
5. Secure the accounts database after adapter initialization and cookie updates; document that the upstream SQLite session store is local plaintext protected by OS access controls, not encrypted at rest.
6. Ensure GitHub Actions never receive a real Cookie, account database, raw page, or normalized export.
7. Extend `.gitignore` and secret-audit fixtures for local state, SQLite sidecars, cookies, raw captures, and export trees.
8. Add tests for CLI argument rejection, no-echo input, secret redaction, repository-path refusal, POSIX modes, raw/export file modes, and persisted error redaction.
9. Update README, usage, security policy, and threat-model documentation with exact guarantees and remaining risks.
10. Run compile, Ruff, full tests, state consistency, workflow contract, and secret audit before advancing to W05.

Exit criteria: no supported CLI path places a Cookie in argv; high-confidence Cookie values are redacted before persistence/output; local state cannot accidentally initialize inside the repository; supported POSIX files/directories are private; all deterministic gates pass; and no claim of encryption or Windows ACL hardening is made without evidence.
