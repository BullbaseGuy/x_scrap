# W05 result — Recent user timelines

Status: PASS (deterministic apply-gate validation)

## Implemented

- `UserTweets` and `UserTweetsAndReplies` remain independent page scopes with their own cursor, page index, terminal state, and resume point;
- timeline collection now runs on every resume before historical windows, so an existing search window can no longer hide an unfinished timeline scope;
- every accepted timeline post is filtered to the resolved stable user ID and the fixed half-open job range `[start, cutoff)`;
- original posts, replies, self-replies, quote posts, long-form text, media metadata, and relation IDs are preserved;
- native reposts remain excluded by default and can be included only by an explicit job scope that cannot be changed on resume;
- requested usernames are normalized case-insensitively while historical search will use the canonical resolved account identity in W06;
- protected targets stop before timeline collection with `HUMAN_REQUIRED` rather than attempting an access-control bypass;
- a missing or suspended target is classified as `TARGET_UNAVAILABLE`, not as a GraphQL schema failure;
- both recent endpoints returning zero pages for a target reporting existing posts is recorded as suspicious; a fully empty timeline and historical search cannot be marked complete;
- persisted profile snapshots now round-trip canonical fields and original raw data without timestamp loss or recursive raw nesting;
- resume rejects changes to fixed start, cutoff, or native-repost scope.

## Deterministic validation

- Python compile: PASS;
- pytest: PASS (60 tests);
- author, range, native-repost, duplicate-source, quote/reply/media/long-form, protected-target, unavailable-target, empty-surface, fixed-boundary, and independent-scope resume cases are covered;
- Ruff, canonical state validation, workflow contract, and repository secret audit are executed in the atomic W05 apply workflow before publication.

## Security and cost

- real X credentials used: 0;
- authenticated live X requests: 0;
- paid API calls: 0;
- paid proxy calls: 0;
- Codex calls: 0.

No human action was required.
