# W03 plan — Page evidence, cursor checkpoints, and persistence hardening

1. Add a stable `CollectorPage` contract containing source, operation, request cursor, next cursor, parsed items, raw response payload, page index, and capture time.
2. Implement `twscrape` raw-page adapters for user tweets, user tweets-with-replies, and search without exposing upstream response types outside the adapter.
3. Persist gzip-compressed page payloads with deterministic SHA-256 metadata rather than labeling per-post normalized payloads as raw pages.
4. Extend SQLite with page checkpoints and artifact metadata so a task resumes at the next committed cursor rather than replaying a whole source/window.
5. Make page ingestion transactional: page metadata, post upserts, and cursor advancement must commit together or roll back together.
6. Detect repeated cursors and non-advancing pagination as an unresolved source condition instead of looping forever.
7. Preserve compatibility with the current item-stream fake adapter through deterministic page fixtures.
8. Add migration, replay, rollback, duplicate-page, repeated-cursor, and interrupted-page tests.
9. Update architecture and output documentation to distinguish page evidence from normalized post records.
10. Run compile, Ruff, tests, state consistency, and secret audit before advancing to W04.

Exit criteria: every source/window can resume from a committed page cursor, raw page artifacts are hash-addressed and traceable from SQLite, interrupted ingestion is idempotent, and all deterministic gates pass.
