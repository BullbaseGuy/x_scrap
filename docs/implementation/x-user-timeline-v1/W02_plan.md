# W02 plan — Dependency and adapter contract

1. Pin and document `twscrape==0.19.2` and its MIT license.
2. Verify Python 3.12 support and required async surfaces.
3. Keep imports and upstream exception heuristics inside `TwscrapeAdapter`.
4. Disable upstream telemetry before import.
5. Validate cookie input and ensure account listing is redacted.
6. Add adapter tests for missing cookies, error classification, and lazy dependency loading.
7. Document the gap between normalized model artifacts and full raw HTTP pages.
8. Publish the branch, open a Draft PR, and run repository gates.

Exit criteria: adapter contract tests and all deterministic CI gates pass; no secret or credential data is present.
