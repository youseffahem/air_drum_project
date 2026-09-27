"""Phase 18 Task 18.9: regenerate every Experiment 1 table and figure, from stored results and from raw data.

    python scripts/regenerate_phase18.py --run <offline run dir>               # from stored results.json
    python scripts/regenerate_phase18.py --run <offline run dir> --from-raw    # recompute from raw data
        [--reproduction-reason "<why>"]                                       # required for participant data

**Stored:** ``_p18_report.render`` runs on ``results.json`` into ``<run>/regenerated/``. Table and
figure-data digests must equal ``report-manifest.json``. PNG bytes are compared and reported, but
not required: matplotlib output is byte-stable only within one library build.

**From raw:** the lock's held-out sessions are reloaded (the fixture regenerated, or ``ds-v1.0``
through ``load_dataset``). The locked arms and model packages are rebuilt, the confirmatory
computation is repeated, and every number is compared with ``results.json`` (absolute tolerance
``1e-9``).
This reproduction is not a new confirmatory execution. For participant data it needs a stated
reason and appends a ``REPRODUCTION`` line to the ledger.

A second person repeating either command on another machine is the check the phase document's
Evidence line asks for. Its result is recorded in the gate record, not here.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from _p10 import write_json
from _p18 import LEDGER_PATH, ROOT, add_executor_args, build_arm, evidence, read_json
from _p18_report import render
from _runlog import git_sha

from spacedrums.features.schema import FeatureSchema
from spacedrums.live_eval.prereg import Ledger, file_digest
from spacedrums.timing import wall_clock_iso

VOLATILE = {"run_id", "lock", "prereg", "self_checks"}
TOLERANCE = 1e-9


def compare(a: Any, b: Any, path: str = "") -> list[str]:
    """Paths where two JSON values differ (numbers within TOLERANCE are equal)."""
    if isinstance(a, dict) and isinstance(b, dict):
        skip = VOLATILE if path == "" else set()  # run-specific keys exist only in the stored results
        out = [f"{path}/{k}: key only on one side" for k in sorted((set(a) ^ set(b)) - skip)]
        for k in sorted((set(a) & set(b)) - skip):
            out += compare(a[k], b[k], f"{path}/{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} != {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b, strict=True)) for d in compare(x, y, f"{path}/{i}")]
    if isinstance(a, bool) or isinstance(b, bool):
        return [] if a == b else [f"{path}: {a!r} != {b!r}"]
    if isinstance(a, int | float) and isinstance(b, int | float):
        return [] if math.isclose(a, b, rel_tol=0.0, abs_tol=TOLERANCE) else [f"{path}: {a!r} != {b!r}"]
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def stored(run_dir: Path) -> dict[str, Any]:
    results = read_json(run_dir / "results.json")
    manifest = read_json(run_dir / "report-manifest.json")
    again = render(results, run_dir / "regenerated")
    table_diff = [n for n, d in manifest["tables"].items() if again["tables"].get(n) != d]
    data_diff = [n for n, d in manifest["figure_data"].items() if again["figure_data"].get(n) != d]
    png_diff = [n for n, d in manifest["figures"].items() if again["figures"].get(n) != d]
    return {
        "tables": len(manifest["tables"]),
        "figures": len(manifest["figures"]),
        "table_mismatches": table_diff,
        "figure_data_mismatches": data_diff,
        "png_byte_differences": png_diff,
        "png_note": "PNG bytes depend on the matplotlib build; figure data equality is the check",
        "passed": not table_diff and not data_diff,
    }


def from_raw(run_dir: Path, cfg: Any, out: Path) -> dict[str, Any]:
    from run_offline_confirmatory import confirmatory, load_test_sessions

    results = read_json(run_dir / "results.json")
    lock = read_json(Path(results["lock"]["path"]))
    off = lock["offline"]
    schema = FeatureSchema(cfg["zones"])
    arms = {s["arm_id"]: build_arm(s, cfg, dataset=off["dataset"], schema=schema) for s in off["arms"]}
    sessions = load_test_sessions(lock, cfg)
    again = confirmatory(lock, cfg, sessions, arms, out)
    diffs = compare(results, again)
    write_json(out / "results.recomputed.json", again)
    return {
        "differences": diffs[:50],
        "n_differences": len(diffs),
        "passed": not diffs,
        "tolerance": TOLERANCE,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--from-raw", action="store_true")
    ap.add_argument("--reproduction-reason", default=None)
    ap.add_argument("--output", type=Path, default=ROOT / "experiments" / "phase-18")
    add_executor_args(ap)
    args = ap.parse_args()
    results = read_json(args.run / "results.json")
    participant = results["evidence"] == "PARTICIPANT"
    if participant and args.from_raw and not args.reproduction_reason:
        ap.error("a participant from-raw reproduction needs --reproduction-reason (recorded in the ledger)")
    with evidence(
        args,
        slug="regenerate",
        task="18.9",
        description=f"Regeneration of {args.run.name} "
        f"({'from raw data' if args.from_raw else 'from stored results'})",
        output=args.output,
    ) as (run, cfg):
        report: dict[str, Any] = {
            "source_run": str(args.run),
            "evidence": results["label"],
            "results_sha256": file_digest(args.run / "results.json"),
            "stored": stored(args.run),
        }
        if args.from_raw:
            if participant:
                Ledger(LEDGER_PATH)._append(
                    {
                        "event": "REPRODUCTION",
                        "lock_sha256": results["lock"]["sha256"],
                        "run_id": run.run_id,
                        "at": wall_clock_iso(),
                        "git_head": git_sha(),
                        "reason": args.reproduction_reason,
                    }
                )
            report["from_raw"] = from_raw(args.run, cfg, run.dir)
        report["passed"] = report["stored"]["passed"] and report.get("from_raw", {"passed": True})["passed"]
        write_json(run.dir / "regeneration.json", report)
        print(
            json.dumps(
                {k: v for k, v in report.items() if k != "from_raw"}
                | (
                    {"from_raw": {k: report["from_raw"][k] for k in ("n_differences", "passed")}}
                    if args.from_raw
                    else {}
                ),
                indent=2,
            )
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
