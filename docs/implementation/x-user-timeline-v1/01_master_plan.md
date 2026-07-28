# Master plan

| Stage | Scope | Exit condition |
|---|---|---|
| W00 | Contract, completeness boundary, risks, master plan | Required documents committed |
| W01 | Devflow bootstrap and repository gates | State, tests, workflows, and secret audit valid |
| W02 | Dependency evidence and adapter contract | Pinned dependency; adapter tests pass |
| W03 | Domain model, SQLite, normalized artifacts | Idempotency and transaction tests pass |
| W04 | Local cookie import and security boundary | No secret leakage; telemetry disabled |
| W05 | Recent timelines | User tweets and replies collected and deduplicated |
| W06 | Historical search partitions | Saturated windows split and resumed |
| W07 | Coverage and exports | Auditable artifacts and terminal coverage state |
| W08 | Fault and recovery matrix | 429/transient/schema/auth/interruption tests pass |
| W09 | Local opt-in live E2E | Authorized local smoke and resume evidence |
| W10 | Final docs, review, merge, exact-main gate | Acceptance/security/post-merge PASS |

Normal stages continue without asking for a manual "continue." Only a stop condition in the task contract creates a human gate.
