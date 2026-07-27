# W03 result — Page evidence, cursor checkpoints, and atomic ingestion

Status: PASS

## Implemented

- introduced a stable `CollectorPage` contract for operation, cursor pair, parsed items, raw JSON body, capture time, and page index;
- switched the `twscrape` integration to `user_tweets_raw`, `user_tweets_and_replies_raw`, and `search_raw` page streams;
- preserved only the stable upstream JSON body in deterministic gzip artifacts;
- added content-addressed filenames, atomic file replacement, and fixed-path overwrite protection;
- added `harvest_scopes`, `harvest_pages`, and `harvest_page_posts` persistence;
- committed page metadata, post upserts, page-to-post provenance, and cursor advancement in one SQLite transaction;
- distinguished `EXHAUSTED` from `LIMIT_REACHED`, preventing terminal-page interruption from restarting page one;
- resumed search and timeline work from the next committed cursor and remaining item budget;
- rejected repeated/non-advancing cursors, conflicting page indexes, duplicate page payloads, and request-cursor mismatches;
- added schema migration for page time-range columns;
- counted accepted posts distinctly across pages so repeated search results do not inflate window statistics;
- updated README, architecture, and usage documentation to distinguish raw JSON evidence from SQLite metadata and normalized exports.

## Defects found and corrected during W03

1. A rejected conflicting retry could overwrite a fixed raw filename before the database rejected it. Raw artifacts are now immutable and content addressed.
2. A crash after committing a terminal page but before final scope completion could make `next_cursor=NULL` look like an initial request. The explicit `EXHAUSTED` state now finalizes without re-querying.
3. Hashing a metadata envelope included volatile capture timestamps and weakened duplicate-page detection. The artifact hash now covers only the stable upstream JSON body.
4. Per-page accepted counts could double count a post repeated on multiple pages. Scope statistics now count distinct linked post IDs.

## Deterministic validation

The final W03 tree at commit `3eef1c2f0c5e22d8e45416b84381f33610bc5b2b` passed:

- compile: PASS;
- Ruff: PASS;
- full pytest suite: PASS;
- repository-full Product Gate: PASS;
- canonical task-state validation: PASS;
- repository secret audit: PASS.

Tests cover page contracts, raw-page adapter parsing, repeated cursors, immutable raw writes, schema migration, duplicate/conflicting pages, atomic rollback, page-to-post traceability, unique statistics, exact cursor resume, and terminal-page resume.

## Security and cost

- real X credentials used: 0;
- authenticated live X requests: 0;
- paid API calls: 0;
- paid proxy calls: 0;
- Codex calls: 0.

No human action was required.
