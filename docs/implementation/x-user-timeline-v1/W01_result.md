# W01 result

Status: PASS (local deterministic scope)

Implemented:

- installable `x-scrap` Python package and command-line interface;
- local path discovery and credential/data isolation;
- string-ID domain models;
- SQLite WAL jobs, windows, posts, profile snapshots, and events;
- recent timeline and historical search orchestration;
- recursive window splitting and coverage audit;
- JSONL/CSV/manifest/profile/coverage/summary exports;
- Devflow configuration, canonical task state, CI workflows, and secret audit;
- 11 deterministic tests.

Validation:

- `python -m compileall -q src tests`: PASS;
- `pytest -q`: PASS (11 tests);
- Ruff, state, and secret gates are finalized in W02 publication/CI.

Defect caught during W01: persisted profile snapshots expose `user_id`, while the initial reconstruction path accepted only upstream `id/id_str`. The mapping and a resume regression test were added before publication.
