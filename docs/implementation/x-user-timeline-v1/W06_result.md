# W06 result — Historical search partitions

Status: PASS (deterministic local validation)

## Implemented

- historical `from:` queries now use the canonical username captured from the resolved profile rather than the user-supplied alias;
- every accepted search result is independently required to match the stable resolved user ID, protecting against stale or reused usernames;
- explicit start and cutoff values must use whole-second UTC precision, and the default cutoff is frozen at the latest completed second;
- all search windows remain half-open `[start, end)`, with exact integer-second epoch boundaries;
- recursive splits use an integer midpoint, preserve exact parent coverage for odd durations, and reject an unsplittable one-second interval;
- dense windows split only when an upstream cursor remains at the source budget; terminal cursors are treated as exhaustion even when the item count equals the budget;
- parent, child, raw-page, page-to-post, and cursor evidence remain intact, while completed siblings are skipped and interrupted child scopes resume from their own next cursor;
- noisy foreign-user and out-of-window records remain in immutable page evidence but are excluded from normalized posts;
- manifests distinguish the canonical resolved username from the originally requested alias.

## Deterministic validation

- Python compile: PASS;
- pytest: PASS (69 tests);
- repository secret audit: PASS;
- `git diff --check`: PASS;
- canonical username, stable user ID, exact start/cutoff inclusion, foreign/noisy filtering, odd-second splitting, dense recursion, minimum-window partial status, parent/child continuity, and child-cursor resume are covered by tests.

Ruff and the complete repository Product Gate are executed by the atomic W06 apply workflow before the canonical state advances.

## Security and cost

- real X credentials used: 0;
- authenticated live X requests: 0;
- paid API calls: 0;
- paid proxy calls: 0;
- Codex calls: 0.

No human action was required.
