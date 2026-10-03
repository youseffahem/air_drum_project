"""Score explicit developer annotations and render evidence, not dataset ground truth."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from review_developer_endpoints import load_capture, quantiles


def point(p):
    return tuple(np.rint(p).astype(int))


def score(labels, prediction, rows, tolerance):
    lookup = {(r["frame_id"], e["hand_id"]): e for r in prediction for e in r["endpoints"]}
    result = []
    for a in labels:
        if not a["scorable"]:
            continue
        e = lookup[(a["frame_id"], a["hand_id"])]
        entry = {**a, "kind": e["kind"], "reason": e["reason"], "predicted_px": None, "error_px": None}
        if e["kind"] == "MEASURED":
            pred = np.array(e["tip"]) * [640, 480]
            error = float(np.linalg.norm(pred - a["tip_px"]))
            entry.update(
                predicted_px=pred.tolist(),
                error_px=error,
                classification="correct" if error <= tolerance else "incorrect",
                uncertainty_classification="clearly_correct"
                if error + a["uncertainty_px"] <= tolerance
                else "clearly_incorrect"
                if error - a["uncertainty_px"] > tolerance
                else "borderline",
            )
        else:
            entry["classification"] = "abstained"
        result.append(entry)
    errors = [a["error_px"] for a in result if a["error_px"] is not None]
    accepted = len(errors)
    correct = sum(a["classification"] == "correct" for a in result)
    return {
        "scorable": len(result),
        "accepted": accepted,
        "correct": correct,
        "incorrect": accepted - correct,
        "abstained": len(result) - accepted,
        "point_precision": correct / accepted if accepted else None,
        "correct_coverage": correct / len(result) if result else None,
        "error_px": quantiles(errors),
        "uncertainty_classes": dict(
            Counter(a.get("uncertainty_classification") for a in result if a["error_px"] is not None)
        ),
        "examples": result,
    }


def render(im, row, pred, name, annotations, diag=None):
    im = im.copy()
    for hand in row["hands"]:
        if hand["present"]:
            lm = np.array(hand["landmarks"]) * [640, 480]
            for p in lm:
                cv2.circle(im, point(p), 1, (255, 190, 40), -1)
            cv2.putText(im, hand["hand_id"], point(lm[0] + [7, 0]), 0, 0.45, (255, 190, 40), 1)
    if diag:
        for d in diag.values():
            if "candidates" not in d:
                if d.get("polygon"):
                    cv2.polylines(im, [np.rint(d["polygon"]).astype(np.int32)], True, (160, 80, 160), 1)
                pixels = np.array(d.get("support_pixels", []), int).reshape(-1, 2)
                if len(pixels):
                    im[pixels[:, 1], pixels[:, 0]] = (230, 150, 0)
                a = d.get("axis")
                if a:
                    cv2.line(im, point(a["origin_px"]), point(a["support_far_px"]), (255, 120, 60), 1)
                    cv2.drawMarker(
                        im, point(a["support_far_px"]), (0, 0, 255), cv2.MARKER_TILTED_CROSS, 10, 1
                    )
                continue
            if d.get("grip"):
                cv2.drawMarker(im, point(d["grip"]), (255, 220, 60), cv2.MARKER_CROSS, 10, 2)
            for c in d["candidates"]:
                if c.get("candidate") is not None and not c["valid"]:
                    cv2.drawMarker(im, point(c["candidate"]), (0, 0, 255), cv2.MARKER_TILTED_CROSS, 8, 1)
            c = d.get("selected")
            if not c and d["candidates"]:
                rejected = d["candidates"][0]
                p = rejected["proposal"]
                strength = np.asarray(rejected.get("strength", []))
                if len(strength):
                    origin = np.asarray(p["origin"])
                    direction = np.asarray(p["direction"])
                    support = origin + np.flatnonzero(strength >= 12)[:, None] * direction
                    for s in support[::2]:
                        cv2.circle(im, point(s), 1, (255, 255, 0), -1)
                if rejected.get("candidate") is not None:
                    cv2.line(im, point(p["origin"]), point(rejected["candidate"]), (255, 100, 30), 1)
                    cv2.drawMarker(
                        im, point(rejected["candidate"]), (0, 0, 255), cv2.MARKER_TILTED_CROSS, 10, 2
                    )
            if c:
                p = c["proposal"]
                cv2.line(im, point(p["origin"]), point(c["tip"]), (255, 100, 30), 1)
                for edge in p["edges"]:
                    cv2.line(im, point(edge[:2]), point(edge[2:]), (180, 90, 180), 1)
                for s in c["support"][::2]:
                    cv2.circle(im, point(s), 1, (255, 255, 0), -1)
                cv2.circle(im, point(c["candidate"]), 8, (0, 210, 255), 1)
            if d.get("prior_tip"):
                cv2.drawMarker(im, point(d["prior_tip"]), (180, 180, 180), cv2.MARKER_DIAMOND, 8, 1)
    for e in pred:
        if e["kind"] == "MEASURED":
            cv2.circle(im, point(np.array(e["tip"]) * [640, 480]), 4, (30, 245, 30), -1)
    for a in annotations:
        if a["frame_id"] == row["frame_id"]:
            cv2.circle(im, point(a["tip_px"]), 10, (255, 255, 255), 1)
            cv2.drawMarker(im, point(a["tip_px"]), (255, 255, 255), cv2.MARKER_CROSS, 12, 1)
    footer = np.zeros((106, 640, 3), np.uint8)
    texts = [f"{name} | frame {row['frame_id']} | {row['elapsed_s']:.3f}s"]
    texts += [f"{e['hand_id']}: {e['kind']} / {e['reason']}" for e in pred]
    texts += [
        "White: manual  Yellow ring: candidate  Green: accepted",
        "Cyan: sampled support  Blue: axis  Red X: rejected  Gray: prior only",
    ]
    for i, line in enumerate(texts):
        cv2.putText(footer, line, (5, 18 + 20 * i), 0, 0.39, (240, 240, 240), 1)
    return np.vstack([im, footer])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=Path("experiments/developer-endpoint-check-20261004-01"))
    p.add_argument("--output", type=Path, default=Path("experiments/developer-endpoint-offline-20261004-01"))
    p.add_argument(
        "--tolerance-px",
        type=float,
        default=10,
        help="Developer comparison tolerance chosen after inspecting cap size/annotation uncertainty.",
    )
    args = p.parse_args()
    report, rows, images = load_capture(args.source)
    labels = json.loads((args.output / "manual-labels.json").read_text())["labels"]
    methods = {"live_baseline": rows}
    for mode in ("support", "paired", "profile_single", "profile_temporal"):
        methods[mode] = [json.loads(s) for s in (args.output / f"{mode}.jsonl").read_text().splitlines()]
    metrics = {name: score(labels, pred, rows, args.tolerance_px) for name, pred in methods.items()}
    result = {
        "status": "developer diagnostic subset, visually reviewed by Codex; not independent ground truth",
        "tolerance_px": args.tolerance_px,
        "methods": metrics,
    }
    byframe = {r["frame_id"]: i for i, r in enumerate(rows)}
    diag_counts = Counter()
    details = []
    for a in labels:
        if not a["scorable"]:
            continue
        r = rows[byframe[a["frame_id"]]]
        stage = r["stages"][a["hand_id"]]
        if not stage or not stage["search_polygon_px"]:
            continue
        poly = np.asarray(stage["search_polygon_px"], np.float32)
        margin = cv2.pointPolygonTest(poly, tuple(map(float, a["tip_px"])), True)
        g = np.array(stage["grip_px"])
        d = np.array(a["tip_px"]) - g
        d /= np.linalg.norm(d)
        prior = np.array(stage["prior_direction_px"])
        ang = float(np.arccos(np.clip(np.dot(prior, d), -1, 1)))
        info = {
            "frame_id": a["frame_id"],
            "hand_id": a["hand_id"],
            "tip_search_margin_px": margin,
            "prior_to_physical_axis_deg": float(np.degrees(ang)),
            "logged_reason": next(e["reason"] for e in r["endpoints"] if e["hand_id"] == a["hand_id"]),
        }
        details.append(info)
        diag_counts["reviewed_scorable_with_search"] += 1
        diag_counts["tip_outside_search"] += margin < 0
        diag_counts["prior_axis_difference_over_0.7rad"] += min(ang, np.pi - ang) > 0.7
    result["reviewed_search_geometry"] = {"counts": dict(diag_counts), "details": details}
    (args.output / "accuracy.json").write_text(json.dumps(result, indent=2))
    for fid in sorted({a["frame_id"] for a in labels}):
        i = byframe[fid]
        baseline = render(images[i], rows[i], rows[i]["endpoints"], "RECORDED LIVE", labels)
        support = render(
            images[i],
            rows[i],
            methods["support"][i]["endpoints"],
            "JPEG BASELINE SUPPORT",
            labels,
            methods["support"][i]["stages"],
        )
        candidate = render(
            images[i],
            rows[i],
            methods["profile_temporal"][i]["endpoints"],
            "EXPERIMENTAL PROFILE + PRIOR",
            labels,
            methods["profile_temporal"][i]["stages"],
        )
        cv2.imwrite(
            str(args.output / f"comparison-frame-{fid}.jpg"), np.hstack([baseline, support, candidate])
        )
    frame_ids = sorted({a["frame_id"] for a in labels})
    # Local report viewer; no server, CDN, camera, or audio access.
    page = """<!doctype html><html lang="en"><meta charset="utf-8"><title>Endpoint investigation</title>
<style>body{background:#141a24;color:#ecf2fa;font:16px system-ui;margin:28px}h1{font-size:26px}
select,button{font:inherit;padding:8px;margin:8px;background:#25344a;color:white;border:1px solid #6280a4}
img{width:100%;height:auto}a{color:#8cd9ff}.note{max-width:1000px;line-height:1.5}</style>
<h1>Offline stick endpoint investigation · 608 saved frames</h1>
<p class="note">Experimental prototype. Production tracker unchanged.
The diagnostic set is manually reviewed by Codex, not independent human ground truth.
White crosses mark reviewed tips; green marks acceptance, not guaranteed correctness.</p>
<p><a href="accuracy.json">Pixel errors and annotations</a> · <a href="comparison.json">Continuity</a> ·
<a href="benchmark.json">CPU benchmark</a> · <a href="manual-labels.json">Labels and uncertainty</a></p>
<p>Left: recorded live baseline · Middle: baseline replay support/search ·
Right: current candidate diagnostics</p>
<button id="prev">Previous</button><select id="frame"></select><button id="next">Next</button>
<img id="comparison" alt="Endpoint evidence comparison">
<p class="note">Blue: axis. Cyan: candidate shaft samples (baseline panel: retained component pixels).
Purple: baseline search region or proposed edge pair. Yellow ring: current candidate. Red X: rejection.
Gray diamond: prior only. Rejection reasons appear below each panel.</p>
<script>const ids=FRAME_IDS;let i=0;const select=document.querySelector('#frame');
ids.forEach(id=>{const o=document.createElement('option');o.value=id;
o.textContent='Frame '+id;select.append(o)});
function show(){select.selectedIndex=i;
document.querySelector('#comparison').src='comparison-frame-'+ids[i]+'.jpg'}
select.onchange=()=>{i=select.selectedIndex;show()};document.querySelector('#prev').onclick=()=>{i=(i+ids.length-1)%ids.length;show()};
document.querySelector('#next').onclick=()=>{i=(i+1)%ids.length;show()};show();</script></html>"""
    (args.output / "review.html").write_text(
        page.replace("FRAME_IDS", json.dumps(frame_ids)), encoding="utf-8"
    )
    print(
        json.dumps({n: {k: v for k, v in m.items() if k != "examples"} for n, m in metrics.items()}, indent=2)
    )
    print(json.dumps(result["reviewed_search_geometry"]["counts"]))


if __name__ == "__main__":
    main()
