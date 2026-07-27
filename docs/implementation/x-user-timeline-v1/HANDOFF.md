# Handoff

Resume from `W09_LIVE_RUNBOOK.md` on `feature/x-user-timeline-v1`.

Before changing product behavior:

1. inspect `task_state.yaml`, `STATUS.md`, Task #1, and Draft PR #2;
2. keep X-specific compatibility fixes inside `src/x_scrap/adapters/`;
3. preserve stable-user-ID filtering and exact whole-second half-open search windows;
4. do not label coverage complete unless windows, scopes, pages, page-to-post links, canonical posts, conflicts, and raw evidence agree;
5. preserve reset-aware rate-limit waits and bounded same-root transient recovery;
6. do not add real Cookies, account DBs, exports, captured authorization data, raw responses, raw post text, local paths, or plaintext cursors to Git, tests, Issues, PRs, or chat;
7. keep Codex and paid API/proxy usage disabled.

W00-W08 and the deterministic W09 preparation are complete. W09 remains a real human gate because only the user can provide the authorized local browser session and execute live traffic.

Run the single PowerShell command documented in `W09_LIVE_RUNBOOK.md`. It performs the small, interruption, exact-resume, and higher-volume cases and emits a strict sanitized `W09_ACCEPTANCE.json`. Once that manually reviewed file passes, continue automatically through `W09_result.md`, W10, PR readiness and merge, and exact-main Post-Merge.
