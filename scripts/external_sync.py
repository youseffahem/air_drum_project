"""Phase 18 Task 18.5: align an external recording with a recorded live session (``t_mono``).

    python scripts/external_sync.py --session <session dir> --method M1 --recording <wav>
    python scripts/external_sync.py --session <session dir> --method M2 --recording <video> --roi x,y,w,h

**M1 (microphone).** Every played sample is located in the recording (normalised
cross-correlation with its bank template). The located train is aligned with the session's
``AudioEvent.t_target_play`` train by offset search plus a drift fit
(``live_eval.sync.align_event_trains``). The system's own drum sounds are the sync events, with
operator claps as a fallback. The fit maps recording time to ``t_mono``. It attributes each sound
to its ``strike_id``, and so to the arm that sounded; the latency itself is a within-recording
difference.

**M2 (video).** Per-frame brightness in the ROI gives flash onsets. These are aligned with the
session's FLASH sync markers.

Either way, the result goes into ``live-session.json`` as ``external_methods[].sync``: status,
reason, matched count and map. A FAILED sync is kept with its reason and excludes that session's
external latencies (pre-registration §7). The recording's SHA-256 is recorded next to it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _p10 import write_json  # noqa: E402
from _p18 import ROOT, add_executor_args, evidence  # noqa: E402
from _p18_live import m1_session, pad_windows, read_json  # noqa: E402

from spacedrums.calib import load_calibrated_config  # noqa: E402
from spacedrums.live_eval.metadata import LiveSessionMetadata  # noqa: E402
from spacedrums.live_eval.prereg import file_digest  # noqa: E402
from spacedrums.live_eval.sync import align_event_trains, detect_flashes  # noqa: E402
from spacedrums.live_eval.video import brightness_series  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", type=Path, required=True)
    ap.add_argument("--method", choices=("M1", "M2"), required=True)
    ap.add_argument("--recording", type=Path, required=True)
    ap.add_argument("--roi", default=None, help="M2: x,y,w,h of the flash / LED region")
    ap.add_argument("--output", type=Path, default=ROOT / "experiments" / "phase-18")
    add_executor_args(ap)
    args = ap.parse_args()
    live = LiveSessionMetadata.read(args.session)
    base = read_json(args.session / "metadata.json")
    with evidence(
        args,
        slug=f"external-sync-{args.method.lower()}",
        task="18.5",
        description=f"{args.method} sync of {live.data['session_id']} ({live.data['evidence_label']})",
        output=args.output,
    ) as (run, _cfg):
        cfg = load_calibrated_config(args.session / "config.snapshot.yaml").config
        if args.method == "M1":
            result = m1_session(args.session, cfg, args.recording, pad_windows=pad_windows(base))
            sync = result["sync"]
            n = len(result.get("strikes", []))
            record = {
                "status": sync["status"],
                "reason": sync["reason"],
                "n_matched": sync["n_matched"],
                "map": sync["map"],
            }
            write_json(run.dir / "m1-session.json", result)
            print(f"[sync] M1 {sync['status']} ({sync['reason']}); paired strikes {n}")
        else:
            roi = tuple(int(v) for v in args.roi.split(",")) if args.roi else None
            series = brightness_series(args.recording, roi=roi)
            flashes = detect_flashes(series["brightness"], series["times_s"])
            markers = [m["t_mono"] for m in live.data["sync_markers"] if m["kind"] == "FLASH"]
            aligned = align_event_trains(
                flashes["onsets_s"], markers, tolerance_s=max(2 * flashes["frame_period_s"], 0.01)
            )
            record = {
                "status": aligned["status"],
                "reason": aligned["reason"],
                "n_matched": len(aligned["matches"]),
                "map": aligned["map"],
            }
            write_json(
                run.dir / "m2-flashes.json",
                {
                    "series": {
                        k: series[k]
                        for k in ("n_frames", "frame_period_s", "frame_period_p95_s", "advertised_fps")
                    },
                    "flashes": flashes,
                    "alignment": aligned,
                },
            )
            print(
                f"[sync] M2 {aligned['status']} ({aligned['reason']}); "
                f"frame period {series['frame_period_s']}"
            )
        method = next(m for m in live.data["external_methods"] if m["method"] == args.method)
        recording = next(
            (r for r in method["recordings"] if Path(r["path"]).name == args.recording.name), None
        )
        if recording is not None and recording["sha256"] != file_digest(args.recording):
            raise ValueError("the recording differs from the one registered in live-session.json")
        live.set_method(args.method, sync=record)
        live.write(args.session)
        write_json(run.dir / "sync.json", record)
    return 0 if record["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
