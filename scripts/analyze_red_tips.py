"""Offline red-tip analysis (app.play --red-tips). Never opens a camera, a microphone or a speaker.

    python scripts/analyze_red_tips.py frames <session-dir | image-dir | video-file | image> --output <dir>
        [--scale 0.6667] [--labels red-tip-labels.json] [--stick-tip-config configs/red-tip.tuned.yaml]
    python scripts/analyze_red_tips.py replay-fingertips <fingertip session dir> --output <dir>
    python scripts/analyze_red_tips.py synthetic --output <dir>
    python scripts/analyze_red_tips.py fit-verifier <session> [<session> ...] --output <dir> [--first-half]

``frames`` runs the detector and two-tip tracker over recorded images: a play ``--record-frames``
session, a folder of PNG/JPG frames or a video *file*. It reports continuity per hand, detection-loss
gaps, ambiguity, rejected blobs and per-frame compute on those real frames; measures the HSV of the
tracked tips and writes ``stick-tip.suggested.yaml`` (review it, then pass it to app.play with
``--stick-tip-config``); lists red objects that never moved as ``ignore_regions`` candidates; and writes a
contact sheet of annotated frames (camera orientation, not mirrored): a crosshair marks each blob's cap
point, a small grey dot the whole red region's centroid when it differs. A single image (e.g. a photo) is
repeated ``--repeat`` times so the tracker can confirm its tips; ``--scale`` resizes images and videos to
the tracking scale first (a 1280 x 720 native frame's 960 x 720 window is 2/3 of the tracking frame).

``frames --labels FILE`` measures **real-footage accuracy** against tip centres clicked by a person
(``scripts/tune_red_tips.py --label``): per labelled tip, whether a measured slot lies within
``--match-px`` of it, the pixel error of that slot's tip point (median / p95 / max), measured tips that
lie near no label, and identity swaps (which slot follows which labelled stick).

``replay-fingertips`` re-renders the *recorded* fingertip trajectories of a ``--fingers`` session as red
tips on SYNTHETIC images (recorded timestamps, gaps and an exposure-length blur), runs the red-tip
perception and the session's own decision pipeline, and compares the strikes with the fingertip
pipeline on the same motion. Only the perception layer differs: this measures agreement, identity
through real crossings and continuity, never real-world accuracy (the imagery is synthetic).

``synthetic`` is a known-truth self-test on SYNTHETIC swings with distractors and occlusions.

``fit-verifier`` refits the redness detector's cap verifier (stick/red_tip_caps.py) from labelled
sessions: every candidate within ``max(12, r / 2)`` px of a labelled cap is a cap, every candidate farther
than ``max(25, r + 5)`` px from all labelled caps and 25 px from all ``uncertain`` caps a non-cap (label
files marked ``"complete": false`` give caps only). It writes ``verifier.yaml``, a ``product: stick_tip:``
fragment for ``--stick-tip-config``. ``--first-half`` fits on the first half of each session's labelled
frames, so ``frames --labels ... --label-half second`` scores on frames the verifier never saw.

All output is developer evidence (``participant_evidence: false``).
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spacedrums.app.pipeline import DecisionPipeline  # noqa: E402
from spacedrums.app.red_tip_perception import RedTipPerception  # noqa: E402
from spacedrums.capture import ReplayFrameSource  # noqa: E402
from spacedrums.config import config_hash, deep_merge, load_yaml  # noqa: E402
from spacedrums.contracts import (  # noqa: E402
    FrameSample,
    FrameView,
    HandId,
    HandObservation,
    ImageRef,
    StickObservation,
    TimestampSource,
)
from spacedrums.contracts.perception import EndpointEvidence  # noqa: E402
from spacedrums.geometry import ZoneRegistry  # noqa: E402
from spacedrums.stick.red_tip import RedTipSettings  # noqa: E402
from spacedrums.stick.red_tip_caps import DEFAULT_VERIFIER, FEATURES, CapDetector, CapVerifier  # noqa: E402
from spacedrums.stick.red_tip_estimator import RedTipEndpointEstimator  # noqa: E402
from spacedrums.stick.red_tip_synthetic import background, draw_blob, draw_tip, speckles  # noqa: E402
from spacedrums.stick.red_tip_tracker import MEASURED_STATES  # noqa: E402

HANDS = (HandId.LEFT, HandId.RIGHT)
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp")
FRAGMENT = ROOT / "configs/red-tip.candidate.yaml"


def distribution(values):
    if not values:
        return None
    p50, p95, top = (round(float(v), 3) for v in np.percentile(values, [50, 95, 100]))
    return {"n": len(values), "p50": p50, "p95": p95, "max": top}


def tip_block(override: Path | None) -> dict:
    block = copy.deepcopy(load_yaml(FRAGMENT)["product"]["stick_tip"])
    if override is not None:
        block.update(load_yaml(override)["product"]["stick_tip"])
    return block


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------- frames


def count_frames(source: Path, limit: int | None, repeat: int = 1) -> int:
    if source.is_file() and source.suffix.lower() in IMAGE_SUFFIXES:
        n = max(1, repeat)
    elif source.is_dir() and (source / "frames.jsonl").exists():
        lines = (source / "frames.jsonl").read_text(encoding="utf-8").splitlines()
        n = sum(1 for line in lines if line.strip())
    elif source.is_dir():
        n = sum(1 for p in source.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    else:
        capture = cv2.VideoCapture(str(source))
        n = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        capture.release()
    return min(n, limit) if limit else n


def image_views(source: Path, fps: float, limit: int | None, *, scale: float = 1.0, repeat: int = 1):
    """FrameViews from a play/replay session, an image folder, a video file or one image (never a camera
    index). Images and videos are resized by ``scale``; a single image is yielded ``repeat`` times."""
    if source.is_dir() and (source / "frames.jsonl").exists():
        if scale != 1.0:
            raise SystemExit("--scale applies to images and videos; recorded sessions are at tracking scale")
        replay = ReplayFrameSource(source, limit=limit)
        for sample in replay:
            yield replay.view(sample)
        return
    if source.is_file() and source.suffix.lower() in IMAGE_SUFFIXES:
        still = cv2.imread(str(source))
        if still is None:
            raise SystemExit(f"cannot read image {source}")
        images = (still for _ in range(max(1, repeat)))
    elif source.is_dir():
        files = sorted(p for p in source.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
        images = (cv2.imread(str(p)) for p in files[:limit] if p.is_file())
    elif source.is_file():
        capture = cv2.VideoCapture(str(source))

        def frames():
            while limit is None or capture.get(cv2.CAP_PROP_POS_FRAMES) < limit:
                ok, img = capture.read()
                if not ok:
                    break
                yield img
            capture.release()

        images = frames()
    else:
        raise FileNotFoundError(source)
    for k, img in enumerate(i for i in images if i is not None):
        if scale != 1.0:
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]
        t = 100.0 + k / fps
        sample = FrameSample(frame_id=k, t_capture=t, t_frame_available=t,
                             timestamp_source=TimestampSource.REPLAY, frame_size_px=(w, h),
                             roi_px=(0, 0, w, h), image_ref=ImageRef.memory(img),
                             camera_profile_id="offline-analysis", dropped_since_last=0)
        yield FrameView(sample, img, img)


def annotate(view: FrameView, frame, labels=None) -> np.ndarray:
    """Camera-orientation diagnostics: grey = rejected (with reason), yellow crosshair = accepted blob's cap
    point (grey dot = whole-region centroid), filled / ring = measured / unmeasured slot, green = label."""
    img = view.roi.copy()
    for b in frame.rejected:
        p = tuple(map(round, b.center))
        cv2.circle(img, p, 7, (130, 130, 130), 1, cv2.LINE_AA)
        cv2.putText(img, str(b.reason), (p[0] + 8, p[1] + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.33,
                    (150, 150, 150), 1, cv2.LINE_AA)
    for b in frame.candidates:
        p = tuple(map(round, b.center))
        cv2.drawMarker(img, p, (0, 220, 255), cv2.MARKER_CROSS, 22, 1, cv2.LINE_AA)
        if b.region_center is not None and math.dist(b.region_center, b.center) > 2:
            cv2.circle(img, tuple(map(round, b.region_center)), 3, (160, 160, 160), -1, cv2.LINE_AA)
    for p in labels or ():
        if p is not None:
            cv2.circle(img, tuple(map(round, p)), 13, (60, 220, 60), 1, cv2.LINE_AA)
    for hand, st in frame.slots.items():
        color = (0, 190, 255) if hand is HandId.LEFT else (255, 145, 35)
        p = st.tip if st.tip is not None else st.predicted
        if p is None:
            continue
        cv2.circle(img, tuple(map(round, p)), 7, color, -1 if st.measured else 1, cv2.LINE_AA)
        cv2.putText(img, f"{str(hand)[0]}#{st.track_id} {st.state}", (round(p[0]) + 9, round(p[1]) - 9),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)
    mask = np.zeros_like(img)
    if frame.region is not None:
        mask[frame.region > 0] = (40, 40, 140)  # growth near seeds
    seeds = frame.mask  # seeds (paint core), or the redness detector's half-resolution candidate regions
    if seeds.shape[:2] != img.shape[:2]:
        seeds = cv2.resize(seeds, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
    mask[seeds > 0] = (60, 60, 255)
    inset = cv2.resize(mask, (img.shape[1] // 4, img.shape[0] // 4), interpolation=cv2.INTER_AREA)
    img[: inset.shape[0], -inset.shape[1]:] = inset
    cv2.putText(img, f"frame {view.sample.frame_id}  {frame.ms:.1f} ms  (camera view, not mirrored)",
                (8, img.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (240, 240, 240), 1, cv2.LINE_AA)
    return img


def hsv_samples(view: FrameView, frame, settings: RedTipSettings, out: dict) -> None:
    """Hue/saturation/value of red-band pixels around each measured tip (for threshold suggestions)."""
    hsv = cv2.cvtColor(view.roi, cv2.COLOR_BGR2HSV)
    for st in frame.slots.values():
        if not st.measured:
            continue
        r = int(math.sqrt((st.area or 0) / math.pi)) + 2
        x, y = map(round, st.tip)
        patch = hsv[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1].reshape(-1, 3).astype(int)
        hue = patch[:, 0]
        red = ((hue <= settings.hue_low_max + 8) | (hue >= settings.hue_high_min - 8)) & (patch[:, 1] >= 40) \
            & (patch[:, 2] >= 25)
        out["h"].extend(((hue[red] + 90) % 180 - 90).tolist())  # signed distance from hue 0
        out["s"].extend(patch[red, 1].tolist())
        out["v"].extend(patch[red, 2].tolist())


def suggest(settings: RedTipSettings, samples: dict) -> dict | None:
    """Conservative floors from the tracked tips' pixels; a starting point to review, not a calibration."""
    if len(samples["s"]) < 200:
        return None
    s10, v10 = np.percentile(samples["s"], 10), np.percentile(samples["v"], 10)
    h2, h98 = np.percentile(samples["h"], [2, 98])
    s_min = int(np.clip(s10 - 15, 60, 220))
    v_min = int(np.clip(v10 - 15, 30, 220))
    return {
        "hue_low_max": int(np.clip(max(h98, 0) + 2, 3, 20)),
        "hue_high_min": int(np.clip(180 + min(h2, 0) - 2, 160, 179)),
        "s_min": s_min,
        "v_min": v_min,
        "s_min_weak": max(35, min(settings.s_min_weak, s_min - 40)),
        "v_min_weak": max(20, min(settings.v_min_weak, v_min - 20)),
    }


def load_labels(path: Path) -> dict[int, list]:
    """``{frame_id: [stick A tip | None, stick B tip | None]}`` (tracking-frame pixels) from a labels file
    written by ``scripts/tune_red_tips.py --label``."""
    return load_label_doc(path)["labels"]


def load_label_doc(path: Path) -> dict:
    """Labels plus the optional ``absent`` frames (a stick certainly out of view: any measurement there is
    false) and ``uncertain`` points (visible but unlabelled caps, e.g. blurred: measurements near them are
    not scored). A label may carry a third value, the cap's radius in px (close-range caps): ``radius``."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    labels = {int(k): [None if p is None else (float(p[0]), float(p[1])) for p in v]
              for k, v in doc["labels"].items()}
    radius = {int(k): [float(p[2]) if p is not None and len(p) > 2 else None for p in v]
              for k, v in doc["labels"].items() if any(p is not None and len(p) > 2 for p in v)}
    absent = {int(k): list(v) for k, v in (doc.get("absent") or {}).items()}
    uncertain = {int(k): [(float(p[0]), float(p[1])) for p in v]
                 for k, v in (doc.get("uncertain") or {}).items()}
    return {"labels": labels, "absent": absent, "uncertain": uncertain, "radius": radius,
            "complete": bool(doc.get("complete", True))}


def label_half(doc: dict, half: str) -> dict:
    """``first`` / ``second`` half of the labelled frames by frame id (``absent`` frames follow the split)."""
    if half == "all":
        return doc
    fids = sorted(doc["labels"])
    cut = fids[len(fids) // 2] if fids else 0
    keep = (lambda f: f < cut) if half == "first" else (lambda f: f >= cut)
    parts = ("labels", "absent", "uncertain", "radius")
    return {**doc, **{k: {f: v for f, v in doc[k].items() if keep(f)} for k in parts}}


def score_labels(measured: dict[int, dict], labels: dict[int, list], match_px: float, *,
                 absent: dict[int, list] | None = None, uncertain: dict[int, list] | None = None,
                 uncertain_px: float = 25.0, radius: dict[int, list] | None = None) -> dict:
    """Detector output against labelled cap centres. ``measured``: each frame's measured slot tips or None.

    Each frame's labelled tips and measured tips are paired by minimum total distance among pairs closer
    than ``match_px`` (or half the cap's labelled ``radius`` when larger: a point on the middle of a
    close-range cap is on the cap). A measured tip on a scored frame (labelled or ``absent``) that matches no
    label and
    lies more than ``uncertain_px`` from every ``uncertain`` (visible, unlabelled) cap is a **false
    measurement**: on a hand, the shaft, cloth or the wall. Identity: each labelled stick should follow one
    slot; ``identity_disagreements`` count pairs off the stick's majority slot, ``identity_switches`` count
    changes of slot between consecutive matched observations of a stick."""
    from scipy.optimize import linear_sum_assignment

    absent, uncertain, radius = absent or {}, uncertain or {}, radius or {}
    errors, pairs, missed, stray, frames, total, false = [], [], 0, 0, 0, 0, 0
    per_stick = {0: {"labelled": 0, "errors": []}, 1: {"labelled": 0, "errors": []}}
    measured_scored = 0
    for fid in sorted(set(labels) | set(absent)):
        if fid not in measured:
            continue
        frames += 1
        points = labels.get(fid, [None, None])
        named = [(i, p) for i, p in enumerate(points) if p is not None]
        tips = [(h, p) for h, p in measured[fid].items() if p is not None]
        total += len(named)
        measured_scored += len(tips)
        for i, _ in named:
            per_stick[i]["labelled"] += 1
        matched_tips = set()
        if named and tips:
            cost = np.array([[math.dist(p, q) for _, q in tips] for _, p in named])
            sizes = radius.get(fid, [None, None])
            reach = np.array([[max(match_px, 0.5 * (sizes[i] or 0.0))] for i, _ in named])
            rows, cols = linear_sum_assignment(np.where(cost <= reach, cost, 1e6))
            for r, c in zip(rows, cols, strict=True):
                if cost[r, c] <= reach[r, 0]:
                    errors.append(float(cost[r, c]))
                    per_stick[named[r][0]]["errors"].append(float(cost[r, c]))
                    pairs.append((fid, named[r][0], tips[c][0]))
                    matched_tips.add(c)
        missed += len(named) - len(matched_tips)
        stray += len(tips) - len(matched_tips)
        for c, (_, q) in enumerate(tips):
            if c not in matched_tips and all(math.dist(q, u) > uncertain_px for u in uncertain.get(fid, ())):
                false += 1
    majority = {}
    for stick in {s for _, s, _ in pairs}:
        majority[stick] = Counter(h for _, s, h in pairs if s == stick).most_common(1)[0][0]
    switches = 0
    for stick in (0, 1):
        seq = [h for _, s, h in sorted(pairs) if s == stick]
        switches += sum(1 for x, y in zip(seq, seq[1:], strict=False) if x != y)
    names = "AB"
    return {
        "labelled_frames": frames, "labelled_tips": total, "matched_tips": len(errors),
        "detection_rate": len(errors) / total if total else None, "missed_tips": missed,
        "measured_tips_near_no_label": stray, "match_px": match_px,
        "error_px": distribution(errors),
        "per_stick": {names[i]: {"labelled": v["labelled"], "matched": len(v["errors"]),
                                 "coverage": len(v["errors"]) / v["labelled"] if v["labelled"] else None,
                                 "error_px": distribution(v["errors"])} for i, v in per_stick.items()},
        "false_measurements": false, "measured_on_scored_frames": measured_scored,
        "false_rate": false / measured_scored if measured_scored else None,
        "identity": {names[s]: h for s, h in sorted(majority.items())},
        "identity_disagreements": sum(1 for _, s, h in pairs if majority[s] != h),
        "identity_switches": switches,
    }


def cmd_frames(args) -> dict:
    block = tip_block(args.stick_tip_config)
    settings = RedTipSettings(**block)
    estimator = RedTipEndpointEstimator(settings)
    out = args.output
    label_doc = load_label_doc(args.labels) if args.labels else {"labels": {}, "absent": {}, "uncertain": {}}
    label_doc = label_half(label_doc, args.label_half) if args.labels else label_doc
    labels = label_doc["labels"]
    records, samples, sheet, tracks = [], {"h": [], "s": [], "v": []}, [], {}
    measured: dict[int, dict[str, tuple | None]] = {}
    every = max(1, count_frames(args.source, args.max_frames, args.repeat) // max(1, args.contact_sheet))
    size = None
    for k, view in enumerate(image_views(args.source, args.fps, args.max_frames, scale=args.scale,
                                         repeat=args.repeat)):
        size = view.sample.roi_px[2:]
        estimator.observe(view)
        frame = estimator.frame
        records.append({"frame_id": view.sample.frame_id, **frame.to_record()})
        measured[view.sample.frame_id] = {str(h): st.tip if st.measured else None
                                          for h, st in frame.slots.items()}
        hsv_samples(view, frame, settings, samples)
        for t in frame.tracker.tracks:
            if t["observed"]:
                info = tracks.setdefault(t["id"], {"frames": 0, "xs": [], "ys": []})
                info["frames"] += 1
                info["xs"].append(t["pos"][0])
                info["ys"].append(t["pos"][1])
        if args.contact_sheet and k % every == every - 1 and len(sheet) < args.contact_sheet:
            sheet.append(annotate(view, frame, labels.get(view.sample.frame_id)))
    if size is None:
        raise SystemExit(f"no frames in {args.source}")
    w, h = size
    still = []
    for tid, info in tracks.items():
        span = max(np.ptp(info["xs"]), np.ptp(info["ys"]))
        if info["frames"] >= 0.3 * len(records) and span < settings.move_px:
            x0, x1 = (min(info["xs"]) - 15) / w, (max(info["xs"]) + 15) / w
            y0, y1 = (min(info["ys"]) - 15) / h, (max(info["ys"]) + 15) / h
            still.append({"track_id": tid, "frames": info["frames"],
                          "ignore_region": [round(max(0.0, x0), 3), round(max(0.0, y0), 3),
                                            round(min(1.0, x1), 3), round(min(1.0, y1), 3)]})
    suggestion = suggest(settings, samples)
    with (out / "frames.jsonl").open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    if suggestion is not None:
        text = (f"# Suggested from {args.source} by scripts/analyze_red_tips.py. Review before use:\n"
                "# app.play --red-tips --stick-tip-config <this file>. A suggestion, not a calibration.\n")
        (out / "stick-tip.suggested.yaml").write_text(
            text + yaml.safe_dump({"product": {"stick_tip": suggestion}}, sort_keys=False), encoding="utf-8")
    if sheet:
        cols = min(3, len(sheet))
        rows = [np.hstack(sheet[i:i + cols] + [np.zeros_like(sheet[0])] * (cols - len(sheet[i:i + cols])))
                for i in range(0, len(sheet), cols)]
        cv2.imwrite(str(out / "contact-sheet.jpg"), np.vstack(rows))
    hsv = {k: distribution(v) for k, v in samples.items()}
    return {
        "mode": "frames", "source": str(args.source), "participant_evidence": False,
        "frames": len(records), "stick_tip": block, "red_tip": estimator.summary(),
        "frames_with_candidates": sum(bool(r["candidates"]) for r in records),
        "tip_hsv": hsv, "suggested": suggestion, "never_moved_red_objects": still,
        "scale": args.scale, "label_half": args.label_half if args.labels else None,
        "accuracy_vs_labels": score_labels(measured, labels, args.match_px, absent=label_doc["absent"],
                                           uncertain=label_doc["uncertain"],
                                           radius=label_doc.get("radius")) if labels else None,
    }


# ----------------------------------------------------------------------------- verifier fit


def session_labels(source: Path, name: str) -> Path:
    for candidate in (source / name, source / "red-tip-labels.json", source / "red-tip-labels.all.json"):
        if candidate.is_file():
            return candidate
    raise SystemExit(f"{source}: no labels ({name}, red-tip-labels.json or red-tip-labels.all.json)")


def verifier_examples(source: Path, doc: dict, detector: CapDetector, fps: float, scale: float) -> dict:
    """Candidate feature rows of the labelled frames with 1 = cap, 0 = not a cap (rules: module docstring)."""
    rows, ys = [], []
    for view in image_views(source, fps, None, scale=scale):
        fid = view.sample.frame_id
        if fid not in doc["labels"]:
            continue
        cands, _, _ = detector.candidates(view.roi)
        labs = doc["labels"][fid]
        radius = doc["radius"].get(fid, [None] * len(labs))
        caps = [(p, r or 0.0) for p, r in zip(labs, radius, strict=True) if p is not None]
        unsure = doc["uncertain"].get(fid, [])
        for c in cands:
            dist = [(math.dist(c.point, p), r) for p, r in caps]
            if any(d <= max(12.0, 0.5 * r) for d, r in dist):
                y = 1
            elif doc["complete"] and all(d > max(25.0, r + 5) for d, r in dist) and \
                    all(math.dist(c.point, u) > 25.0 for u in unsure):
                y = 0
            else:
                continue
            rows.append(list(c.features))
            ys.append(y)
    return {"rows": rows, "labels": ys}


def cmd_fit_verifier(args) -> dict:
    block = tip_block(args.stick_tip_config)
    detector = CapDetector(RedTipSettings(**block))
    features = args.features.split(",") if args.features else DEFAULT_VERIFIER["features"]
    rows, ys, per_source = [], [], {}
    for source in args.sessions:
        path = session_labels(source, args.labels_name)
        doc = label_half(load_label_doc(path), "first" if args.first_half else "all")
        ex = verifier_examples(source, doc, detector, args.fps, args.scale)
        rows += ex["rows"]
        ys += ex["labels"]
        per_source[str(source)] = {"labels": str(path), "caps": sum(ex["labels"]),
                                   "non_caps": len(ex["labels"]) - sum(ex["labels"])}
    verifier = CapVerifier.fit(np.array(rows), np.array(ys), features)
    q = verifier.score(np.array(rows))
    y = np.array(ys)
    fragment = {"product": {"stick_tip": {"verifier": verifier.as_dict()}}}
    text = ("# Cap verifier fitted with scripts/analyze_red_tips.py fit-verifier on "
            + ", ".join(str(s) for s in args.sessions)
            + (" (first half of the labels)" if args.first_half else "")
            + ".\n# Developer candidate, not a calibration. Play with:\n"
            "#   .\\play-spacedrums.ps1 --demo --red-tips --stick-tip-config <this file>\n")
    path = args.output / "verifier.yaml"
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text + yaml.safe_dump(fragment, sort_keys=False))
    RedTipSettings(**{**block, "verifier": verifier.as_dict()})
    return {
        "mode": "fit-verifier", "participant_evidence": False, "sessions": per_source,
        "first_half": args.first_half, "features": list(features), "all_features": list(FEATURES),
        "verifier": verifier.as_dict(), "fragment": str(path),
        "training_fit": {"caps_at_0.5": float((q[y == 1] >= 0.5).mean()) if (y == 1).any() else None,
                         "non_caps_at_0.5": float((q[y == 0] >= 0.5).mean()) if (y == 0).any() else None},
    }


# ----------------------------------------------------------------------------- pipeline helpers


def pipeline_for(cfg: dict, session: str) -> DecisionPipeline:
    return DecisionPipeline(
        cfg, registry=ZoneRegistry.from_config(cfg["zones"]), session_id=session, active_arm="A",
        hardware_id="offline-analysis", config_hash=config_hash(cfg), audio=None, gain_fn=lambda z, v: 1.0,
        developer_demo=bool(cfg["product"].get("developer_demo")),
    )


def commit_row(c) -> dict:
    return {"frame_id": c.frame_id, "hand": str(c.hand_id), "zone": c.zone_id, "t": c.t_impact_target}


def run_red(cfg: dict, views, session: str):
    """Red-tip perception + the shared decision pipeline over streamed FrameViews.

    Returns the commits, a compact per-frame slot log ``{frame_id: {hand: (state, tip_px, track_id),
    "resets": [hands]}}``, the per-frame red-tip compute (ms) and the estimator summary. Images and masks
    are not retained.
    """
    perception = RedTipPerception(cfg)
    pipeline = pipeline_for(cfg, session)
    commits, slots, ms = [], {}, []
    for view in views:
        obs = perception(view)
        frame = perception.estimator.frame
        for hand in frame.resets:
            pipeline.reset_hand(hand)
        result = pipeline.step(view.sample, obs, t_now=view.sample.t_frame_available,
                               endpoint_evidence=perception.estimator.evidence)
        commits.extend(commit_row(c) for c in result.commits)
        slots[frame.frame_id] = {h: (st.state, st.tip, st.track_id) for h, st in frame.slots.items()}
        slots[frame.frame_id]["resets"] = sorted(str(h) for h in frame.resets)
        ms.append(frame.ms)
    return commits, slots, ms, perception.estimator.summary()


def run_ideal(cfg: dict, seq, session: str) -> list[dict]:
    """The same pipeline fed the SYNTHETIC tips themselves (perfect measurements, labelled MARKER)."""
    pipeline = pipeline_for(cfg, session)
    commits = []
    for sample, obs in seq.frames:
        sample = replace(sample, roi_px=(0, 0) + tuple(sample.frame_size_px))
        sticks, evidence = {}, {}
        for h, (hand, st) in obs.items():
            fid, t = sample.frame_id, sample.t_capture
            if st.present:
                tip = st.tip
                stick = StickObservation(fid, t, h, True, "MARKER", tip, (0.0, -1.0), tip, 0.9, 0.0, None)
                evidence[h] = EndpointEvidence(fid, t, h, "MEASURED", "IDEAL", stick.tip, stick.tip, 0.9, 1.0)
            else:
                stick = StickObservation.absent(fid, t, h, "MARKER")
                evidence[h] = EndpointEvidence(fid, t, h, "MISSING", "IDEAL")
            sticks[h] = (hand, stick)
        result = pipeline.step(sample, sticks, t_now=sample.t_frame_available, endpoint_evidence=evidence)
        commits.extend(commit_row(c) for c in result.commits)
    return commits


def match(reference: list[dict], other: list[dict], *, tolerance: int = 2) -> tuple[list, list, list]:
    """Greedy one-to-one match on zone and frame distance (hand labels are compared separately)."""
    unused = list(other)
    pairs, missing = [], []
    for ref in reference:
        near = [o for o in unused
                if o["zone"] == ref["zone"] and abs(o["frame_id"] - ref["frame_id"]) <= tolerance]
        if near:
            best = min(near, key=lambda o: abs(o["frame_id"] - ref["frame_id"]))
            unused.remove(best)
            pairs.append((ref, best))
        else:
            missing.append(ref)
    return pairs, missing, unused


def strike_details(red: list[dict], reference: list[dict], missing: list[dict], extra: list[dict],
                   slot_log: dict, before: int = 8) -> dict:
    """Every strike of both pipelines, and each extra / missed one with the nearest strike of the other
    pipeline and the slot states, track ids and identity resets of the frames leading up to it."""
    def context(fid):
        frames = [k for k in range(fid - before, fid + 1) if k in slot_log]
        return {str(k): {**{str(h): list(slot_log[k][h][::2]) for h in HANDS},
                         "resets": slot_log[k]["resets"]} for k in frames}

    def nearest(event, pool):
        return min(pool, key=lambda o: abs(o["frame_id"] - event["frame_id"]), default=None)

    return {"red_tip": red, "reference": reference,
            "extra": [{**e, "nearest_reference": nearest(e, reference), "context": context(e["frame_id"])}
                      for e in extra],
            "missing": [{**m, "nearest_red_tip": nearest(m, red), "context": context(m["frame_id"])}
                        for m in missing]}


# ----------------------------------------------------------------------------- replay-fingertips


def cmd_replay(args) -> dict:
    session = args.session
    report = json.loads((session / "report.json").read_text(encoding="utf-8"))
    lines = (session / "observations.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    if args.max_frames:
        rows = rows[: args.max_frames]
    reasons = Counter(e["reason"] for r in rows for e in r["endpoints"])
    if not reasons.get("FINGERTIP"):
        raise SystemExit(f"{session} is not a --fingers session (endpoint reasons {dict(reasons)})")
    cfg = deep_merge(report["config"], {"product": {"stick_tip": tip_block(args.stick_tip_config)}})
    bg = cv2.imread(str(args.background)) if args.background else None
    rng = np.random.default_rng(args.seed)
    fingers_tips: dict[int, dict] = {}

    def rendered():
        previous = {}
        for r in rows:
            sample = FrameSample.from_dict(r["frame"])
            w, h = sample.frame_size_px
            x0, y0, rw, rh = sample.roi_px
            img = cv2.resize(bg, (w, h)) if bg is not None else background((w, h), rng=rng)
            tips = {}
            for e in r["endpoints"]:
                hand = HandId(e["hand_id"])
                if e["kind"] != "MEASURED":
                    previous.pop(hand, None)
                    continue
                p = np.array([x0 + e["tip"][0] * rw, y0 + e["tip"][1] * rh])
                prev = previous.get(hand)
                if prev is None:
                    draw_tip(img, tuple(p))
                else:
                    path = (prev - p) * args.exposure_fraction
                    # end: the recorded tip is where the exposure ends (the streak trails it, worst-case lag);
                    # center: the recorded tip is the exposure's middle (a landmark of a blurred hand).
                    shift = path / 2 if args.blur_anchor == "center" else 0.0
                    draw_tip(img, tuple(p - shift), blur_from=tuple(p + path - shift))
                previous[hand] = p
                tips[hand] = tuple(p - (x0, y0))
            fingers_tips[sample.frame_id] = tips
            yield FrameView(replace(sample, image_ref=ImageRef.memory(img)), img[y0:y0 + rh, x0:x0 + rw], img)

    name = f"replay-{report.get('session_id', 'session')}"
    red_commits, slot_log, ms, summary = run_red(cfg, rendered(), name)

    # The fingertip pipeline on the recorded evidence, with the same replay clock as the red-tip run.
    finger_pipeline = pipeline_for(copy.deepcopy(report["config"]), "replay-fingertip")
    finger_commits = []
    for r in rows:
        sample = FrameSample.from_dict(r["frame"])
        hands = {HandId(d["hand_id"]): HandObservation.from_dict(d) for d in r["hands"]}
        sticks = {HandId(d["hand_id"]): StickObservation.from_dict(d) for d in r["sticks"]}
        evidence = {}
        for d in r["endpoints"]:
            fields = {k: v for k, v in d.items() if k != "schema_version"}
            for key in ("tip", "origin"):  # JSON lists back to the tuples the pipeline compares with
                fields[key] = None if fields[key] is None else tuple(fields[key])
            evidence[HandId(d["hand_id"])] = EndpointEvidence(**fields)
        result = finger_pipeline.step(sample, {h: (hands[h], sticks[h]) for h in HANDS},
                                      t_now=sample.t_frame_available, endpoint_evidence=evidence)
        finger_commits.extend(commit_row(c) for c in result.commits)
    recorded = [{"frame_id": c["frame_id"], "hand": c["hand_id"], "zone": c["zone_id"],
                 "t": c["t_impact_target"]} for r in rows for c in r["commits"]]

    pairs, missing, extra = match(finger_commits, red_commits)
    measured = MEASURED_STATES
    causes = Counter()
    for ref in missing:
        states = [slot_log[k][h][0] for k in range(ref["frame_id"] - 3, ref["frame_id"] + 1)
                  if k in slot_log for h in HANDS]
        bad = [s for s in states if s not in measured]
        causes[Counter(bad).most_common(1)[0][0] if bad else "MEASURED_BUT_NOT_STRUCK"] += 1
    same, swapped, both = 0, 0, 0
    flips, previous = [], None
    for frame_id, tips in sorted(fingers_tips.items()):
        slots = slot_log[frame_id]
        if len(tips) == 2 and all(slots[h][0] in measured for h in HANDS):
            both += 1
            red = {h: slots[h][1] for h in HANDS}
            d_same = sum(math.dist(red[h], tips[h]) for h in HANDS)
            left, right = HandId.LEFT, HandId.RIGHT
            d_swap = math.dist(red[left], tips[right]) + math.dist(red[right], tips[left])
            same += d_same <= d_swap
            swapped += d_swap < d_same
            label = d_swap < d_same
            if previous is not None and label != previous:  # the slots' hand assignment changed
                flips.append(frame_id)
            previous = label
    details = strike_details(red_commits, finger_commits, missing, extra, slot_log)
    write_json(args.output / "strikes.json", details)
    measured_red = {str(h): sum(s[h][0] in measured for s in slot_log.values()) for h in HANDS}
    measured_fingers = {str(h): sum(h in t for t in fingers_tips.values()) for h in HANDS}
    hands_agree = sum(a["hand"] == b["hand"] for a, b in pairs)
    return {
        "mode": "replay-fingertips", "session": str(session), "participant_evidence": False,
        "imagery": "SYNTHETIC red tips rendered on recorded fingertip trajectories",
        "background": str(args.background) if args.background else "synthetic grey + noise",
        "exposure_fraction": args.exposure_fraction, "blur_anchor": args.blur_anchor, "frames": len(rows),
        "commits": {"recorded_live": len(recorded), "fingertip_replay": len(finger_commits),
                    "red_tip_replay": len(red_commits)},
        "recorded_vs_fingertip_replay": {"matched": len(match(recorded, finger_commits)[0])},
        "red_vs_fingertip": {"matched": len(pairs), "missed": len(missing), "extra": len(extra),
                             "matched_same_hand_label": hands_agree,
                             "frame_offset": dict(Counter(b["frame_id"] - a["frame_id"] for a, b in pairs)),
                             "missed_causes": dict(causes),
                             "extra_zones": dict(Counter(e["zone"] for e in extra))},
        "identity": {"frames_with_both_measured": both, "same_as_fingertip_labels": same,
                     "swapped_vs_fingertip_labels": swapped, "flips": len(flips), "flip_frames": flips},
        "measured_frames": {"fingertip": measured_fingers, "red_tip": measured_red},
        "red_tip_ms": distribution(ms), "red_tip": summary,
    }


# ----------------------------------------------------------------------------- synthetic


def cmd_synthetic(args) -> dict:
    from spacedrums.app import play
    from spacedrums.app.synthetic import Swing, build_sequence
    from spacedrums.stick.red_tip_synthetic import REAL_CAP, tip_frames

    report = {"mode": "synthetic", "participant_evidence": False, "imagery": "SYNTHETIC", "cases": {},
              "tip_size": "small (16 x 12 px)" if args.small_tips else "owner-photo caps (34 x 26 px)"}
    left, right = HandId.LEFT, HandId.RIGHT
    roll = [Swing(right if i % 2 else left, "snare", 0.3 + 0.16 * i, t_down=0.12,
                  x_offset=0.035 if i % 2 else -0.035) for i in range(10)]
    strikes = [Swing(right, "snare", 0.3 + 0.5 * i) for i in range(4)]
    strikes += [Swing(left, z, 2.4 + 0.6 * i) for i, z in enumerate(("hihat", "crash_ride"))]
    cases = {
        "four-pad strikes": ("four", strikes),
        "alternating roll": ("four", roll),
        "simultaneous": ("four", [Swing(left, "hihat", 0.4), Swing(right, "snare", 0.4)]),
        "non-strikes": ("four", [Swing(right, "snare", 0.3, kind="hover"),
                                 Swing(left, "hihat", 0.9, kind="stop_short"),
                                 Swing(right, "tom1", 1.5, kind="lateral")]),
        "full kit": ("full", [Swing(right, z, 0.3 + 0.6 * i)
                              for i, z in enumerate(("snare", "tom1", "ride"))]),
    }

    def clutter(img, k):
        draw_blob(img, (590, 40), 9, hue=178, sat=220, val=190)  # a red object that never moves
        draw_blob(img, (60, 420), 22, hue=12, sat=95, val=170)  # skin tone
        speckles(img, np.random.default_rng(k), 40)

    unknown = set(args.case or ()) - set(cases)
    if unknown:
        raise SystemExit(f"unknown case(s) {sorted(unknown)}; choose from {sorted(cases)}")
    for name, (kit, swings) in cases.items():
        if args.case and name not in args.case:
            continue
        cfg = play.play_config(demo=True, kit=kit, red_tips=True, stick_tip=args.stick_tip_config)
        registry = ZoneRegistry.from_config(cfg["zones"])
        duration = max(s.t_up_end for s in swings) + 0.4
        seq = build_sequence(registry, swings, duration_s=duration)
        tip_kw = None if args.small_tips else dict(REAL_CAP)  # REAL_CAP: the owner photo's caps
        views = (v for v, _ in tip_frames(seq, decorate=clutter, seed=args.seed, tip_kw=tip_kw))
        commits, _, ms, summary = run_red(cfg, views, f"synthetic-{name}")
        ideal = run_ideal(cfg, seq, f"synthetic-ideal-{name}")
        truth = [{"frame_id": int(round((e.t_cross - 100.0) * 30)), "zone": e.zone_id, "hand": str(e.hand)}
                 for e in seq.truth if e.kind == "strike"]
        pairs, missing, extra = match(truth, commits, tolerance=2)
        same, lost, added = match(ideal, commits, tolerance=1)
        report["cases"][name] = {
            "truth": len(truth), "detected": len(pairs), "missed": len(missing), "false": len(extra),
            "zones_of_false": dict(Counter(e["zone"] for e in extra)),
            # Perfect measurements through the same pipeline: what perception alone changes.
            "ideal_tip_commits": len(ideal), "matches_ideal": len(same), "missing_vs_ideal": len(lost),
            "extra_vs_ideal": len(added), "red_tip_ms": distribution(ms), "events": summary["events"],
        }
    report["note"] = ("A 'false' commit that the ideal-tip pipeline also makes comes from the synthetic "
                      "motion path crossing a pad edge between swings, not from red-tip perception. "
                      "Synthetic hands place LEFT on the image's left (the real camera shows it on the "
                      "right), so hand labels are not compared here.")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    f = sub.add_parser("frames", help="detector + tracker over recorded frames")
    f.add_argument("source", type=Path)
    f.add_argument("--fps", type=float, default=30.0, help="timestamps for image folders / videos")
    f.add_argument("--max-frames", type=int)
    f.add_argument("--contact-sheet", type=int, default=9,
                   help="annotated frames in contact-sheet.jpg (0 = none)")
    f.add_argument("--scale", type=float, default=1.0,
                   help="resize images/videos first (0.6667: a native 960x720 window to the tracking scale)")
    f.add_argument("--repeat", type=int, default=3, help="frames made from a single image (tracker birth)")
    f.add_argument("--labels", type=Path, help="tip centres clicked with scripts/tune_red_tips.py --label")
    f.add_argument("--match-px", type=float, default=12.0,
                   help="a measured tip within this distance of a labelled tip counts as found")
    f.add_argument("--label-half", choices=("all", "first", "second"), default="all",
                   help="score only this half of the labelled frames (second: frames fit-verifier "
                        "--first-half never saw)")
    r = sub.add_parser("replay-fingertips", help="red tips rendered on a fingertip session's trajectories")
    r.add_argument("session", type=Path)
    r.add_argument("--exposure-fraction", type=float, default=0.9,
                   help="blurred share of the inter-frame motion (exposure -5 at 30 FPS is about 0.9)")
    r.add_argument("--blur-anchor", choices=("end", "center"), default="end",
                   help="end: the streak trails the recorded tip (worst-case lag); center: centred on it")
    r.add_argument("--background", type=Path, help="a camera frame to render on (default: synthetic grey)")
    r.add_argument("--max-frames", type=int)
    r.add_argument("--seed", type=int, default=0)
    s = sub.add_parser("synthetic", help="known-truth SYNTHETIC self-test")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--case", action="append", help="run only this case (repeatable); default: all")
    s.add_argument("--small-tips", action="store_true",
                   help="render the first version's 16 x 12 px tips instead of the photo-sized caps")
    v = sub.add_parser("fit-verifier", help="refit the redness detector's cap verifier from labels")
    v.add_argument("sessions", type=Path, nargs="+")
    v.add_argument("--labels-name", default="red-tip-labels.json", help="label file inside each session")
    v.add_argument("--first-half", action="store_true", help="fit on the first half of each session's labels")
    v.add_argument("--features", help="comma-separated feature names (default: the built-in verifier's)")
    v.add_argument("--fps", type=float, default=30.0)
    v.add_argument("--scale", type=float, default=1.0)
    for p in (f, r, s, v):
        p.add_argument("--output", type=Path, required=True)
        p.add_argument("--stick-tip-config", type=Path, help="'product: stick_tip:' override fragment")
    args = ap.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    cv2.setNumThreads(1)
    commands = {"frames": cmd_frames, "replay-fingertips": cmd_replay, "synthetic": cmd_synthetic,
                "fit-verifier": cmd_fit_verifier}
    result = commands[args.command](args)
    write_json(args.output / "summary.json", result)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
