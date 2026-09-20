# scripts/

One-off tools.

- `env_smoke.py` (Phase 00) - environment import + experiment-log schema check.
- `validate_contracts.py` (Phase 01) - loads every JSON Schema, accepts the valid examples, rejects broken variants, validates `configs/example.candidate.yaml`. Prints `RESULT: PASS|FAIL`.

Run from the repository root:

    .venv\Scripts\python.exe scripts\env_smoke.py
    .venv\Scripts\python.exe scripts\validate_contracts.py
