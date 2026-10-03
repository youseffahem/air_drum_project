"""Live-responsiveness diagnosis (2026-10-02): where the live loop loses tracking, frames and strikes.

    python scripts/diagnose_responsiveness.py replay --input data/dev-captures/swing-L2-exp-5 \
        --input data/dev-sessions/dev-20260928-1442-playability --label baseline --output <dir>
    python scripts/diagnose_responsiveness.py paced --input data/dev-captures/dist-d080-L2-exp-6 \
        --repeats 3 --label baseline --output <dir> [--render none|headless|window]
    python scripts/diagnose_responsiveness.py pool --runs <dir>/<label> [--select <name> ...] --output <file>
    python scripts/diagnose_responsiveness.py compare --a <dir>/<label-a> --b <dir>/<label-b> --output <file>
    python scripts/diagnose_responsiveness.py synthetic --output <dir>     # SYNTHETIC self-test

``replay`` runs recorded frames through ``spacedrums.app.main.run`` with their recorded timestamps
(deterministic decisions; real stage timings). ``paced`` pushes the recorded frames through the live
capture thread and bounded queue at their recorded intervals in real time (real compute, real
drops). Each run writes ``rows.jsonl`` (one row per delivered frame: timing per stage, queue depth
and frame age, hands, identity, stick, tracker status, reset cause, candidates, commit decisions,
commits, audio events), ``summary.json`` and the app summary. ``--config`` layers config files in
order (a candidate override goes last). Development diagnostics only: no participant data, no
ground truth; replayed or paced recordings are not live measurements at the owner's lighting.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _resp import (  # noqa: E402
    PATCHES,
    ROOT,
    describe_input,
    load_images,
    pooled,
    read_rows,
    run_dirs,
    run_input,
    tip_shift,
    write_json,
)

DEFAULT_CONFIG = ROOT / "configs" / "prototype.candidate.yaml"


def _bins(text: str | None):
    if not text:
        return None
    lo, hi = (float(x) for x in text.split(","))
    return (lo, hi)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("replay", "paced", "synthetic"):
        p = sub.add_parser(name)
        p.add_argument("--output", type=Path, required=True)
        p.add_argument("--label", default=name)
        p.add_argument("--config", nargs="+", type=Path, default=[DEFAULT_CONFIG])
        p.add_argument("--render", choices=("none", "headless", "window"), default="none")
        p.add_argument("--max-frames", type=int, default=None)
        p.add_argument(
            "--speed-bins", default=None, help="slow/normal and normal/fast wrist-speed limits 'a,b'"
        )
        p.add_argument("--patch", choices=PATCHES, default="none", help="report-only research variant")
        if name != "synthetic":
            p.add_argument("--input", type=Path, action="append", required=True)
        else:
            p.add_argument("--scenario", default="rapid")
        if name == "paced":
            p.add_argument("--repeats", type=int, default=3)
    p = sub.add_parser("pool")
    p.add_argument("--runs", type=Path, required=True)
    p.add_argument("--select", action="append", default=None, help="input name prefixes to include")
    p.add_argument("--speed-bins", default=None)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("compare")
    p.add_argument("--a", type=Path, required=True)
    p.add_argument("--b", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = ap.parse_args(argv)

    if args.cmd in ("replay", "paced"):
        bins = _bins(args.speed_bins)
        for path in args.input:
            inp = describe_input(path)
            images = load_images(path, args.max_frames) if args.cmd == "paced" else None
            for repeat in range(args.repeats if args.cmd == "paced" else 1):
                out = (
                    args.output / args.label / (inp["name"] + (f"-r{repeat}" if args.cmd == "paced" else ""))
                )
                s = run_input(
                    inp,
                    mode=args.cmd,
                    configs=args.config,
                    out_dir=out,
                    label=args.label,
                    render=args.render,
                    max_frames=args.max_frames,
                    repeat=repeat,
                    images=images,
                    speed_bins=bins,
                    harness=args.patch,
                )
                ent = s.get("entries", {})
                valid = s["valid_fraction"]
                print(
                    f"[resp] {args.label} {out.name}: frames {s['frames']} "
                    f"fps {s.get('delivered_fps') or 0:.2f} "
                    f"proc p50 {s['processing_ms'].get('p50', 0):.1f} ms "
                    f"drop {s['dropped_percent_of_offered']:.1f}% "
                    f"VALID L/R {valid['LEFT']:.2f}/{valid['RIGHT']:.2f} "
                    f"entries {ent.get('entries')} discarded {ent.get('discarded')} "
                    f"reacq/min {s.get('reacquisitions_per_min') or 0:.1f}",
                    flush=True,
                )
            del images
        return 0
    if args.cmd == "synthetic":
        inp = {
            "name": f"synthetic-{args.scenario}",
            "path": None,
            "kind": "SYNTHETIC",
            "exposure": None,
            "capture_stats": None,
            "segments": None,
            "calibration": None,
        }
        s = run_input(
            inp,
            mode="synthetic",
            configs=args.config,
            out_dir=args.output / args.label / inp["name"],
            label=args.label,
            render="none",
            max_frames=args.max_frames,
            scenario=args.scenario,
        )
        print(f"[resp] SYNTHETIC {args.scenario}: frames {s['frames']}, commits {s['commits']['total']}")
        return 0
    if args.cmd == "pool":
        dirs = run_dirs(args.runs)
        if args.select:
            dirs = [d for d in dirs if any(d.name.startswith(prefix) for prefix in args.select)]
        if not dirs:
            ap.error("no runs selected")
        write_json(args.output, pooled(dirs, speed_bins=_bins(args.speed_bins)))
        print(f"[resp] pooled {len(dirs)} runs -> {args.output}")
        return 0
    a = {d.name: d for d in run_dirs(args.a)}
    b = {d.name: d for d in run_dirs(args.b)}
    common = sorted(set(a) & set(b))
    result = {name: tip_shift(a[name], b[name]) for name in common}
    for name in common:  # frame sets must match for a paired replay comparison
        result[name]["frames_a"] = len(read_rows(a[name]))
        result[name]["frames_b"] = len(read_rows(b[name]))
    write_json(args.output, result)
    print(f"[resp] compared {len(common)} inputs -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
