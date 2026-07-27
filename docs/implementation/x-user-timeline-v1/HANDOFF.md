# Handoff

Resume from `W09_plan.md` on `feature/x-user-timeline-v1` after the W07-W08 atomic publication gate succeeds.

Before changing product behavior:

1. inspect `task_state.yaml`, `STATUS.md`, Task #1, and Draft PR #2;
2. keep X-specific compatibility fixes inside `src/x_scrap/adapters/`;
3. preserve stable-user-ID filtering and exact whole-second half-open search windows;
4. do not label coverage complete unless windows, scopes, pages, page-to-post links, canonical posts, conflicts, and raw evidence agree;
5. preserve reset-aware rate-limit waits and bounded same-root transient recovery;
6. do not add real Cookies, account DBs, exports, or captured authorization data to Git, tests, Issues, PRs, or chat;
7. keep Codex and paid API/proxy usage disabled.

W09 is a real human gate: only the user can run the authorized local live smoke and interruption/resume procedure. Generate the safe summary with `scripts/live/collect_w09_evidence.py`; it omits credentials, raw bodies, local paths, and plaintext cursors. Once that redacted evidence passes, continue automatically through W10, PR readiness/merge, and exact-main Post-Merge.
