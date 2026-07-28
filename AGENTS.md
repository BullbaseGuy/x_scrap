# Repository execution instructions

## Source of truth

- `docs/implementation/ACTIVE_TASKS.yaml` indexes active work.
- Each task's `task_state.yaml` is canonical for lifecycle state.
- A stage must have `Wxx_plan.md` before implementation and `Wxx_result.md` after validation.
- Never mark a task `DONE` before acceptance, security, and exact-main post-merge checks pass.

## Execution discipline

- Continue automatically through normal intermediate gates.
- Diagnose before retrying. Do not repeat a failed action without a changed hypothesis.
- Respect the retry budget in `.devflow/project.json`.
- Stop for a human only for an account challenge, credentials, destructive action, or material product/architecture decision.
- Codex and other paid agent execution are disabled unless the user explicitly re-enables them.

## Security

- Never commit X cookies, passwords, tokens, local account databases, collected exports, or raw capture data.
- Keep secrets outside the repository and redact them from logs, issues, pull requests, test fixtures, and artifacts.
- Do not implement CAPTCHA bypass, automated account creation, purchased-account integration, or access-control circumvention.
- GitHub Actions must use synthetic or recorded sanitized fixtures only.

## Product boundaries

- Keep upstream-specific behavior inside `src/x_scrap/adapters/`.
- Store X IDs as strings.
- Store timestamps in UTC.
- Make writes idempotent and transactionally resumable.
- Do not claim historical completeness without a continuous, terminal coverage report.
