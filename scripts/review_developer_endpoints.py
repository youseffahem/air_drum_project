"""Offline developer endpoint investigation. Never opens a camera or audio device.

Saved current-frame hand observations isolate endpoint perception from the detector.
Coordinates are unmirrored full-frame pixels, unlike the original review sheets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from spacedrums.contracts import FrameSample, FrameView, HandObservation, ImageRef
from spacedrums.stick.estimator import StickSettings
from spacedrums.stick.visible import VisibleEndpointEstimator, VisibleSettings


def load_capture(source):
    report = json.loads((source / "report.json").read_text())
    rows = [json.loads(s) for s in (source / "observations.jsonl").read_text().splitlines()]
    assert len(rows) == report["overall"]["frames"]
    assert all(b["t_capture"] > a["t_capture"] for a, b in zip(rows, rows[1:], strict=False))
    images = [cv2.imread(str(source / r["image"])) for r in rows]
    assert all(im is not None and im.shape == (480, 640, 3) for im in images)
    return report, rows, images


def view_for(row, image, roi):
    x, y, w, h = roi
    sample = FrameSample(
        row["frame_id"],
        row["t_capture"],
        row["t_capture"],
        "GRAB_RETURN",
        (image.shape[1], image.shape[0]),
        tuple(roi),
        ImageRef.memory(image),
        "saved-endpoint-check",
        row["dropped_since_last"],
    )
    return FrameView(sample, image[y : y + h, x : x + w], image)


def quantiles(values):
    return (
        dict(zip(("p50", "p95", "max"), map(float, np.percentile(values, [50, 95, 100])), strict=True))
        if values
        else None
    )


def longest_run(rows, flags, gap=0.115):
    runs, current = [], []
    for i, ok in enumerate(flags):
        if current and (not ok or rows[i]["t_capture"] - rows[current[-1]]["t_capture"] > gap):
            runs.append(current)
            current = []
        if ok:
            current.append(i)
    if current:
        runs.append(current)
    best = max(runs, key=lambda r: rows[r[-1]]["t_capture"] - rows[r[0]]["t_capture"], default=[])
    return {
        "count": len(runs),
        "longest_frames": len(best),
        "longest_span_s": rows[best[-1]]["t_capture"] - rows[best[0]]["t_capture"] if best else 0,
        "longest_frame_ids": [rows[i]["frame_id"] for i in best],
    }


def summarize(rows, outputs):
    flat = [e for r in outputs for e in r]
    both = [len(r) == 2 and all(e["kind"] == "MEASURED" for e in r) for r in outputs]
    n = sum(e["kind"] == "MEASURED" for e in flat)
    hands = sum(h["present"] for r in rows for h in r["hands"])
    return {
        "accepted": n,
        "accepted_given_hand": n / hands if hands else None,
        "reasons": dict(Counter(e["reason"] for e in flat)),
        "both_frames": sum(both),
        "both_fraction": sum(both) / len(rows),
        "both_runs": longest_run(rows, both),
        "per_hand_runs": {
            h: longest_run(
                rows, [any(e["hand_id"] == h and e["kind"] == "MEASURED" for e in r) for r in outputs]
            )
            for h in ("LEFT", "RIGHT")
        },
    }


def inventory(report, rows):
    reasons = Counter(e["reason"] for r in rows for e in r["endpoints"])
    no_axis = Counter()
    short = Counter()
    components = Counter()
    for r in rows:
        for e in r["endpoints"]:
            an = r["stages"][e["hand_id"]]
            if an is None:
                continue
            if e["reason"] == "NO_VISIBLE_AXIS":
                if not an["candidate_pixels"]:
                    no_axis["no_kept_candidate_pixels"] += 1
                    if not an["edge_pixels"]:
                        no_axis["no_edges"] += 1
                    for reason in set(c["reject_reason"] for c in an["components"]):
                        components[str(reason)] += 1
                else:
                    no_axis["candidate_pixels_but_axis_fit_failed"] += 1
            if e["reason"] == "WEAK_OR_SHORT_SUPPORT":
                h = next(h for h in r["hands"] if h["hand_id"] == e["hand_id"])
                from spacedrums.hands.grip import grip_reference

                grip = grip_reference(
                    HandObservation.from_dict(h),
                    StickSettings.from_config(report["config"]).grip,
                    roi_aspect=640 / 480,
                )
                span = max(8, np.linalg.norm(np.array(grip.span_vec) * [640, 480]))
                a = an["axis"]
                short[f"weak={a['confidence'] < 0.4},short={a['support_len_px'] < max(18, 0.75 * span)}"] += 1
    return {
        "unit": "hand-frame; component categories overlap",
        "reasons": dict(reasons),
        "no_axis": dict(no_axis),
        "no_candidate_component_reasons": dict(components),
        "weak_short": dict(short),
    }


def make_review_sheets(rows, images, output):
    ids = sorted(
        {min(range(len(rows)), key=lambda i: abs(rows[i]["elapsed_s"] - t)) for t in np.arange(0.5, 24, 1.0)}
    )
    for start in range(0, len(ids), 4):
        panels = []
        for idx in ids[start : start + 4]:
            r, im = rows[idx], images[idx].copy()
            # Label landmarks only; no endpoint predictions to bias tip annotation.
            for h in r["hands"]:
                if h["present"]:
                    lm = np.asarray(h["landmarks"]) * [640, 480]
                    xy = tuple(np.rint(lm[0]).astype(int))
                    cv2.putText(
                        im,
                        h["hand_id"],
                        (xy[0] + 8, xy[1]),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.45,
                        (255, 200, 50),
                        1,
                    )
            for x in range(0, 640, 40):
                cv2.line(im, (x, 0), (x, 479), (70, 70, 70), 1)
                cv2.putText(im, str(x), (x + 2, 15), 0, 0.35, (240, 240, 240), 1)
            for y in range(40, 480, 40):
                cv2.line(im, (0, y), (639, y), (70, 70, 70), 1)
                cv2.putText(im, str(y), (2, y - 3), 0, 0.35, (240, 240, 240), 1)
            header = np.zeros((28, 640, 3), np.uint8)
            cv2.putText(
                header,
                f"RAW {idx:04d} frame {r['frame_id']} t={r['elapsed_s']:.3f} step {r['step']}",
                (8, 20),
                0,
                0.5,
                (255, 255, 255),
                1,
            )
            panels.append(np.vstack([header, im]))
        sheet = np.vstack([np.hstack(panels[:2]), np.hstack(panels[2:])])
        cv2.imwrite(str(output / f"annotation-sheet-{start // 4 + 1}.jpg"), sheet)
    return [rows[i]["frame_id"] for i in ids]


def run_existing(report, rows, images, mode):
    estimator = VisibleEndpointEstimator(
        StickSettings.from_config(report["config"]),
        VisibleSettings(**report["config"]["product"]["endpoint"]),
        mode=mode,
    )
    outputs, costs, analyses = [], [], []
    for r, im in zip(rows, images, strict=True):
        view = view_for(r, im, report["config"]["roi"]["px"])
        hands = [HandObservation.from_dict(h) for h in r["hands"]]
        begin = time.perf_counter()
        entries, stages = [], {}
        for h in hands:
            estimator.last_analysis = None
            estimator.estimate(view, h)
            entries.append(estimator.evidence[h.hand_id].to_dict())
            an = estimator.last_analysis
            if an:
                stages[str(h.hand_id)] = {
                    "axis": asdict(an.axis) if an.axis else None,
                    "polygon": an.region.polygon_px.tolist() if an.region else None,
                    "grip": an.grip_px,
                    "support_pixels": an.segment.candidate_px.tolist() if an.segment else [],
                }
        costs.append((time.perf_counter() - begin) * 1000)
        outputs.append(entries)
        analyses.append(stages)
    return outputs, costs, analyses


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=Path("experiments/developer-endpoint-check-20261004-01"))
    p.add_argument("--output", type=Path, default=Path("experiments/developer-endpoint-offline-20261004-01"))
    p.add_argument("--prepare", action="store_true")
    p.add_argument("--candidates-only", action="store_true")
    args = p.parse_args()
    cv2.setNumThreads(1)
    args.output.mkdir(parents=True, exist_ok=True)
    report, rows, images = load_capture(args.source)
    result = {
        "source": str(args.source),
        "frames": len(rows),
        "coordinate_system": "raw unmirrored ROI pixels",
        "source_observation_sha256": hashlib.sha256(
            (args.source / "observations.jsonl").read_bytes()
        ).hexdigest(),
        "live_baseline": summarize(rows, [r["endpoints"] for r in rows]),
        "failure_inventory": inventory(report, rows),
    }
    if args.prepare:
        result["review_frame_ids"] = make_review_sheets(rows, images, args.output)
        (args.output / "inventory.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
        return
    if args.candidates_only:
        result = json.loads((args.output / "comparison.json").read_text())
    for mode in () if args.candidates_only else ("support", "paired"):
        outputs, costs, analyses = run_existing(report, rows, images, mode)
        result[mode] = {
            "overall": summarize(rows, outputs),
            "two_hand_compute_ms": quantiles(costs),
            "by_step": {
                str(s): summarize(
                    [r for r in rows if r["step"] == s],
                    [o for r, o in zip(rows, outputs, strict=True) if r["step"] == s],
                )
                for s in (1, 2, 3, 4)
            },
        }
        (args.output / f"{mode}.jsonl").write_text(
            "\n".join(
                json.dumps({"frame_id": r["frame_id"], "endpoints": o, "compute_ms": c, "stages": an})
                for r, o, c, an in zip(rows, outputs, costs, analyses, strict=True)
            )
            + "\n"
        )
    from _endpoint_candidate import ProfileEndpointCandidate, serializable

    for mode in ("profile_single", "profile_temporal"):
        est = ProfileEndpointCandidate(
            StickSettings.from_config(report["config"]).grip, temporal=mode == "profile_temporal"
        )
        outputs, costs = [], []
        with (args.output / f"{mode}.jsonl").open("w") as f:
            for r, im in zip(rows, images, strict=True):
                view = view_for(r, im, report["config"]["roi"]["px"])
                hands = [HandObservation.from_dict(h) for h in r["hands"]]
                begin = time.perf_counter()
                entries, diag = est.process(view, hands)
                cost = (time.perf_counter() - begin) * 1000
                costs.append(cost)
                outputs.append(entries)
                f.write(
                    json.dumps(
                        {
                            "frame_id": r["frame_id"],
                            "endpoints": entries,
                            "compute_ms": cost,
                            "stages": serializable(diag),
                        }
                    )
                    + "\n"
                )
        result[mode] = {
            "overall": summarize(rows, outputs),
            "two_hand_compute_ms": quantiles(costs),
            "by_step": {
                str(s): summarize(
                    [r for r in rows if r["step"] == s],
                    [o for r, o in zip(rows, outputs, strict=True) if r["step"] == s],
                )
                for s in (1, 2, 3, 4)
            },
        }
    (args.output / "comparison.json").write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            {
                k: v.get("overall", v)
                for k, v in result.items()
                if k in ("support", "paired", "profile_single", "profile_temporal")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
