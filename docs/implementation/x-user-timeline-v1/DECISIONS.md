# Decisions

## D001 — Local-first credentials and data

Account cookies, account DB, job DB, exports, and source artifacts live outside the repository under `X_SCRAP_HOME`.

## D002 — `twscrape` behind an adapter

Pin `twscrape==0.19.2`; do not copy private GraphQL implementation. Keep a replaceable protocol boundary.

## D003 — Conservative single-account default

Use one local account and upstream rate-limit waiting by default. Do not optimize around multi-account evasion.

## D004 — Fixed cutoff and half-open windows

Every job freezes its cutoff and traverses `[start, cutoff)` in contiguous windows.

## D005 — String identifiers

X user and post IDs are persisted and exported as strings to avoid numeric precision loss.

## D006 — Observable-source completeness

Only claim continuous traversal of publicly retrievable source windows. Never equate it with recovery of deleted or hidden history.

## D007 — No agent execution

Codex and paid agent execution remain disabled; current call count is zero.
