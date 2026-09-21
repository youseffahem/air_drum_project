"""Phase 05 — render the commit / candidate frames of a recorded session for manual review (Tasks 05.1, 05.7).

    python scripts/render_session_frames.py --session-dir data/dev-sessions/<id> --out docs/figures/phase-05
    python scripts/render_session_frames.py --session-dir ... --frames 40 41 42     # explicit frames

Draws, on the recorded frame, the candidate zone layout (Phase 04 overlay), the filtered tip of both
hands, the predicted trajectory of the rule arm and the impact position of every candidate / commit on
that frame, so a person can check whether commits appear where the tip visibly enters a zone. Pure
rendering of recorded records; it changes no decision and produces no evidence by itself.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))

from spacedrums.app.session_summary import load_session  # noqa: E402
from spacedrums.capture import ReplayFrameSource, Roi  # noqa: E402
from spacedrums.geometry import ZoneRegistry  # noqa: E402
from spacedrums.timing.logger import read_record_stream  # noqa: E402
from spacedrums.ui import draw_zones  # noqa: E402

COLOR = {"LEFT": (0, 200, 255), "RIGHT": (255, 120, 0)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--frames", type=int, nargs="*", default=None,
                    help="frame ids (default: every commit frame)")
    ap.add_argument("--context", type=int, default=1, help="also render +/- this many neighbouring frames")
    args = ap.parse_args(argv)
    d = args.session_dir
    session = load_session(d)
    registry = ZoneRegistry.load(d / "config.snapshot.yaml")
    src = ReplayFrameSource(d)
    by_id = {s.frame_id: s for s in src.samples}
    tracks = {(t["frame_id"], t["hand_id"]): t for t in session["TrackState"]}
    pred_rows = read_record_stream(d / "records" / "TrajectoryPrediction.jsonl")[1]
    preds = {(p["frame_id"], p["hand_id"]): p for p in pred_rows}
    cands_by_frame: dict[int, list] = {}
    for c in session["StrikeCandidate"]:
        cands_by_frame.setdefault(c["frame_id"], []).append(c)
    commits_by_frame: dict[int, list] = {}
    for c in session["CommittedStrike"]:
        commits_by_frame.setdefault(c["frame_id"], []).append(c)
    frames = args.frames if args.frames is not None else sorted(commits_by_frame)
    wanted = sorted({f + k for f in frames for k in range(-args.context, args.context + 1) if f + k in by_id})
    args.out.mkdir(parents=True, exist_ok=True)
    for fid in wanted:
        sample = by_id[fid]
        view = src.view(sample)
        img = view.full.copy() if view.full is not None else view.roi.copy()
        roi = Roi.from_rect(sample.roi_px) if view.full is not None else Roi(0, 0, img.shape[1], img.shape[0])
        img[roi.y : roi.y1, roi.x : roi.x1] = draw_zones(img[roi.y : roi.y1, roi.x : roi.x1], registry)

        def px(p, roi=roi):
            return (int(roi.x + p[0] * (roi.w - 1)), int(roi.y + p[1] * (roi.h - 1)))

        y = 18
        for hand in ("LEFT", "RIGHT"):
            t = tracks.get((fid, hand))
            if t is None:
                continue
            txt = f"{hand} {t['status']} c={t['confidence']:.2f}"
            if t["tip_filtered"] is not None:
                cv2.drawMarker(img, px(t["tip_filtered"]), COLOR[hand], cv2.MARKER_CROSS, 14, 2)
            p = preds.get((fid, hand))
            if p is not None:
                pts = [px(q) for q in p["positions"]]
                for a, b in zip(pts, pts[1:], strict=False):
                    cv2.line(img, a, b, (255, 200, 0), 1, cv2.LINE_AA)
            cv2.putText(img, txt, (roi.x + 6, roi.y + y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR[hand], 1)
            y += 18
        for c in cands_by_frame.get(fid, []):
            col = (0, 255, 255) if c["source"] == "RULE" else (255, 255, 255)
            cv2.drawMarker(img, px(c["impact_position"]), col, cv2.MARKER_TILTED_CROSS, 14, 2)
            cv2.putText(img, f"cand {c['source']} {c['hand_id']} {c['zone_id']}", (roi.x + 6, roi.y + y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1)
            y += 18
        for c in commits_by_frame.get(fid, []):
            col = (0, 0, 255) if not c["shadow"] else (128, 128, 255)
            label = f"COMMIT {c['arm']}{' shadow' if c['shadow'] else ''} {c['hand_id']} {c['zone_id']}"
            cv2.putText(img, label, (roi.x + 6, roi.y + y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
            y += 20
        cv2.putText(img, f"{d.name} frame {fid} t_capture={sample.t_capture:.3f}", (8, img.shape[0] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        out = args.out / f"{d.name}-f{fid:06d}.png"
        cv2.imwrite(str(out), img)
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
