# Task contract: x-user-timeline-v1

## Objective

Given one public X username and an authorized local browser-cookie session, collect the account's currently publicly retrievable authored posts for a fixed UTC range in one resumable task.

## Included

- original posts, replies, self-replies, threads, and quote posts;
- recent timeline plus date-partitioned historical search;
- local SQLite checkpoints and post-ID deduplication;
- automatic bounded recovery for rate limits and transient failures;
- JSONL, CSV, profile, manifest, coverage, and summary outputs;
- synthetic deterministic CI tests;
- zero paid API or proxy dependency.

## Excluded

- protected/private data or access-control bypass;
- CAPTCHA bypass and automated account registration;
- purchased account/proxy integration;
- deleted, removed, suspended, de-indexed, or search-suppressed recovery guarantees;
- a historical native-repost completeness guarantee;
- authenticated live X calls from GitHub Actions;
- automatic merge or Codex execution.

## Completeness definition

`COMPLETE_PUBLICLY_RETRIEVABLE` requires every leaf search window covering the requested range to be terminally complete with no time gaps. It describes the observable source surface at collection time, not all content that ever existed.

## Security contract

X cookies, passwords, local account databases, exports, and network captures remain outside Git. Logs and account listing commands must not print cookie values. Telemetry is disabled by default.

## Stop conditions

Stop and persist a human gate for an account challenge, expired credentials that require manual action, destructive operation, new legal/compliance decision, or material architecture choice. Upstream schema breakage is a diagnosed product block, not an empty result.
