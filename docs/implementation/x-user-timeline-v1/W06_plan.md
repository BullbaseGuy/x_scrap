# W06 plan — Historical search partitions

1. Use the canonical resolved username for `from:` queries and independently enforce the stable resolved user ID on every accepted result.
2. Require whole-second fixed boundaries so `since_time` and `until_time` cannot introduce fractional-second gaps.
3. Keep all windows half-open `[start, end)` and split dense windows at an exact integer-second midpoint.
4. Treat a remaining cursor at the configured source budget as saturation, recursively split until source exhaustion or the minimum window size.
5. Preserve parent, child, page, cursor, unique-post, and raw-response evidence so interrupted child windows resume without replaying completed siblings.
6. Filter noisy foreign-author and out-of-window search results while retaining the immutable original page payload.
7. Validate duplicate results across windows, exact boundaries, dense-window recursion, minimum-window partial status, canonical username changes, and child-window resume.
8. Run compile, Ruff, full tests, state consistency, workflow contract, and secret audit before advancing to W07.

Exit criteria: the requested range has contiguous terminal leaf windows; every accepted search result matches the stable user ID and exact half-open range; saturation never masquerades as source exhaustion.
