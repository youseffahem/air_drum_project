"""Phase 02, Task 02.5: exposure / motion-blur setting procedure (docs/protocols/exposure-blur-procedure.md).

Three sub-commands:

  inspect   Machine-executable now. For each backend and each exposure setting (AUTO and a list
            of manual values) it applies the setting, waits, and records: whether the backend
            accepted it (set/readback), the short unique-frame rate (does the setting keep the
            sensor at ~30 FPS?), mean luminance, and a temporal-noise proxy (std of the frame
            difference in a static scene). Output -> experiments/<run_id>/exposure_inspect.json.

  record    Needs a person: records --seconds of frames (lossless PNG sequence + frames.jsonl
            of FrameSample records with image_ref FILE) while the person swings a stick through
            the ROI, for one exposure setting and one named lighting condition.
            Output -> data/dev-captures/<name>/ (git-ignored, never a dataset recording).
            Shows a live mirror preview with a readable guide (q stops early; --no-window
            disables it). Saved PNGs and frames.jsonl retain the original camera coordinates.

  analyze   Computes, per recorded frame, a motion proxy (mean |frame difference| inside the ROI)
            and a blur proxy (mean Sobel gradient magnitude over the *moving* pixels of the ROI);
            reports the frames with the largest motion and their blur proxy, and saves the
            peak-motion frame crop for the qualitative check. This is the CANDIDATE quantitative
            proxy of the phase document ("edge-gradient magnitude along the stick at peak speed");
            until Phase 03 localises the stick it is computed over the moving region, not along
            the stick axis, and is labelled as such.

Usage:
    python scripts/exposure_blur_check.py inspect --backends DSHOW,MSMF --values -4,-5,-6,-7,-8
    python scripts/exposure_blur_check.py record --name swing-room-light-exp-6 --exposure MANUAL:-6 \
        --lighting L2-overhead-room-light --seconds 6
    python scripts/exposure_blur_check.py analyze --name swing-room-light-exp-6
    python scripts/exposure_blur_check.py inspect --synthetic     # self-test
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

from _runlog import ROOT, RunLog  # noqa: E402

from spacedrums import timing  # noqa: E402
from spacedrums.capture import (  # noqa: E402
    CaptureSettings,
    LiveFrameSource,
    OpenCvCamera,
    Roi,
    SyntheticCamera,
    crop_roi,
)
from spacedrums.capture.backend import CameraOpenSpec  # noqa: E402
from spacedrums.config import load_config  # noqa: E402
from spacedrums.contracts import FrameSample, ImageRef, TimestampSource  # noqa: E402
from spacedrums.ui import draw_guide  # noqa: E402

DEFAULT_BASE = ROOT / "configs" / "example.candidate.yaml"
DEFAULT_CAMERA = ROOT / "configs" / "camera" / "hw01-integrated-webcam.candidate.yaml"
DEV_CAPTURES = ROOT / "data" / "dev-captures"
WINDOW = "Space Drums - developer capture (q to stop)"


def _cfg(args: argparse.Namespace, backend: str | None = None) -> Any:
    overrides: dict[str, Any] = {"camera_profile": {"device": {}}}
    if backend:
        overrides["camera_profile"]["device"]["backend"] = backend.upper()
    exposure = getattr(args, "exposure", None)
    if exposure:
        mode, _, value = exposure.partition(":")
        overrides["camera_profile"]["exposure"] = {"mode": mode.upper(),
                                                   "value": float(value) if value else None}
    return load_config(args.base_config, args.camera_config, overrides=overrides)


# ----------------------------------------------------------------------------- inspect


def _probe_setting(cam: OpenCvCamera, mode: str, value: float | None, n: int = 45) -> dict[str, Any]:
    rep = cam.apply_exposure(mode, value)
    timing.sleep_s(0.7)  # let the sensor settle
    for _ in range(5):
        cam.read()
    prev = None
    unique = 0
    lum: list[float] = []
    noise: list[float] = []
    t0 = timing.now()
    for _ in range(n):
        raw = cam.read()
        if raw is None:
            break
        img = raw.image
        if prev is not None:
            if not np.array_equal(prev, img):
                unique += 1
                d = img.astype(np.int16) - prev.astype(np.int16)
                noise.append(float(d.std()))
        else:
            unique += 1
        prev = img
        lum.append(float(img.mean()))
    dur = timing.now() - t0
    return {
        "mode": mode, "value": value, "apply": rep,
        "unique_fps_short": unique / dur if dur > 0 else None,
        "mean_luminance": float(np.mean(lum)) if lum else None,
        "temporal_noise_std": float(np.median(noise)) if noise else None,
        "note": "short probe; static scene assumed for the noise proxy",
    }


def cmd_inspect(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    values = [float(v) for v in args.values.split(",") if v.strip()]
    backends = [b.strip().upper() for b in args.backends.split(",") if b.strip()]
    slug = "p02-exposure-inspect" + ("-synthetic" if args.synthetic else "")
    with RunLog(phase="02", task="02.5", slug=slug, config=cfg, hardware_id=args.hardware_id,
                experiments_dir=args.experiments_dir,
                description=f"Task 02.5 exposure-control inspection on {args.hardware_id}: backends "
                            f"{backends}, manual values {values}; unique-FPS, luminance and noise "
                            "proxy per setting (short probes; lighting condition recorded in notes).") as run:
        out: dict[str, Any] = {"lighting_note": args.lighting, "rows": []}
        if not args.synthetic:
            cam_cfg = cfg["camera_profile"]
            for backend in backends:
                cam = OpenCvCamera()
                try:
                    mode = cam.open(CameraOpenSpec(index=cam_cfg["device"]["index"] or 0, backend=backend,
                                                   width=cam_cfg["resolution_px"][0],
                                                   height=cam_cfg["resolution_px"][1],
                                                   fps=cam_cfg["requested_fps"]))
                    for _ in range(10):
                        cam.read()
                    print(f"\n{backend}: negotiated {mode.width}x{mode.height} {mode.fourcc}")
                    print("| backend | setting | set ok | readback (auto, value) | unique FPS (short) | "
                          "mean lum | noise std |")
                    print("|---|---|---|---|---|---|---|")
                    settings = [("AUTO", None)] + [("MANUAL", v) for v in values] + [("AUTO", None)]
                    for m, v in settings:
                        row = _probe_setting(cam, m, v)
                        row["backend"] = backend
                        out["rows"].append(row)
                        a = row["apply"]
                        noise = row["temporal_noise_std"]
                        noise_txt = "-" if noise is None else f"{noise:.2f}"
                        print(f"| {backend} | {m}{'' if v is None else f' {v:g}'} | "
                              f"{a.get('set_auto_ok')}/{a.get('set_value_ok', '-')} | "
                              f"({a['readback_auto']:g}, {a['readback_value']:g}) | "
                              f"{row['unique_fps_short']:.1f} | {row['mean_luminance']:.0f} | "
                              f"{noise_txt} |")
                finally:
                    cam.close()
        run.write_json_artefact("exposure_inspect.json", out)
        run.finish({"n_rows": len(out["rows"]), "manual_exposure_settable": any(
            r["apply"].get("set_value_ok") for r in out["rows"]) if out["rows"] else None,
            "lighting_note": args.lighting})
        print(f"\nRESULT: COMPLETED {run.run_id}")
    return 0


# ----------------------------------------------------------------------------- record


def cmd_record(args: argparse.Namespace) -> int:
    cfg = _cfg(args, args.backend)
    settings = CaptureSettings.from_config(cfg.data)
    out_dir = DEV_CAPTURES / args.name
    if out_dir.exists() and any(out_dir.iterdir()):
        print(f"refusing to overwrite non-empty {out_dir}")
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    camera: Any = SyntheticCamera(width=640, height=480, fps=30) if args.synthetic else OpenCvCamera()
    if args.synthetic:
        settings = CaptureSettings(camera_profile_id=settings.camera_profile_id, spec=CameraOpenSpec(),
                                   roi=Roi.from_rect(cfg["roi"]["px"]), nominal_fps=30,
                                   timestamp_source=TimestampSource.GRAB_RETURN, warmup_frames=2)
    src = LiveFrameSource(camera, settings)
    mode = src.start()
    meta = {
        "purpose": "developer-only exposure/blur check (Task 02.5); NOT a dataset recording",
        "lighting": args.lighting, "exposure": cfg["camera_profile"]["exposure"],
        "negotiated": mode.to_dict(), "config_hash": cfg.config_hash, "roi_px": cfg["roi"]["px"],
        "started_at": timing.wall_clock_iso(), "seconds": args.seconds,
    }
    n = 0
    print(f"recording {args.seconds:.0f} s to {out_dir} - swing the stick through the box now")
    window = not args.synthetic and not args.no_window
    try:
        if window:
            cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        with (out_dir / "frames.jsonl").open("w", encoding="utf-8") as fh:
            t_end = timing.now() + args.seconds
            while timing.now() < t_end:
                f = src.next_frame(timeout=0.5)
                if f is None:
                    continue
                path = f"frame_{n:05d}.png"
                cv2.imwrite(str(out_dir / path), f.image_ref.array)
                rec = FrameSample(**{**f.__dict__, "image_ref": ImageRef.file(path, n, "FULL")})
                fh.write(json.dumps(rec.to_dict()) + "\n")
                n += 1
                if window:
                    cv2.imshow(WINDOW, draw_guide(f.image_ref.array, src.roi, mirror=True))
                    if cv2.pollKey() & 0xFF == ord("q"):
                        break
    finally:
        src.stop()
        if window:
            cv2.destroyWindow(WINDOW)
            cv2.waitKey(1)
    meta["frames"] = n
    meta["capture_stats"] = src.stats().to_dict()
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"recorded {n} frames; stats {meta['capture_stats']}")
    return 0


# ----------------------------------------------------------------------------- analyze


def analyze_sequence(frames: list[np.ndarray], roi: Roi, motion_threshold: float = 12.0) -> dict[str, Any]:
    rows = []
    prev_gray = None
    for i, img in enumerate(frames):
        gray = cv2.cvtColor(crop_roi(img, roi), cv2.COLOR_BGR2GRAY)
        if prev_gray is None:
            prev_gray = gray
            continue
        diff = cv2.absdiff(gray, prev_gray)
        moving = diff > motion_threshold
        motion = float(diff.mean())
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        mag = np.sqrt(gx * gx + gy * gy)
        blur_proxy = float(mag[moving].mean()) if moving.any() else None
        rows.append({"index": i, "motion_mean_absdiff": motion, "moving_fraction": float(moving.mean()),
                     "gradient_mag_in_moving_region": blur_proxy})
        prev_gray = gray
    ranked = sorted((r for r in rows if r["gradient_mag_in_moving_region"] is not None),
                    key=lambda r: -r["motion_mean_absdiff"])
    return {"per_frame": rows, "top_motion_frames": ranked[:5], "motion_threshold": motion_threshold,
            "proxy_note": "CANDIDATE blur proxy: mean Sobel gradient magnitude over pixels whose "
                          "inter-frame |diff| > threshold, inside the ROI; not yet along the stick axis "
                          "(Phase 03)"}


def cmd_analyze(args: argparse.Namespace) -> int:
    d = DEV_CAPTURES / args.name
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    roi = Roi.from_rect(meta["roi_px"])
    paths = sorted(d.glob("frame_*.png"))
    frames = [cv2.imread(str(p)) for p in paths]
    res = analyze_sequence(frames, roi, args.motion_threshold)
    res["lighting"] = meta["lighting"]
    res["exposure"] = meta["exposure"]
    (d / "blur_analysis.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"{args.name}: lighting {meta['lighting']}, exposure {meta['exposure']}, {len(frames)} frames")
    print("| frame | motion (mean |diff|) | moving fraction | "
          "gradient magnitude in moving region (blur proxy, higher = sharper) |")
    print("|---|---|---|---|")
    for r in res["top_motion_frames"]:
        print(f"| {r['index']} | {r['motion_mean_absdiff']:.2f} | {r['moving_fraction']:.3f} | "
              f"{r['gradient_mag_in_moving_region']:.1f} |")
    if res["top_motion_frames"]:
        peak = res["top_motion_frames"][0]["index"]
        crop = crop_roi(frames[peak], roi)
        cv2.imwrite(str(d / f"peak_motion_frame_{peak:05d}_roi.png"), crop)
        print("peak-motion ROI crop written for qualitative inspection: "
              f"peak_motion_frame_{peak:05d}_roi.png")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-config", type=Path, default=DEFAULT_BASE)
    p.add_argument("--camera-config", type=Path, default=DEFAULT_CAMERA)
    p.add_argument("--hardware-id", default="HW-01")
    p.add_argument("--experiments-dir", type=Path, default=None)
    p.add_argument("--synthetic", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("inspect")
    s.add_argument("--backends", default="DSHOW,MSMF")
    s.add_argument("--values", default="-4,-5,-6,-7,-8")
    s.add_argument("--lighting", default="unrecorded",
                   help="lighting condition id (docs/protocols/lighting-checklist.md)")
    s.set_defaults(func=cmd_inspect)
    r = sub.add_parser("record")
    r.add_argument("--name", required=True)
    r.add_argument("--backend", default=None)
    r.add_argument("--exposure", default=None)
    r.add_argument("--lighting", required=True)
    r.add_argument("--seconds", type=float, default=6.0)
    r.add_argument("--no-window", action="store_true", help="record without the live mirror preview")
    r.set_defaults(func=cmd_record)
    a = sub.add_parser("analyze")
    a.add_argument("--name", required=True)
    a.add_argument("--motion-threshold", type=float, default=12.0)
    a.set_defaults(func=cmd_analyze)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
