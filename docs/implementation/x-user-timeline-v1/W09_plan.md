# W09 plan — Local opt-in authenticated end-to-end validation

## Purpose

Validate the remaining behavior that sanitized fixtures cannot truthfully prove: the operator's current X session, current private GraphQL compatibility, real pagination, a real process interruption and cursor resume, and the final self-verifying export bundle.

## Non-negotiable boundary

W09 runs only on the repository owner's local computer. GitHub Actions, shared runners, chat, Issues, PRs, screenshots, and shell arguments must never receive Cookie values, account databases, authorization headers, raw authenticated responses, exported posts, or unredacted errors.

## Automated procedure

The preferred entrypoint is the PowerShell orchestrator:

```powershell
.\scripts\live\run_w09.ps1 `
  -Home D:\x_scrap_private `
  -SmallUsername <PUBLIC_USERNAME> `
  -VolumeUsername <PUBLIC_USERNAME>
```

It performs, in order:

1. deterministic compile and test preflight;
2. private-state and telemetry setup;
3. exactly-one-active-account validation, with an optional no-echo Cookie prompt;
4. a new small fixed-range job;
5. a new controlled job interrupted immediately after one committed page;
6. a resume run tied to the interruption report's exact job, target fingerprint, range, committed page hashes, next page index, and nonempty cursor;
7. a new higher-volume historical job;
8. individual report validation;
9. cross-report acceptance validation and creation of `W09_ACCEPTANCE.json` under `X_SCRAP_HOME/live-evidence`.

Every non-resume case explicitly creates a new job. The resume case can only continue the job named by the private interruption checkpoint; this prevents a stale partial job for the same username from being selected accidentally.

## Required evidence

The acceptance validator requires exactly four sanitized reports:

- `small-fixed-range.json`;
- `interruption-resume.json`;
- `interruption-resume-final.json`;
- `higher-volume.json`.

Automatic W09 acceptance requires:

- Python 3.12 and `twscrape==0.19.2`;
- telemetry disabled;
- exactly one active local account;
- no proxy environment for the automatic acceptance path;
- zero paid API, paid proxy, and Codex calls;
- all three completed cases ending `COMPLETED / COMPLETE_PUBLICLY_RETRIEVABLE`;
- zero same-ID conflicts, gaps, unresolved windows, and integrity findings;
- at least one committed page in the small case;
- at least one committed page plus a nonempty next cursor at the interruption checkpoint;
- the final resume using the same job, target fingerprint, and frozen range;
- every pre-interruption page hash and metadata tuple remaining unchanged;
- the first page after the checkpoint using the persisted request cursor;
- the higher-volume case committing at least two pages and traversing historical windows;
- every final export bundle passing inventory/hash/record verification.

A natural 429 is useful but not mandatory. The tool must not create aggressive traffic merely to manufacture one. If a real 429 occurs, the sanitized report records only aggregate wait counts; the runtime itself preserves reset-aware recovery events locally.

## True stop conditions

Remain at W09 and record a human/product gate when any of these occurs:

- expired or challenged local session;
- protected or unavailable target;
- current GraphQL operation/schema incompatibility;
- a source range that cannot reach complete observable coverage;
- a resume checkpoint without a remaining cursor;
- an unresolved same-ID material conflict;
- proxy use that cannot be excluded or explicitly reviewed;
- any possible credential or private-path leakage.

Do not bypass account challenges, access controls, CAPTCHA, or source limitations.

## Exit and continuation

After `W09_ACCEPTANCE.json` validates, commit only the sanitized acceptance evidence or a manually reviewed equivalent, write `W09_result.md`, and advance directly through W10 final review, PR readiness, merge, and exact-main Post-Merge validation. Routine intermediate confirmations are not required.
