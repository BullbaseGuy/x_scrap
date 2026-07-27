# Handoff

Resume from `W07_plan.md` on `feature/x-user-timeline-v1`.

Before changing product behavior:

1. run the repository-full gate;
2. inspect `task_state.yaml`, `STATUS.md`, and Task #1;
3. keep X-specific compatibility fixes inside `src/x_scrap/adapters/`;
4. preserve stable-user-ID filtering and exact whole-second half-open search windows;
5. do not label coverage complete unless leaf windows, scopes, pages, posts, and evidence agree;
6. do not add real Cookies or captured account data to tests;
7. keep Codex and paid API/proxy usage disabled.

The first live credential requirement belongs to W09, not earlier deterministic stages.
