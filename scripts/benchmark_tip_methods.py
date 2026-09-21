"""Phase 03, Tasks 03.10 / 03.11 / 03.13 / 03.15: tip-method benchmark on developer captures.

Runs, on the same replayed frames (recorded ``t_capture``, ``REPLAY``): hands (Tasks 03.1-03.3)
-> all three ``TipEstimator``s (GEOM, AXIS_REFINED, MARKER) -> one ``CausalTracker`` per hand per
method, and writes an experiment log with:

* per method: present / low-confidence / no-axis / fallback counts and rates, ``tip_confidence``
  and ``axis_confidence`` distributions, per-frame estimator compute time (p50 / p95), inter-method
  agreement (AXIS_REFINED vs GEOM tip distance in px, where both present);
* **tip error vs reference** (median, p90 in px and ROI-normalized units) stratified by speed
  tercile and capture condition — ONLY when an annotation file produced by ``tools/annotate_tip.py``
  exists under ``data/dev-annotations/<capture>/tips.jsonl``; otherwise the error rows are written
  as ``PENDING`` (no reference is ever invented). Synthetic annotation files (``tips.SYNTHETIC.jsonl``)
  are refused unless ``--allow-synthetic-reference`` (self-test only; labelled in the run);
* tracker per method per hand: status histogram, reset events (kind, frame), a compact state trace
  string, TEST-CONFORM-2 checks (schema validity of every ``TrackState``, one per frame per hand);
* Task 03.11 rows for the single-frame distance captures (``--distance``): landmark presence,
  landmark-based hand span (px), axis confidence and support length per hand per distance;
* overlay screenshots (Task 03.15) for sampled frames.

Usage:
    python scripts/benchmark_tip_methods.py --capture swing-L2-exp-5 --capture swing-L2-exp-6
    python scripts/benchmark_tip_methods.py --distance            # d080/d100/d150/d220 single frames
    python scripts/benchmark_tip_methods.py --synthetic           # self-test (stub hands, drawn stick)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _devcapture import DEV_CAPTURES, iter_views, load_dev_capture  # noqa: E402
from _runlog import ROOT, RunLog  # noqa: E402
from hands_landmark_check import StubBackend, _iter_synthetic  # noqa: E402

from spacedrums import timing  # noqa: E402
from spacedrums.capture import Roi, crop_roi, norm_to_px_point  # noqa: E402
from spacedrums.config import load_config  # noqa: E402
from spacedrums.contracts import (  # noqa: E402
    FrameSample,
    FrameView,
    HandId,
    ImageRef,
    ResetReason,
    TimestampSource,
    TipMethod,
)
from spacedrums.contracts import schema as contract_schema  # noqa: E402
from spacedrums.hands import HandLandmarker, HandLandmarkerSettings  # noqa: E402
from spacedrums.stick import StickSettings, make_tip_estimator  # noqa: E402
from spacedrums.tracking import CausalTracker, TrackerSettings  # noqa: E402
from spacedrums.ui import draw_debug_overlay  # noqa: E402

DEFAULT_BASE = ROOT / "configs" / "example.candidate.yaml"
DEFAULT_CAMERA = ROOT / "configs" / "camera" / "hw01-integrated-webcam.candidate.yaml"
ANNOTATIONS = ROOT / "data" / "dev-annotations"
METHODS = [TipMethod.GEOM, TipMethod.AXIS_REFINED, TipMethod.MARKER]
HANDS = (HandId.LEFT, HandId.RIGHT)


# ----------------------------------------------------------------------------- helpers


def _pct(v: list[float], q: float) -> float | None:
    return float(np.percentile(v, q)) if v else None


def _dist(v: list[float]) -> dict[str, Any]:
    return {"n": len(v), "p50": _pct(v, 50), "p90": _pct(v, 90), "p95": _pct(v, 95),
            "mean": float(np.mean(v)) if v else None, "max": float(max(v)) if v else None}


def _rate(n: int, d: int) -> float | None:
    return n / d if d else None


def load_reference(name: str, allow_synthetic: bool) -> tuple[dict[tuple[int, str], dict], str | None]:
    """{(frame_id, hand_id): annotation} from tools/annotate_tip.py output, or ({}, reason)."""
    d = ANNOTATIONS / name
    real, synth = d / "tips.jsonl", d / "tips.SYNTHETIC.jsonl"
    path = real if real.exists() else (synth if (synth.exists() and allow_synthetic) else None)
    if path is None:
        why = ("no annotation file" if not synth.exists()
               else "only a SYNTHETIC annotation file exists (refused)")
        return {}, why
    ref: dict[tuple[int, str], dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            a = json.loads(line)
            if a.get("skipped"):
                continue
            ref[(int(a["frame_id"]), str(a["hand_id"]))] = a
    return ref, None


def speed_terciles(ref: dict[tuple[int, str], dict], roi: Roi) -> dict[tuple[int, str], str]:
    """Speed class per annotated (frame, hand) from finite differences of the reference tip (px/frame)."""
    by_hand: dict[str, list[tuple[int, np.ndarray]]] = {}
    for (fid, hid), a in ref.items():
        by_hand.setdefault(hid, []).append((fid, np.array(a["tip_px"], float)))
    speeds: dict[tuple[int, str], float] = {}
    for hid, items in by_hand.items():
        items.sort()
        for (f0, p0), (f1, p1) in zip(items, items[1:], strict=False):
            if f1 - f0 <= 3:
                speeds[(f1, hid)] = float(np.hypot(*(p1 - p0)) / (f1 - f0))
    if not speeds:
        return {}
    vals = np.array(list(speeds.values()))
    t1, t2 = np.percentile(vals, [33.3, 66.7])
    return {k: ("slow" if v <= t1 else "medium" if v <= t2 else "fast") for k, v in speeds.items()}


# ----------------------------------------------------------------------------- per capture


def run_capture(run: RunLog, cfg, landmarker: HandLandmarker, cap, views, *, name: str, meta: dict,
                overlay_every: int, allow_synthetic_ref: bool) -> dict[str, Any]:
    stick_settings = StickSettings.from_config(cfg.data)
    tracker_settings = TrackerSettings.from_config(cfg.data)
    estimators = {m: make_tip_estimator(m, stick_settings) for m in METHODS}
    trackers = {m: {h: CausalTracker(h, tracker_settings) for h in HANDS} for m in METHODS}
    for m in METHODS:
        for h in HANDS:
            trackers[m][h].reset(ResetReason.SESSION_START)
    ref, ref_note = load_reference(name, allow_synthetic_ref)
    roi = Roi.from_rect(meta["roi_px"])
    speed_cls = speed_terciles(ref, roi) if ref else {}

    per_method: dict[str, dict[str, Any]] = {}
    for m in METHODS:
        per_method[str(m)] = {"frames_hand": 0, "present": 0, "low_conf": 0, "no_axis": 0, "fallback": 0,
                              "tip_conf": [], "axis_conf": [], "compute_s": [], "support_px": [],
                              "errors_px": [], "errors_norm": [],
                              "errors_by_speed": {"slow": [], "medium": [], "fast": []},
                              "ref_frames_present": 0, "ref_frames_absent": 0, "schema_errors": 0}
    agreement_px: list[float] = []
    states_by_method = {str(m): {str(h): [] for h in HANDS} for m in METHODS}
    stick_paths = {m: (run.dir / f"stick_observations.{name}.{m.value}.jsonl").open("w", encoding="utf-8")
                   for m in METHODS}
    track_path = (run.dir / f"track_states.{name}.jsonl").open("w", encoding="utf-8")
    n_frames = 0
    shots = 0
    try:
        for view in views:
            n_frames += 1
            res = landmarker.detect(view)
            per_hand_records: dict[HandId, dict[TipMethod, Any]] = {}
            analyses: dict[TipMethod, dict[HandId, Any]] = {m: {} for m in METHODS}
            tracks: dict[TipMethod, dict[HandId, Any]] = {m: {} for m in METHODS}
            for h in HANDS:
                obs = res.left if h is HandId.LEFT else res.right
                per_hand_records[h] = {}
                for m in METHODS:
                    est = estimators[m]
                    t0 = timing.now()
                    so = est.estimate(view, obs)
                    dt = timing.now() - t0
                    pm = per_method[str(m)]
                    pm["compute_s"].append(dt)
                    stick_paths[m].write(json.dumps(so.to_dict()) + "\n")
                    if contract_schema.errors("stick-observation", so.to_dict()):
                        pm["schema_errors"] += 1
                    per_hand_records[h][m] = so
                    analyses[m][h] = est.last_analysis
                    if obs.present:
                        pm["frames_hand"] += 1
                        if so.present:
                            pm["present"] += 1
                            pm["tip_conf"].append(so.tip_confidence)
                            pm["axis_conf"].append(so.axis_confidence)
                            if so.tip_confidence < tracker_settings.machine.c_valid:
                                pm["low_conf"] += 1
                            an = est.last_analysis
                            if an is not None and an.axis is not None:
                                pm["support_px"].append(an.axis.support_len_px)
                    key = (view.sample.frame_id, str(h))
                    if key in ref:
                        a = ref[key]
                        if so.present:
                            tx, ty = norm_to_px_point(so.tip[0], so.tip[1], roi)
                            err_px = float(np.hypot(tx - a["tip_px"][0], ty - a["tip_px"][1]))
                            pm["errors_px"].append(err_px)
                            pm["errors_norm"].append(err_px / roi.h)
                            pm["ref_frames_present"] += 1
                            cls = speed_cls.get(key)
                            if cls:
                                pm["errors_by_speed"][cls].append(err_px)
                        else:
                            pm["ref_frames_absent"] += 1
                    st = trackers[m][h].update(obs, so, view.sample.t_capture)
                    tracks[m][h] = st
                    states_by_method[str(m)][str(h)].append(st)
                    track_path.write(json.dumps({"method": str(m), **st.to_dict()}) + "\n")
                g = per_hand_records[h].get(TipMethod.GEOM)
                r_ = per_hand_records[h].get(TipMethod.AXIS_REFINED)
                if g is not None and r_ is not None and g.present and r_.present:
                    gx, gy = norm_to_px_point(g.tip[0], g.tip[1], roi)
                    rx_, ry_ = norm_to_px_point(r_.tip[0], r_.tip[1], roi)
                    agreement_px.append(float(np.hypot(gx - rx_, gy - ry_)))
            # counters that live on the estimators
            for m in METHODS:
                per_method[str(m)]["no_axis"] = estimators[m].counters["no_axis"]
                per_method[str(m)]["fallback"] = estimators[m].counters["fallback"]
            if overlay_every and view.full is not None and view.sample.frame_id % overlay_every == 0:
                hands = {h: (res.left if h is HandId.LEFT else res.right) for h in HANDS}
                sticks = {h: per_hand_records[h][TipMethod.GEOM] for h in HANDS}
                img = draw_debug_overlay(view.full, roi, hands, analyses[TipMethod.GEOM], sticks,
                                         tracks[TipMethod.GEOM],
                                         title=f"{name} frame {view.sample.frame_id} GEOM (primary)")
                # add the AXIS_REFINED tip in its own colour on the same image (method comparison)
                for h in HANDS:
                    so = per_hand_records[h][TipMethod.AXIS_REFINED]
                    if so.present:
                        px, py = norm_to_px_point(so.tip[0], so.tip[1], roi)
                        cv2.circle(img, (int(px), int(py)), 7, (255, 0, 255), 1)
                p = run.dir / f"overlay.{name}.frame{view.sample.frame_id:05d}.png"
                cv2.imwrite(str(p), img)
                run.add_artefact(p, "figure")
                shots += 1
    finally:
        for fh in stick_paths.values():
            fh.close()
        track_path.close()
    for m in METHODS:
        run.add_artefact(run.dir / f"stick_observations.{name}.{m.value}.jsonl", "predictions")
    run.add_artefact(run.dir / f"track_states.{name}.jsonl", "predictions")

    # --- summaries
    methods_out: dict[str, Any] = {}
    for m in METHODS:
        pm = per_method[str(m)]
        fh = pm["frames_hand"]
        err_rows: dict[str, Any]
        if ref:
            err_rows = {
                "status": "MEASURED" if pm["errors_px"] else "NO_MATCHED_FRAMES",
                "n_reference_frames_hand": pm["ref_frames_present"] + pm["ref_frames_absent"],
                "n_estimate_present": pm["ref_frames_present"],
                "failure_rate_on_reference": _rate(pm["ref_frames_absent"],
                                                   pm["ref_frames_present"] + pm["ref_frames_absent"]),
                "error_px": _dist(pm["errors_px"]),
                "error_roi_height_units": _dist(pm["errors_norm"]),
                "error_px_by_speed_tercile": {k: _dist(v) for k, v in pm["errors_by_speed"].items()},
                "reference_kind": ("SYNTHETIC (self-test only)"
                                   if allow_synthetic_ref and not (ANNOTATIONS / name / "tips.jsonl").exists()
                                   else "manual annotation (tools/annotate_tip.py)"),
            }
        else:
            err_rows = {"status": "PENDING",
                        "reason": f"{ref_note}: run tools/annotate_tip.py --capture {name} "
                                  f"(person-dependent); no reference is invented"}
        methods_out[str(m)] = {
            "hand_frames": fh,
            "present": pm["present"],
            "present_rate": _rate(pm["present"], fh),
            "low_confidence_rate": _rate(pm["low_conf"], pm["present"]),
            "no_axis_frames": pm["no_axis"],
            "fallback_frames": pm["fallback"],
            "fallback_rate": _rate(pm["fallback"], fh) if m is TipMethod.AXIS_REFINED else None,
            "tip_confidence": _dist(pm["tip_conf"]),
            "axis_confidence": _dist(pm["axis_conf"]),
            "axis_support_px": _dist(pm["support_px"]),
            "compute_per_hand_frame_s": _dist(pm["compute_s"]),
            "schema_errors": pm["schema_errors"],
            "error_vs_reference": err_rows,
            "label": "FALLBACK / BENCHMARK CONDITION ONLY (REQ-211, I-7); no marker-equipped capture exists"
            if m is TipMethod.MARKER else "markerless",
        }
    trackers_out: dict[str, Any] = {}
    for m in METHODS:
        trackers_out[str(m)] = {}
        for h in HANDS:
            sts = states_by_method[str(m)][str(h)]
            hist: dict[str, int] = {}
            for st in sts:
                hist[st.status.value] = hist.get(st.status.value, 0) + 1
            trk = trackers[m][h]
            trackers_out[str(m)][str(h)] = {
                "states": len(sts),
                "status_histogram": hist,
                "resets": [r.to_dict() for r in trk.resets if r.frame_id is not None],
                "trace": "".join(st.status.value[0] for st in sts),
                "schema_valid_all": all(not contract_schema.errors("track-state", st.to_dict())
                                        for st in sts),
                "one_state_per_frame": len(sts) == n_frames,
                "tracker_id": trk.tracker_id,
                "declared_history": trk.declared_history(),
            }
    return {
        "capture": name, "n_frames": n_frames, "lighting": meta.get("lighting"),
        "exposure": meta.get("exposure"),
        "roi_px": meta.get("roi_px"), "methods": methods_out,
        "agreement_axis_refined_vs_geom_px": _dist(agreement_px),
        "trackers": trackers_out, "overlay_frames": shots,
        "reference": {"available": bool(ref), "n_annotations": len(ref), "note": ref_note},
    }


# ----------------------------------------------------------------------------- distance frames (03.11)


def run_distance(run: RunLog, cfg, landmarker_unused: HandLandmarker) -> dict[str, Any]:
    """Single stills: an IMAGE-mode landmarker (VIDEO mode assumes consecutive frames)."""
    stick_settings = StickSettings.from_config(cfg.data)
    est = make_tip_estimator(TipMethod.GEOM, stick_settings)
    import dataclasses

    hs = dataclasses.replace(HandLandmarkerSettings.from_config(cfg.data), running_mode="IMAGE")
    landmarker = HandLandmarker(hs)
    rows: dict[str, Any] = {}
    ddir = DEV_CAPTURES / "distance"
    if not ddir.exists():
        return {"status": "PENDING", "reason": "no data/dev-captures/distance/ on this machine"}
    dirs = sorted(p for p in ddir.iterdir() if (p / "frame.png").exists() and (p / "capture.json").exists())
    for d in dirs:
        side = json.loads((d / "capture.json").read_text(encoding="utf-8"))
        full = cv2.imread(str(d / "frame.png"), cv2.IMREAD_COLOR)
        roi = Roi.from_rect(side["roi_px"])
        s = FrameSample(frame_id=0, t_capture=0.0, t_frame_available=0.001,
                        timestamp_source=TimestampSource.REPLAY,
                        frame_size_px=(full.shape[1], full.shape[0]), roi_px=roi.as_tuple(),
                        image_ref=ImageRef.memory(full), camera_profile_id="hw01-integrated-webcam-v0",
                        dropped_since_last=0)
        view = FrameView(sample=s, roi=crop_roi(full, roi), full=full)
        landmarker.identity.reset()
        res = landmarker.detect(view)
        hands_out: dict[str, Any] = {}
        analyses: dict[HandId, Any] = {}
        sticks: dict[HandId, Any] = {}
        for h in HANDS:
            obs = res.left if h is HandId.LEFT else res.right
            so = est.estimate(view, obs)
            an = est.last_analysis
            analyses[h], sticks[h] = an, so
            hands_out[str(h)] = {
                "landmarks_present": obs.present,
                "handedness_score": obs.handedness_score,
                "hand_span_px": (an.region.span_px if an is not None and an.region is not None else None),
                "axis_found": bool(an is not None and an.axis is not None),
                "axis_confidence": (an.axis.confidence if an is not None and an.axis is not None else None),
                "axis_support_px": (an.axis.support_len_px if an is not None and an.axis is not None
                                    else None),
                "geom_tip_present": so.present,
            }
        img = draw_debug_overlay(full, roi, {h: (res.left if h is HandId.LEFT else res.right) for h in HANDS},
                                 analyses, sticks, None,
                                 title=f"distance {side['label']} ({side['distance_m']} m) GEOM")
        p = run.dir / f"overlay.distance.{side['label']}.png"
        cv2.imwrite(str(p), img)
        run.add_artefact(p, "figure")
        rows[side["label"]] = {"distance_m": side["distance_m"], "lighting": side.get("lighting"),
                               "exposure": side.get("exposure"), "n_frames": 1,
                               "note": ("single frame per distance (Phase 02 Task 02.7 capture); "
                                        "presence is 1-frame evidence, not a rate"),
                               "hands": hands_out}
    landmarker.close()
    return {"status": "MEASURED (single frames, L2 only, IMAGE mode)", "rows": rows}


# ----------------------------------------------------------------------------- synthetic self-test


class _SynthCap:
    name = "synthetic"

    def __init__(self, roi: Roi, n: int = 12) -> None:
        self.roi = roi
        self.meta = {"lighting": "synthetic", "exposure": None, "roi_px": list(roi.as_tuple())}
        self.samples = []
        for i in range(n):
            full = np.full((480, 640, 3), 70, np.uint8)
            # a light stick drawn along the stub hand's knuckle-row direction (pinky -> index of the stub
            # landmarks points down-left in pixels) from the stub RIGHT hand's grip point
            gx, gy = roi.x + 0.302 * roi.w, roi.y + 0.793 * roi.h
            ux, uy = -0.7276, 0.6860
            p0 = (int(gx + 6 * ux), int(gy + 6 * uy))
            p1 = (int(gx + 96 * ux), int(gy + 96 * uy))
            cv2.line(full, p0, p1, (200, 200, 200), 7)
            t = 50.0 + i / 30
            self.samples.append(FrameSample(frame_id=i, t_capture=t, t_frame_available=t + 0.001,
                                            timestamp_source=TimestampSource.REPLAY, frame_size_px=(640, 480),
                                            roi_px=roi.as_tuple(), image_ref=ImageRef.memory(full),
                                            camera_profile_id="synthetic", dropped_since_last=0))

    def __len__(self) -> int:
        return len(self.samples)


# ----------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--experiments-dir", type=Path, default=None)
    ap.add_argument("--base-config", type=Path, default=DEFAULT_BASE)
    ap.add_argument("--camera-config", type=Path, default=DEFAULT_CAMERA)
    ap.add_argument("--capture", action="append", default=[])
    ap.add_argument("--distance", action="store_true",
                    help="also run the Task 03.11 single-frame distance rows")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--overlay-every", type=int, default=40,
                    help="overlay screenshot every N frames (0 = off)")
    ap.add_argument("--allow-synthetic-reference", action="store_true",
                    help="self-test only: accept tips.SYNTHETIC.jsonl as a reference (labelled)")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--hardware-id", default="HW-01")
    args = ap.parse_args(argv)

    cfg = load_config(args.base_config, args.camera_config)
    hands_settings = HandLandmarkerSettings.from_config(cfg.data)
    slug = "p03-tip-benchmark" + ("-synthetic" if args.synthetic else "")
    names = ["synthetic"] if args.synthetic else list(args.capture)
    desc = ("Task 03.10/03.11/03.13 tip-method benchmark "
            + ("(SYNTHETIC self-test: stub hands, drawn stick; numbers are not evidence)" if args.synthetic
               else f"on dev captures {names}{' + distance frames' if args.distance else ''}")
            + "; all three TipEstimators on the same replayed frames, one CausalTracker per hand per method; "
              "error vs reference only where tools/annotate_tip.py annotations exist (else PENDING). "
              "MARKER = fallback/benchmark condition only.")
    with RunLog(phase="03", task="03.10", slug=slug, config=cfg, hardware_id=args.hardware_id,
                experiments_dir=args.experiments_dir, description=desc) as run:
        landmarker = HandLandmarker(hands_settings, backend=StubBackend()) if args.synthetic \
            else HandLandmarker(hands_settings)
        print(f"detector_id: {landmarker.detector_id}")
        captures: dict[str, Any] = {}
        try:
            for name in names:
                if args.synthetic:
                    cap: Any = _SynthCap(Roi.from_rect(cfg["roi"]["px"]))
                    views: Any = _iter_synthetic(cap)
                else:
                    cap = load_dev_capture(name, limit=args.limit)
                    views = iter_views(cap)
                print(f"\n== {name}: {len(cap)} frames")
                m = run_capture(run, cfg, landmarker, cap, views, name=name, meta=cap.meta,
                                overlay_every=args.overlay_every,
                                allow_synthetic_ref=args.allow_synthetic_reference)
                captures[name] = m
                for meth, mm in m["methods"].items():
                    c = mm["compute_per_hand_frame_s"]
                    e = mm["error_vs_reference"]
                    print(f"  {meth:12s} present {mm['present']}/{mm['hand_frames']} ({mm['present_rate']}) "
                          f"low-conf rate {mm['low_confidence_rate']} no-axis {mm['no_axis_frames']} "
                          f"fallback {mm['fallback_frames']} compute p50 {1000 * (c['p50'] or 0):.2f} ms "
                          f"p95 {1000 * (c['p95'] or 0):.2f} ms; error vs reference: {e['status']}")
                print(f"  AXIS_REFINED vs GEOM tip distance px: {m['agreement_axis_refined_vs_geom_px']}")
                for meth, th in m["trackers"].items():
                    for h, tt in th.items():
                        print(f"  tracker[{meth}][{h}] {tt['status_histogram']} resets {len(tt['resets'])} "
                              f"schema_ok {tt['schema_valid_all']} one/frame {tt['one_state_per_frame']}")
            distance = run_distance(run, cfg, landmarker) if (args.distance and not args.synthetic) else None
            if distance:
                print("\n== distance rows:", json.dumps(distance, indent=1)[:1500])
        finally:
            landmarker.close()
        run.write_json_artefact("benchmark.json", {"captures": captures, "distance": distance})
        run.finish({"captures": captures, "distance": distance, "synthetic": args.synthetic,
                    "detector_id": landmarker.detector_id})
        print(f"\nRESULT: COMPLETED {run.run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
