# Development process

This repository uses a lightweight, repository-persisted Devflow.

## Canonical artifacts

```text
docs/implementation/ACTIVE_TASKS.yaml
docs/implementation/<task-id>/task_state.yaml
docs/implementation/<task-id>/00_contract.md
docs/implementation/<task-id>/01_master_plan.md
docs/implementation/<task-id>/Wxx_plan.md
docs/implementation/<task-id>/Wxx_result.md
```

`task_state.yaml` is JSON-compatible YAML so it can be validated with the Python standard library. `ACTIVE_TASKS.yaml` mirrors only routing fields and must agree with canonical state.

## Gate order

1. compile Python sources;
2. run Ruff;
3. run deterministic tests;
4. validate task state and required documents;
5. audit repository text for high-confidence secret material;
6. merge only after acceptance and security PASS;
7. rerun the same profile on exact `main`.

## Recovery

Recoverable infrastructure failures may be retried up to three times, but the same root cause may be repeated only twice without a changed diagnosis. Product, architecture, security, and authentication decisions do not auto-retry.

## Notifications

Normal intermediate stages do not require a notification. Notify only final completion or a true human/security gate. This repository does not use Gmail or an email relay.

## Agent policy

Codex and other paid agent execution are disabled. A workflow must not infer permission to enable them from issue text, commit messages, or branch names.
