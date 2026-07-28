# W09 live timeline pagination hotfix

Status: PASS (deterministic gate); live W09 rerun required.

## Trigger

The first authorized local export failed with:

```text
UpstreamChanged: timeline:user_tweets stopped while a pagination cursor remained
```

No Cookie, account database, raw authenticated response, or private target information was copied into GitHub or chat.

## Root cause

`twscrape==0.19.2` deliberately stops its internal GraphQL page generator after three consecutive empty or filtered pages, even when its last returned content page contained a bottom cursor. This protects the upstream library from an endless sequence of promotional or filtered pages, but it means generator exhaustion does not always prove that the recent user timeline cursor itself reached `None`.

The project previously treated every such recent-timeline stop as a GraphQL schema change. That was too strict because recent user timelines are only a supplemental fast path; exact date-partitioned Search remains the authoritative full-range coverage surface.

## Fix

- A recent timeline that stops after the upstream empty-page guard with a cursor is persisted as `LIMIT_REACHED` with reason `UPSTREAM_TIMELINE_CURSOR_REMAINS`.
- The event is recorded as `TIMELINE_SOURCE_TRUNCATED`, not falsely reported as complete.
- The source is listed in `coverage.json` under `timeline_truncated_sources` and accompanied by an explicit warning.
- Exact historical Search still processes every frozen time window and remains subject to strict cursor exhaustion, recursive window splitting, integrity auditing, and raw-evidence verification.
- A configured finite `--timeline-limit` remains distinguishable as `CONFIGURED_TIMELINE_LIMIT`.
- A resumed job that already contains this terminal timeline state does not retry the same opaque cursor indefinitely.

## Regression coverage

A deterministic adapter fixture reproduces the real condition: one recent timeline page contains a next cursor, then the generator ends. The test proves that:

1. the timeline scope becomes explicitly truncated;
2. Search remains authoritative and supplies exact frozen-range coverage;
3. the final export can still be `COMPLETE_PUBLICLY_RETRIEVABLE` only when all Search windows and evidence checks pass;
4. the truncation warning and source list are present;
5. the event log contains `TIMELINE_SOURCE_TRUNCATED`.

## Validation

The atomic hotfix publication passed:

- Python compilation;
- Ruff;
- complete pytest suite including the new live-regression fixture;
- canonical task-state validation;
- repository secret audit;
- `git diff --check`;
- temporary workflow removal.

Hotfix product commit: `7579f3ed11c608e7a23c784bc2260144a882a067`.

## Local continuation

Update the branch and reinstall the editable package before rerunning the same public target. The previously failed terminal job is retained as evidence; a new run can start without deleting the local Cookie database or prior raw artifacts.
