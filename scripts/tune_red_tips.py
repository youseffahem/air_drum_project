"""Tune the colour red-tip detector on recorded frames and label true tip centres (app.play --red-tips).

Never opens a camera, a microphone or a speaker. Works on what ``scripts/analyze_red_tips.py frames``
reads: a play ``--record-frames`` session, an image folder, a video file or a single image.

    python scripts/tune_red_tips.py data/dev-product/<session>
    python scripts/tune_red_tips.py photo.png --scale 0.6667
    python scripts/tune_red_tips.py data/dev-product/<session> --label --label-every 10
    python scripts/tune_red_tips.py <source> --no-window --set s_min=130 --set v_min=50 --save

**Tuning** (default) adjusts the HSV ``detector: colour`` (bright light, close range); every fragment it
writes sets ``detector: colour`` so app.play uses the tuned keys. The default ``redness`` detector has no
thresholds to tune: refit its cap verifier from your labels with ``scripts/analyze_red_tips.py
fit-verifier <session> ...`` instead. One window per frame, camera orientation (not mirrored):
- yellow crosshair = accepted blob's cap point (the tracked position), grey dot = the whole red region's
  centroid when it differs, grey ring + reason = rejected region; top-right inset: red = seeds (paint
  core), dark red = growth near seeds;
- trackbars: the colour bands and floors, growth, the seed share and the area limits;
- keys: ``n`` / ``p`` next / previous frame (``N`` / ``P`` jump 10), ``m`` full-size mask view, click =
  HSV percentiles of the region under the cursor (printed), ``s`` save, ``q`` / Esc quit.

``s`` writes the tuned values as a ``product: stick_tip:`` fragment (default
``configs/red-tip.tuned.yaml``), validated exactly as ``app.play --stick-tip-config`` will load it.

**Labelling** (``--label``): click the true centre of the painted cap of stick A, then of stick B, on
every ``--label-every``-th frame (follow the same physical stick as A throughout); ``x`` = the current
stick is not visible, ``c`` = clear this frame, ``n`` / ``p`` move. Labels are saved to ``--labels``
(default ``red-tip-labels.json`` in the session folder, or beside an image / video) in tracking-frame
pixels; score the detector against them
with ``scripts/analyze_red_tips.py frames <source> --labels <file>``.

Detection here is per frame (no tracking); tracking and continuity come from ``analyze_red_tips.py
frames``. Frames are held in memory: ``--stride`` / ``--max-frames`` bound that.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_red_tips as art  # noqa: E402

from spacedrums.app.play import stick_tip_override  # noqa: E402
from spacedrums.stick.red_tip import RedTipDetector, RedTipSettings  # noqa: E402

WINDOW = "SpaceDrums red-tip tuning (camera view, not mirrored)"
DEFAULT_OUTPUT = ROOT / "configs/red-tip.tuned.yaml"
# (setting, trackbar maximum, trackbar units per setting unit): integers unless the scale is not 1.
TRACKBARS = (
    ("hue_low_max", 30, 1), ("hue_high_min", 180, 1), ("hue_margin_weak", 15, 1),
    ("s_min", 255, 1), ("v_min", 255, 1), ("s_min_weak", 255, 1), ("v_min_weak", 255, 1),
    ("grow_px", 12, 1), ("min_seed_fraction", 100, 100), ("min_area_px", 400, 1), ("max_area_px", 600, 0.1),
)
TUNED_KEYS = tuple(name for name, _, _ in TRACKBARS) + (
    "v_highlight", "s_highlight_max", "head_length_factor", "head_contrast", "min_seed_px", "ignore_regions",
    "dark_paint", "dark_hue_min", "dark_hue_max", "dark_s_min", "dark_v_min", "dark_v_max", "dark_rg_min",
    "dark_hue_mean_max", "dark_rb_mean_max", "dark_s_mean_min", "dark_v_mean_min", "dark_min_area_px",
    "dark_max_area_px",
    "dark_max_elongation", "dark_birth_surround",
    "dark_birth_frames", "dark_confidence")
LABEL_COLOURS = ((60, 220, 60), (230, 200, 40))  # stick A green, stick B cyan


def parse_set(items: list[str]) -> dict:
    out = {}
    for item in items:
        key, _, value = item.partition("=")
        if key not in RedTipSettings.__dataclass_fields__:
            raise SystemExit(f"--set: unknown stick_tip setting {key!r}")
        out[key] = yaml.safe_load(value)
    return out


def settings_from(block: dict) -> RedTipSettings:
    return RedTipSettings(**block)


def write_fragment(path: Path, block: dict, source: str) -> dict:
    """Write the tuned keys as a ``product: stick_tip:`` fragment and validate it as app.play will. The keys
    tune the colour detector, so the fragment selects it (``detector: colour``)."""
    settings_from(block)  # cross-field rules (raises ValueError)
    tuned = {"detector": "colour", **{k: block[k] for k in TUNED_KEYS if k in block}}
    if isinstance(tuned.get("ignore_regions"), tuple):
        tuned["ignore_regions"] = [list(r) for r in tuned["ignore_regions"]]
    text = ("# Tuned with scripts/tune_red_tips.py on " + source + ".\n"
            "# Developer candidate, not a calibration. Play with:\n"
            "#   .\\play-spacedrums.ps1 --demo --red-tips --stick-tip-config " + str(path) + "\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text + yaml.safe_dump({"product": {"stick_tip": tuned}}, sort_keys=False))
    stick_tip_override(path)  # the same structural check app.play applies
    return tuned


def load_frames(args) -> list[tuple[int, np.ndarray]]:
    frames = []
    for k, view in enumerate(art.image_views(args.source, args.fps, None, scale=args.scale, repeat=1)):
        if k % args.stride:
            continue
        frames.append((view.sample.frame_id, np.ascontiguousarray(view.roi)))
        if len(frames) >= args.max_frames:
            break
    if not frames:
        raise SystemExit(f"no frames in {args.source}")
    return frames


def region_hsv(det, x: int, y: int) -> dict | None:
    """HSV percentiles of the detected region under (x, y), else of a 7 x 7 patch (signed hue around 0)."""
    h, w = det.hsv.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        return None
    pick = None
    if det.region is not None and det.region[y, x]:
        n, labels = cv2.connectedComponents((det.region > 0).astype(np.uint8))
        pick = labels == labels[y, x]
    if pick is None:
        pick = np.zeros((h, w), bool)
        pick[max(0, y - 3):y + 4, max(0, x - 3):x + 4] = True
    px = det.hsv[pick].astype(int)
    hue = (px[:, 0] + 90) % 180 - 90
    pct = (5, 25, 50, 75, 95)
    return {"pixels": int(len(px)), "hue_signed": np.percentile(hue, pct).round(1).tolist(),
            "s": np.percentile(px[:, 1], pct).round(0).tolist(),
            "v": np.percentile(px[:, 2], pct).round(0).tolist()}


def summarize(det) -> list[dict]:
    return [{"cap": [round(b.center[0], 1), round(b.center[1], 1)], "area": round(b.area, 1),
             "seed_fraction": None if b.seed_fraction is None else round(b.seed_fraction, 3),
             "region_centroid": [round(v, 1) for v in (b.region_center or b.center)]} for b in det.blobs]


def draw(img: np.ndarray, det, *, labels=None, active=None, full_mask=False, status="") -> np.ndarray:
    if full_mask:
        out = np.zeros_like(img)
        if det.region is not None:
            out[det.region > 0] = (40, 40, 140)
        out[det.mask > 0] = (60, 60, 255)
    else:
        out = img.copy()
        mask = np.zeros_like(img)
        if det.region is not None:
            mask[det.region > 0] = (40, 40, 140)
        mask[det.mask > 0] = (60, 60, 255)
        inset = cv2.resize(mask, (img.shape[1] // 4, img.shape[0] // 4), interpolation=cv2.INTER_AREA)
        out[: inset.shape[0], -inset.shape[1]:] = inset
    for b in det.rejected:
        p = tuple(map(round, b.center))
        cv2.circle(out, p, 7, (130, 130, 130), 1, cv2.LINE_AA)
        cv2.putText(out, str(b.reason), (p[0] + 8, p[1] + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.33,
                    (160, 160, 160), 1, cv2.LINE_AA)
    for b in det.blobs:
        p = tuple(map(round, b.center))
        cv2.drawMarker(out, p, (0, 220, 255), cv2.MARKER_CROSS, 22, 1, cv2.LINE_AA)
        if b.region_center is not None and math.dist(b.region_center, b.center) > 2:
            cv2.circle(out, tuple(map(round, b.region_center)), 3, (160, 160, 160), -1, cv2.LINE_AA)
    for i, p in enumerate(labels or ()):
        if p is not None:
            cv2.circle(out, tuple(map(round, p)), 13, LABEL_COLOURS[i], 2 if i == active else 1, cv2.LINE_AA)
            cv2.putText(out, "AB"[i], (round(p[0]) + 14, round(p[1])), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        LABEL_COLOURS[i], 1, cv2.LINE_AA)
    cv2.putText(out, status, (8, out.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (240, 240, 240), 1,
                cv2.LINE_AA)
    return out


def save_labels(path: Path, labels: dict[int, list], args, size) -> None:
    doc = {"source": str(args.source), "scale": args.scale, "frame_size": list(size), "sticks": ["A", "B"],
           "note": "Clicked centres of the painted caps (tracking pixels); A follows one physical stick.",
           "labelled_by": "a person, in scripts/tune_red_tips.py --label",
           "labels": {str(k): [None if p is None else [round(p[0], 2), round(p[1], 2)] for p in v]
                      for k, v in sorted(labels.items())}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


def calibrate_dark(frames, labels: dict[int, list], block: dict, radius: float = 3.0) -> dict:
    """The dark-paint profile from labelled caps: the pixel band from robust percentiles of the caps' central
    pixels (the rim mixes with the wall and the shaft), the blob limits from the 10th / 90th percentile of
    the per-cap averages, each with a small margin. Returns the updated keys and what they came from."""
    by_id = dict(frames)
    px, discs = [], []
    for fid, points in labels.items():
        img = by_id.get(fid)
        if img is None:
            continue
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.int16)
        h, w = img.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w]
        for p in points:
            if p is None:
                continue
            disc = (xx - p[0]) ** 2 + (yy - p[1]) ** 2 <= radius ** 2
            hue = hsv[..., 0][disc]
            hue = np.where(hue > 90, hue - 180, hue)
            b, g, r = (img[..., k][disc].astype(np.int16) for k in range(3))
            cols = np.stack([hue, hsv[..., 1][disc], hsv[..., 2][disc], r - g, r - b], axis=1)
            px.append(cols)
            discs.append(cols.mean(axis=0))
    if len(discs) < 5:
        raise SystemExit(f"--calibrate-dark needs at least 5 labelled caps in the frames, found {len(discs)}")
    px, discs = np.vstack(px), np.array(discs)
    pct = lambda col, q: float(np.percentile(px[:, col], q))  # noqa: E731
    cap = lambda col, q: float(np.percentile(discs[:, col], q))  # noqa: E731
    out = {
        "dark_paint": True,
        "dark_hue_min": int(np.clip(round(pct(0, 5) - 3), -89, 0)),
        "dark_hue_max": int(np.clip(round(pct(0, 95) + 3), 1, 89)),
        "dark_s_min": int(np.clip(round(pct(1, 10) - 5), 20, 200)),
        "dark_v_min": int(np.clip(round(pct(2, 5) - 3), 5, 200)),
        "dark_v_max": int(np.clip(round(pct(2, 98) + 20), 30, 255)),
        "dark_rg_min": int(np.clip(round(pct(3, 20)), 2, 60)),
        "dark_hue_mean_max": round(cap(0, 90) + 3, 1),
        "dark_rb_mean_max": round(cap(4, 90) + 2, 1),
        "dark_s_mean_min": round(cap(1, 10) - 5, 1),
        "dark_v_mean_min": round(cap(2, 10) - 3, 1),
    }
    if out["dark_v_min"] >= out["dark_v_max"]:
        raise SystemExit("--calibrate-dark: the labelled caps give an empty brightness band")
    search = _search_blob_limits(by_id, labels, {**block, **out}, cap)
    out.update(search.pop("limits"))
    block.update(out)
    settings_from(block)
    return {"caps": len(discs), "pixels": len(px), "updated": out, "search": search,
            "cap_pixel_percentiles_5_50_95": {name: np.percentile(px[:, k], [5, 50, 95]).round(1).tolist()
                                              for k, name in enumerate(("hue_signed", "s", "v", "r_minus_g",
                                                                        "r_minus_b"))}}


NEGATIVE_WEIGHT = 0.3  # recall given up per extra non-cap dark blob per frame (tracking suffers from them)
MATCH_PX = 6.0


def _search_blob_limits(by_id, labels, block, cap) -> dict:
    """Pick the four blob-average limits by grid search: run the dark pass once with the limits open, then
    score every combination by recall at the labelled caps minus NEGATIVE_WEIGHT x non-cap blobs per frame
    (unlabelled caps count as non-cap, so this errs on the strict side)."""
    loose = RedTipDetector(settings_from({**block, "dark_paint": True, "dark_hue_mean_max": 89.0,
                                          "dark_rb_mean_max": 255.0, "dark_s_mean_min": 0.0,
                                          "dark_v_mean_min": 0.0}))
    rows, frames, n_caps = [], 0, 0
    for fid, points in labels.items():
        img = by_id.get(fid)
        if img is None:
            continue
        frames += 1
        caps = [p for p in points if p is not None]
        n_caps += len(caps)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        _, region, _ = loose.segment(hsv)
        for b in loose._dark(img, hsv, region, Counter()):  # every candidate (detect() keeps the best 8)
            if b.colour is not None:
                near = [k for k, p in enumerate(caps) if math.dist(b.center, p) <= MATCH_PX]
                rows.append((*b.colour, (fid, near[0]) if near else None))
    if not rows:
        raise SystemExit("--calibrate-dark: the dark pass finds nothing at all with this pixel band")
    colour = np.array([r[:4] for r in rows], float)
    which = [r[4] for r in rows]
    grid = {
        "dark_hue_mean_max": sorted({round(cap(0, q) + m, 1) for q in (75, 90, 100) for m in (0, 3)}),
        "dark_s_mean_min": sorted({round(cap(1, q) - m, 1) for q in (0, 10, 25) for m in (0, 5)}),
        "dark_v_mean_min": sorted({round(cap(2, q) - m, 1) for q in (0, 10, 25) for m in (0, 3)}),
        "dark_rb_mean_max": sorted({round(cap(4, q) + m, 1) for q in (75, 90, 100) for m in (0, 2)}),
    }
    best = None
    for hue in grid["dark_hue_mean_max"]:
        for sat in grid["dark_s_mean_min"]:
            for val in grid["dark_v_mean_min"]:
                for rb in grid["dark_rb_mean_max"]:
                    ok = (colour[:, 0] <= hue) & (colour[:, 1] >= sat)
                    ok &= (colour[:, 2] >= val) & (colour[:, 3] <= rb)
                    found = {which[k] for k in np.flatnonzero(ok) if which[k] is not None}
                    negatives = sum(1 for k in np.flatnonzero(ok) if which[k] is None)
                    recall, per_frame = len(found) / n_caps, negatives / frames
                    score = recall - NEGATIVE_WEIGHT * per_frame
                    if best is None or score > best[0]:
                        best = (score, recall, per_frame, {"dark_hue_mean_max": hue, "dark_s_mean_min": sat,
                                                           "dark_v_mean_min": val, "dark_rb_mean_max": rb})
    return {"limits": best[3], "recall_at_labels": round(best[1], 3),
            "non_cap_blobs_per_frame": round(best[2], 2), "frames": frames}


def headless(args, block: dict, frames) -> dict:
    detector = RedTipDetector(settings_from(block))
    report = {"source": str(args.source), "frames": len(frames), "stick_tip": block,
              "detections": {str(fid): summarize(detector.detect(img)) for fid, img in frames}}
    if args.save:
        report["saved"] = str(args.output)
        report["fragment"] = write_fragment(args.output, block, str(args.source))
    return report


def interactive(args, block: dict, frames) -> None:  # pragma: no cover - needs a display
    state = {"k": 0, "full": False, "dirty": True, "active": 0, "click": None}
    labels: dict[int, list] = {}
    beside = args.source if args.source.is_dir() else args.source.parent  # data/** is git-ignored
    labels_path = args.labels or beside / "red-tip-labels.json"
    if args.label and labels_path.exists():
        labels = {int(k): v for k, v in art.load_labels(labels_path).items()}
    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)

    def on_bar(_):
        state["dirty"] = True

    for name, top, scale in TRACKBARS:
        cv2.createTrackbar(name, WINDOW, int(round(block[name] * scale)), top, on_bar)
    cv2.createTrackbar("frame", WINDOW, 0, max(1, len(frames) - 1), on_bar)

    def on_mouse(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN:
            state["click"] = (x, y)

    cv2.setMouseCallback(WINDOW, on_mouse)
    detector, last_block, det = None, None, None
    while True:
        k = cv2.getTrackbarPos("frame", WINDOW)
        state["k"] = k
        for name, _, scale in TRACKBARS:
            v = cv2.getTrackbarPos(name, WINDOW) / scale
            block[name] = int(v) if scale == 1 and isinstance(block[name], int) else float(v)
        try:
            if block != last_block:
                detector, last_block = RedTipDetector(settings_from(block)), dict(block)
            error = ""
        except ValueError as exc:
            error = f"invalid: {exc}"
        fid, img = frames[k]
        if detector is not None and (state["dirty"] or det is None):
            det = detector.detect(img)
            state["dirty"] = False
        if state["click"] is not None and det is not None:
            (x, y), state["click"] = state["click"], None
            if args.label:
                pts = labels.setdefault(fid, [None, None])
                pts[state["active"]] = (float(x), float(y))
                state["active"] = 1 - state["active"]
                save_labels(labels_path, labels, args, img.shape[1::-1])
            else:
                print(json.dumps({"frame": fid, "at": [x, y], "hsv": region_hsv(det, x, y)}))
        mode = f"LABEL stick {'AB'[state['active']]}" if args.label else "TUNE"
        found = len(det.blobs) if det else 0
        keys = "n/p frame  m mask  s save  q quit"
        status = error or f"{mode}  frame {fid} ({k + 1}/{len(frames)})  accepted {found}  {keys}"
        shown = img if det is None else draw(img, det, labels=labels.get(fid), active=state["active"],
                                             full_mask=state["full"], status=status)
        cv2.imshow(WINDOW, shown)
        key = cv2.waitKey(30) & 0xFF
        step = {ord("n"): 1, ord("p"): -1, ord("N"): 10, ord("P"): -10}.get(key)
        if args.label and step in (1, -1):
            step *= max(1, args.label_every)
        if step:
            cv2.setTrackbarPos("frame", WINDOW, int(np.clip(k + step, 0, len(frames) - 1)))
            state["active"], state["dirty"] = 0, True
        elif key == ord("m"):
            state["full"] = not state["full"]
        elif key == ord("x") and args.label:
            labels.setdefault(fid, [None, None])[state["active"]] = None
            state["active"] = 1 - state["active"]
            save_labels(labels_path, labels, args, img.shape[1::-1])
        elif key == ord("c") and args.label:
            labels.pop(fid, None)
            state["active"] = 0
            save_labels(labels_path, labels, args, img.shape[1::-1])
        elif key == ord("s"):
            try:
                write_fragment(args.output, block, str(args.source))
                print(f"saved {args.output}; play with --stick-tip-config {args.output}")
            except ValueError as exc:
                print(f"not saved: {exc}")
        elif key in (ord("q"), 27):
            break
    cv2.destroyAllWindows()
    if args.label:
        scale = f" --scale {args.scale}" if args.scale != 1 else ""
        print(f"labels: {labels_path} ({len(labels)} frames); score with\n"
              f"  python scripts/analyze_red_tips.py frames {args.source} --labels {labels_path}"
              f" --output <dir>{scale}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path, help="session dir, image dir, video file or image")
    ap.add_argument("--stick-tip-config", type=Path, help="start from this 'product: stick_tip:' fragment")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="tuned fragment written by 's'")
    ap.add_argument("--scale", type=float, default=1.0, help="resize images/videos (0.6667: native window)")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--stride", type=int, default=1, help="keep every n-th frame")
    ap.add_argument("--max-frames", type=int, default=600)
    ap.add_argument("--label", action="store_true", help="click the true cap centres of sticks A and B")
    ap.add_argument("--label-every", type=int, default=10, help="label mode: frames between labelled frames")
    ap.add_argument("--labels", type=Path, help="labels file (default: red-tip-labels.json by the source)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override a setting")
    ap.add_argument("--no-window", action="store_true", help="print detections as JSON instead of a window")
    ap.add_argument("--save", action="store_true", help="--no-window: also write the fragment to --output")
    ap.add_argument("--calibrate-dark", type=Path, metavar="LABELS",
                    help="derive the dark-paint profile (dim light, playing distance) from labelled caps and "
                         "write it, with dark_paint: true, to --output")
    args = ap.parse_args(argv)
    block = {**art.tip_block(args.stick_tip_config), **parse_set(args.set)}
    settings_from(block)
    frames = load_frames(args)
    cv2.setNumThreads(1)
    if args.calibrate_dark:
        report = calibrate_dark(frames, art.load_labels(args.calibrate_dark), block)
        source = f"{args.source} (labels {args.calibrate_dark})"
        report["fragment"] = write_fragment(args.output, block, source)
        report["saved"] = str(args.output)
        print(json.dumps(report, indent=1))
        return 0
    if args.no_window:
        print(json.dumps(headless(args, block, frames), indent=1))
    else:
        interactive(args, block, frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
