"""Phase 05, Tasks 05.4 / 05.9 — README section 5.3 timing decomposition of a recorded session.

    python scripts/timing_summary.py --session-dir data/dev-sessions/<session_id>
    python scripts/timing_summary.py --synthetic       # SYNTHETIC self-test (temporary synthetic session)

Reads ``timing.jsonl`` (+ ``session.json`` for the producer) and prints the per-component table with
its labels (software-stamped; ``_est`` = software-estimated) and the ``L_sys_est`` term list. For a
LIVE session every term is computable; ``L_sys_est`` additionally needs a MEASURED audio output latency
(``t_audio_out_est`` non-null), which is PENDING on HW-01 — the table then says so. For REPLAY /
SYNTHETIC sessions the cross-clock terms are N/A (architecture.md section 12.1). Nothing printed here is
an external latency measurement (README section 5.4: ``L_sys`` proper needs Phase 18's instrument).
Writes an experiment run with the decomposition JSON.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _p05 import DEFAULT_CONFIG, run_synthetic_session  # noqa: E402
from _runlog import RunLog  # noqa: E402

from spacedrums.app.session_summary import summarise_session  # noqa: E402
from spacedrums.config import load_config  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--experiments-dir", type=Path, default=None)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--session-dir", type=Path, default=None)
    mode.add_argument("--synthetic", action="store_true")
    ap.add_argument("--hardware-id", default="HW-01")
    args = ap.parse_args(argv)

    tmp: Path | None = None
    try:
        if args.synthetic:
            tmp = Path(tempfile.mkdtemp(prefix="p05-timing-synth-"))
            summary = run_synthetic_session(
                "repeated",
                out_dir=tmp,
                session_id="synthetic-timing",
                active="A",
                shadow=("B",),
                config=args.config,
            )
            session_dir = Path(summary["session_dir"])
            cfg = load_config(args.config)
        else:
            session_dir = args.session_dir
            snapshot = session_dir / "config.snapshot.yaml"
            cfg = load_config(snapshot if snapshot.exists() else args.config)
        ss = summarise_session(session_dir)
        dec = ss["timing_decomposition"]
        producer = ss["session"].get("producer")
        label = "SYNTHETIC self-test" if args.synthetic else f"session {session_dir.name} ({producer})"
        desc = (
            f"Tasks 05.4/05.9 timing decomposition (software-stamped) of {label}. "
            + ("Cross-clock terms N/A (replay). " if not dec["live"] else "")
            + (
                "L_sys_est PENDING: no MEASURED audio output latency (Phase 04 criterion 6)."
                if not dec["audio_out_est_available"]
                else ""
            )
        )
        with RunLog(
            phase="05",
            task="05.9",
            slug="p05-timing-summary" + ("-synthetic" if args.synthetic else ""),
            config=cfg,
            experiments_dir=args.experiments_dir,
            description=desc,
            hardware_id=args.hardware_id,
        ) as runlog:
            print(
                f"session: {session_dir}  producer={producer}  frames={dec['n_frames']}  "
                f"strikes={dec['n_strikes']}"
            )
            print(ss["timing_table_markdown"])
            print(f"L_sys_est terms: {' + '.join(dec['L_sys_est_terms'])}  ({dec['L_sys_est_rule']})")
            runlog.write_json_artefact(
                "timing_decomposition.json",
                {
                    "label": (
                        "SYNTHETIC" if args.synthetic else "MEASURED (software-stamped, developer session)"
                    ),
                    "session_dir": str(session_dir),
                    "producer": producer,
                    "decomposition": dec,
                    "table_markdown": ss["timing_table_markdown"],
                    "counts": ss["counts"],
                },
            )
            runlog.finish(
                {
                    "label": "SYNTHETIC" if args.synthetic else "software-stamped",
                    "n_frames": dec["n_frames"],
                    "n_strikes": dec["n_strikes"],
                    "live": dec["live"],
                    "audio_out_est_available": dec["audio_out_est_available"],
                }
            )
            print(f"\nRESULT: COMPLETED {runlog.run_id}")
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
