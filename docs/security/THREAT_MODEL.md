# Threat model

## Protected assets

- the local X browser session (`auth_token` and `ct0`);
- the `twscrape` account database;
- job state and error records;
- raw upstream JSON evidence;
- normalized exports and profile snapshots.

## Trust boundaries

1. **Local operator and operating system** — trusted to protect the selected state directory and user account.
2. **X web interfaces** — external, unstable, rate-limited, and capable of returning malformed or changed payloads.
3. **`twscrape`** — pinned third-party compatibility dependency, isolated behind an adapter.
4. **Git repository and GitHub Actions** — treated as public to collaborators and therefore forbidden from receiving real credentials or collected data.
5. **Exports** — public-source data can still be sensitive in aggregate and is stored privately by default.

## Mitigated threats

| Threat | Control |
|---|---|
| Cookie exposed in shell history or process list | No Cookie command-line option; no-echo prompt only |
| State accidentally committed | State home rejected inside Git worktrees; ignore rules and secret audit |
| Credential copied into errors | Central recursive redaction before persistence and CLI output |
| Other local POSIX users read state | `0700` directories and `0600` files |
| Crash leaves partial raw/export file | temporary file, flush, `fsync`, atomic replacement |
| Retry overwrites prior raw evidence | immutable content-addressed raw artifacts |
| CI accesses a real account | read-only deterministic workflows; live smoke excluded |
| Upstream telemetry leaks use metadata | `TWS_TELEMETRY=0` and `DO_NOT_TRACK=1` forced before import |

## Residual risks

- Windows and non-POSIX protection depends on inherited ACLs; `x_scrap` does not configure or verify them.
- Local administrators, malware, memory inspection, terminal capture, and compromised Python dependencies can access an active session.
- The account database is not encrypted at rest by this project.
- X may restrict or suspend an account, alter private GraphQL operations, or omit indexed content.
- Publicly accessible posts may contain personal data; collection and downstream use remain the operator's responsibility.
- Redaction cannot guarantee removal of an unknown future secret format.

## Explicit non-goals

The project does not bypass CAPTCHA, login challenges, protected-account controls, account suspensions, or platform access restrictions. It does not automate account creation, purchase accounts or proxies, or represent observable search traversal as recovery of all historical content.
