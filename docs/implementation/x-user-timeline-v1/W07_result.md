# W07 result — Coverage audit and reproducible exports

Status: PASS (deterministic local validation)

## Implemented

- terminal leaf windows must form one exact, non-overlapping half-open partition of the frozen `[start, cutoff)` range;
- completeness now cross-checks windows, harvest scopes, page-index continuity, cursor chains, page-to-post links, post source provenance, timestamp summaries, and immutable raw-artifact size/hash/content;
- a missing parent search scope for a split window is an integrity failure rather than silently accepted history;
- same-ID disagreements in stable author, timestamp, text, conversation, reply, quote, or repost fields are persisted in `post_conflicts` without replacing the first canonical payload;
- unresolved material disagreements produce `SOURCE_CONFLICT`, while any evidence-graph inconsistency produces `PARTIAL_UNRESOLVED_WINDOWS`;
- exports are built in a private staging directory, verified, and then published with rollback protection;
- bundles now contain `inventory.json`, `errors.jsonl`, and `conflicts.jsonl` in addition to manifest, profile, coverage, JSONL, CSV, and summary files;
- inventory records deterministic hashes, sizes, row counts, schema versions, source counts, scope/window summaries, raw-evidence references, and a bundle digest;
- JSONL and CSV identities, string IDs, UTC timestamps, stable ordering, UTF-8 content, and duplicate-source provenance are self-verified;
- error and conflict outputs pass through centralized credential redaction.

## Defects caught during implementation

1. A seeded recursive-window resume fixture created a `SPLIT` parent without the rate-limited parent scope that justified the split. The fixture was corrected to preserve the missing page/cursor evidence; the auditor was not weakened.
2. Replacing an existing export directly could expose a partial bundle. Publication now uses verified staging plus rollback-aware directory replacement.
3. Same-ID payloads previously allowed later observations to replace earlier normalized material. Stable material is now canonical and conflicts are explicit evidence.

## Deterministic validation

- Python compile: PASS;
- pytest: PASS, including exact partition, evidence hash loss, conflict persistence, service-level `SOURCE_CONFLICT`, deterministic bundle reproduction, tamper detection, redaction, and failed-staging rollback;
- canonical task-state validation: PASS;
- repository secret audit: PASS.

Ruff and the complete repository Product Gate are executed by the atomic apply workflow before publication.

## Security and cost

- real X credentials used: 0;
- authenticated live X requests: 0;
- paid API calls: 0;
- paid proxy calls: 0;
- Codex calls: 0.

No human action was required.
