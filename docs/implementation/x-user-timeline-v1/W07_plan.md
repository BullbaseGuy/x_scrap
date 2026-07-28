# W07 plan — Coverage audit and reproducible exports

1. Strengthen the coverage auditor so terminal leaf windows must form one exact, non-overlapping partition of the frozen `[start, cutoff)` range.
2. Cross-check window state, harvest-scope state, cursor termination, page counts, accepted counts, observed post timestamps, and raw-artifact metadata before issuing a completeness status.
3. Detect same-ID normalized payload conflicts instead of silently replacing materially different author, timestamp, text, or relation fields; preserve all source provenance and expose `SOURCE_CONFLICT` when unresolved.
4. Add an export inventory containing deterministic file hashes, byte sizes, record counts, schema versions, source counts, scope summaries, window summaries, and known source limitations.
5. Write the export set through a staging directory and atomically publish it only after every required file and checksum validates.
6. Add `errors.jsonl`/event summaries without exposing local Cookies, authorization values, or unredacted upstream failures.
7. Verify JSONL and CSV row identity, string IDs, UTC timestamps, stable ordering, UTF-8 handling, duplicate-source provenance, and reproducible hashes for identical committed database state.
8. Run compile, Ruff, full tests, state consistency, workflow contract, and secret audit before advancing to W08.

Exit criteria: a completed job has a self-verifying export bundle whose coverage status is derived from mutually consistent windows, scopes, pages, posts, and immutable evidence; conflicts or unresolved traversal can never be labeled complete.
