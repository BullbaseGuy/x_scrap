# Handoff

Resume from `W06_plan.md` on `feature/x-user-timeline-v1`.

Before changing product behavior:

1. run the repository-full gate;
2. inspect `task_state.yaml`, `STATUS.md`, and Task #1;
3. keep X-specific fixes inside `src/x_scrap/adapters/`;
4. preserve whole-second half-open window semantics and stable-user-ID filtering;
5. do not add real Cookies or captured account data to tests;
6. keep Codex and paid API/proxy usage disabled.

The first live credential requirement belongs to W09, not earlier deterministic stages.
