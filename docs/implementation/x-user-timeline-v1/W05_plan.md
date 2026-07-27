# W05 plan — Recent user timelines

1. Treat `UserTweets` and `UserTweetsAndReplies` as independently resumable page scopes.
2. Filter every accepted item to the resolved stable user ID and fixed job cutoff.
3. Preserve original posts, replies, self-replies, and quote posts; exclude native reposts unless explicitly requested.
4. Validate duplicate items across timeline surfaces, edited/long-form text, media metadata, and relation IDs.
5. Make timeline completion explicit and prevent a partial or silently empty upstream response from being misreported as a complete historical export.
6. Add deterministic tests for protected users, invalid users, source filtering, cutoff filtering, terminal pages, repeated cursors, and interrupted-page resume.
7. Run compile, Ruff, full tests, state consistency, workflow contract, and secret audit before advancing to W06.

Exit criteria: both recent timeline scopes are page-resumable, author/cutoff filtered, deduplicated, terminally classified, and covered by deterministic tests without a real X credential.
