"""Phase 02, Task 02.8: capture-latency measurement by the screen-flash method.

Method (docs/protocols/capture-latency-flash-method.md):

1. A full-screen OpenCV window shows black. The webcam runs through ``LiveFrameSource`` with
   MANUAL exposure (auto-exposure would adapt to the flash) and the ROI of the config.
2. Baseline: after ``--settle`` seconds with the black window (the scene must stop reacting to
   whatever the screen showed before), the mean luminance L of a detection patch (whole frame by
   default, or a ``--patch`` in ROI-normalized coordinates) is sampled over ``--baseline``
   seconds -> global mu, sigma (reported). Detection uses a **rolling** baseline: the last
   ``--baseline-frames`` frames before each flash give mu_i, sigma_i, so a slow drift of the
   room light cannot mask or fake a detection.
3. Trial: after a random wait (0.6-1.4 s) the window is switched to white; ``t_flash`` is the
   ``t_mono`` stamp taken immediately after ``cv2.waitKey(1)`` returns, i.e. when the frame was
   handed to the display pipeline. Frames are then read until the first frame whose L exceeds
   ``mu_i + max(k * sigma_i, min_delta)`` (k = ``--k``, candidate 6; ``--min-delta`` in grey
   levels, candidate 3.0 for a normally lit screen, lower when the screen is dim) or a timeout.
   That frame's ``t_frame_available`` and ``t_capture`` are recorded.
4. The window returns to black and the loop waits for L to settle before the next trial.

Reported per trial: ``raw = t_frame_available(detect) - t_flash`` (the quantity the phase
document asks for, an UPPER BOUND on capture latency because it includes the display
pipeline's own latency from the waitKey return to photons, and the exposure phase), the
``t_capture`` variant ``t_capture(detect) - t_flash`` (how much of the wait the stamped
``t_capture`` recovers), the frame period, and ``raw - period/2`` (the flash instant is
uniformly distributed within a frame period; the half-period correction is the *mean*
correction and is reported beside the raw distribution, never instead of it).

Known limitations (must accompany every number): display latency of the laptop panel is
unknown and included; the scene must be lit by the screen (dim room or a mirror), so the
contrast of the flash is reported per trial; the detection frame is the first *exposed after*
the flash reached the scene, so the true capture latency is bounded above by the raw values.

Usage:
    python scripts/measure_capture_latency.py --backend DSHOW --trials 30
    python scripts/measure_capture_latency.py --synthetic --trials 5   # self-test, no camera/window
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

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
from spacedrums.capture.backend import CameraOpenSpec, RawFrame  # noqa: E402
from spacedrums.config import load_config  # noqa: E402
from spacedrums.contracts import TimestampSource  # noqa: E402

DEFAULT_BASE = ROOT / "configs" / "example.candidate.yaml"
DEFAULT_CAMERA = ROOT / "configs" / "camera" / "hw01-integrated-webcam.candidate.yaml"
WINDOW = "spacedrums-flash"


class _Display:
    """Full-screen black/white window (real) or a no-op stand-in (synthetic self-test)."""

    def __init__(self, enabled: bool, size: tuple[int, int] = (1280, 720)) -> None:
        self.enabled = enabled
        self._black = np.zeros((size[1], size[0], 3), np.uint8)
        self._white = np.full((size[1], size[0], 3), 255, np.uint8)
        if enabled:
            import cv2

            cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
            cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
            self.show(False)

    def show(self, white: bool) -> float:
        if self.enabled:
            import cv2

            cv2.imshow(WINDOW, self._white if white else self._black)
            cv2.waitKey(1)
        return timing.now()

    def close(self) -> None:
        if self.enabled:
            import cv2

            cv2.destroyWindow(WINDOW)
            cv2.waitKey(1)


class _FlashSyntheticCamera(SyntheticCamera):
    """Synthetic camera whose frames brighten ``latency_s`` after ``flash_at`` (self-test only)."""

    def __init__(self, latency_s: float = 0.02, **kw: Any) -> None:
        super().__init__(**kw)
        self.flash_at: float | None = None
        self.latency_s = latency_s

    def read(self) -> RawFrame | None:
        raw = super().read()
        if raw is None:
            return None
        img = raw.image.copy()
        img[:] = 40 + (self._i % 3)  # dark, tiny noise so frames are unique
        if self.flash_at is not None and raw.t_grab_return - self.latency_s >= self.flash_at:
            img[:] = 200 + (self._i % 3)
        return RawFrame(image=img, t_grab_return=raw.t_grab_return, t_driver_s=raw.t_driver_s)


def _patch_luminance(frame: np.ndarray, roi: Roi, patch: tuple[float, float, float, float] | None) -> float:
    if patch is None:
        return float(frame.mean())
    x, y, w, h = patch
    sub = crop_roi(frame, roi)
    hh, ww = sub.shape[:2]
    return float(sub[int(y * hh):int((y + h) * hh), int(x * ww):int((x + w) * ww)].mean())


def run_trials(
    *,
    src: LiveFrameSource,
    display: _Display,
    trials: int,
    baseline_s: float,
    k: float,
    min_delta: float,
    patch: tuple[float, float, float, float] | None,
    timeout_s: float,
    rng: np.random.Generator,
    synthetic_cam: _FlashSyntheticCamera | None,
    settle_s: float = 3.0,
    baseline_frames: int = 15,
) -> dict[str, Any]:
    roi = src.roi
    assert roi is not None

    def lum(f) -> float:
        return _patch_luminance(f.image_ref.array, roi, patch)

    # settle: let the scene stop reacting to whatever the screen showed before the black window
    t_end = timing.now() + settle_s
    while timing.now() < t_end:
        src.next_frame(timeout=0.5)
    # global baseline (reported; detection uses the rolling per-trial baseline below)
    t_end = timing.now() + baseline_s
    base: list[float] = []
    t_caps: list[float] = []
    while timing.now() < t_end:
        f = src.next_frame(timeout=0.5)
        if f is not None:
            base.append(lum(f))
            t_caps.append(f.t_capture)
    if len(base) < 10:
        raise RuntimeError("no frames during baseline")
    mu, sigma = float(np.mean(base)), float(np.std(base))
    period = float(np.median(np.diff(t_caps))) if len(t_caps) > 2 else float("nan")
    threshold = mu + max(k * sigma, min_delta)
    print(f"global baseline luminance mu {mu:.2f} sigma {sigma:.3f} (threshold would be {threshold:.2f}); "
          f"frame period {period*1e3:.2f} ms; detection uses a rolling {baseline_frames}-frame baseline")

    results: list[dict[str, Any]] = []
    recent: list[float] = []
    for i in range(trials):
        # settle after the previous flash, then a random wait; keep the rolling baseline fresh
        settle_end = timing.now() + 1.2 + float(rng.uniform(0.6, 1.4))
        while timing.now() < settle_end:
            f = src.next_frame(timeout=0.5)
            if f is not None:
                recent.append(lum(f))
        recent = recent[-baseline_frames:]
        if len(recent) < max(5, baseline_frames // 2):
            raise RuntimeError("too few frames for the rolling baseline")
        mu_i, sigma_i = float(np.mean(recent)), float(np.std(recent))
        threshold = mu_i + max(k * sigma_i, min_delta)
        # drain anything queued so the first frame we read post-flash is fresh
        while src.next_frame(timeout=0.0) is not None:
            pass
        last_before: Any = None
        t_flash = display.show(True)
        if synthetic_cam is not None:
            synthetic_cam.flash_at = t_flash
        detect = None
        n_read = 0
        deadline = t_flash + timeout_s
        while timing.now() < deadline:
            f = src.next_frame(timeout=0.5)
            if f is None:
                continue
            n_read += 1
            value = lum(f)
            if value > threshold:
                detect = (f, value)
                break
            last_before = (f, value)
        display.show(False)
        if synthetic_cam is not None:
            synthetic_cam.flash_at = None
        row: dict[str, Any] = {"trial": i + 1, "t_flash": t_flash, "frames_read_after_flash": n_read,
                               "baseline_mu": mu_i, "baseline_sigma": sigma_i, "threshold": threshold}
        recent = []  # the flash frames must not feed the next baseline
        if detect is None:
            row["detected"] = False
            print(f"trial {i+1:2d}: NOT DETECTED within {timeout_s:.1f} s (baseline {mu_i:.2f}, "
                  f"threshold {threshold:.2f}, max lum seen "
                  f"{last_before[1] if last_before else float('nan'):.2f})")
        else:
            f, value = detect
            raw = f.t_frame_available - t_flash
            row.update({
                "detected": True,
                "frame_id": f.frame_id,
                "t_capture_detect": f.t_capture,
                "t_frame_available_detect": f.t_frame_available,
                "raw_latency_s": raw,
                "t_capture_minus_flash_s": f.t_capture - t_flash,
                "corrected_half_period_s": raw - period / 2 if period == period else None,
                "luminance_detect": value,
                "contrast_sigma": (value - mu_i) / sigma_i if sigma_i > 0 else None,
                "luminance_before": last_before[1] if last_before else None,
                "t_frame_available_before": last_before[0].t_frame_available if last_before else None,
                "timestamp_source": str(f.timestamp_source),
            })
            print(f"trial {i+1:2d}: raw {raw*1e3:6.1f} ms | "
                  f"t_capture-flash {(f.t_capture - t_flash)*1e3:6.1f} ms | "
                  f"contrast {(value - mu_i):.2f} levels ({row['contrast_sigma']:.0f} sigma) | "
                  f"frames after flash {n_read}")
        results.append(row)

    det = [r for r in results if r["detected"]]
    summary: dict[str, Any] = {
        "trials": trials, "detected": len(det), "global_baseline_mu": mu, "global_baseline_sigma": sigma,
        "frame_period_s": period, "k": k, "min_delta": min_delta, "patch_roi_norm": patch,
        "settle_s": settle_s, "baseline_frames": baseline_frames,
    }
    if det:
        raw = np.array([r["raw_latency_s"] for r in det])
        tc = np.array([r["t_capture_minus_flash_s"] for r in det])
        summary.update({
            "raw_latency_s": {"median": float(np.median(raw)), "p10": float(np.percentile(raw, 10)),
                              "p90": float(np.percentile(raw, 90)), "min": float(raw.min()),
                              "max": float(raw.max()), "mean": float(raw.mean()), "std": float(raw.std())},
            "t_capture_minus_flash_s": {"median": float(np.median(tc)), "p10": float(np.percentile(tc, 10)),
                                        "p90": float(np.percentile(tc, 90)), "min": float(tc.min()),
                                        "max": float(tc.max())},
            "corrected_half_period_median_s": float(np.median(raw) - period / 2),
            "contrast_sigma_min": float(min(r["contrast_sigma"] for r in det
                                            if r["contrast_sigma"] is not None)),
        })
        print(f"\nraw latency (t_frame_available - t_flash): median {np.median(raw)*1e3:.1f} ms, "
              f"p10 {np.percentile(raw,10)*1e3:.1f}, p90 {np.percentile(raw,90)*1e3:.1f}, "
              f"min {raw.min()*1e3:.1f}, max {raw.max()*1e3:.1f} ms  (n={len(det)}/{trials}; "
              f"UPPER BOUND incl. display latency)")
        print(f"t_capture - t_flash: median {np.median(tc)*1e3:.1f} ms; half-period-corrected raw median "
              f"{(np.median(raw) - period/2)*1e3:.1f} ms")
    return {"summary": summary, "trials_detail": results}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-config", type=Path, default=DEFAULT_BASE)
    p.add_argument("--camera-config", type=Path, default=DEFAULT_CAMERA)
    p.add_argument("--backend", default=None)
    p.add_argument("--timestamp-source", choices=["DRIVER_MAPPED", "GRAB_RETURN"], default=None)
    p.add_argument("--mode", default=None, help="WxH@fps override (default: camera config)")
    p.add_argument("--exposure", default=None, help="MANUAL:<value> (default: camera config; AUTO refused)")
    p.add_argument("--trials", type=int, default=30)
    p.add_argument("--baseline", type=float, default=3.0)
    p.add_argument("--settle", type=float, default=3.0, help="seconds of black screen before the baseline")
    p.add_argument("--baseline-frames", type=int, default=15, help="rolling per-trial baseline length")
    p.add_argument("--k", type=float, default=6.0)
    p.add_argument("--min-delta", type=float, default=3.0)
    p.add_argument("--timeout", type=float, default=1.0)
    p.add_argument("--patch", default=None, help="x,y,w,h in ROI-normalized units (default: whole frame)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--slug", default=None)
    p.add_argument("--hardware-id", default="HW-01")
    p.add_argument("--experiments-dir", type=Path, default=None)
    p.add_argument("--synthetic", action="store_true")
    args = p.parse_args(argv)

    overrides: dict[str, Any] = {"camera_profile": {"device": {}}}
    if args.backend:
        overrides["camera_profile"]["device"]["backend"] = args.backend.upper()
    if args.timestamp_source:
        overrides["camera_profile"]["timestamp_source"] = args.timestamp_source
    if args.mode:
        res, fps = args.mode.split("@")
        w, h = res.lower().split("x")
        overrides["camera_profile"]["resolution_px"] = [int(w), int(h)]
        overrides["camera_profile"]["requested_fps"] = float(fps)
    if args.exposure:
        mode, _, value = args.exposure.partition(":")
        overrides["camera_profile"]["exposure"] = {"mode": mode.upper(),
                                                   "value": float(value) if value else None}
    cfg = load_config(args.base_config, args.camera_config, overrides=overrides)
    cam = cfg["camera_profile"]
    if cam["exposure"]["mode"] != "MANUAL" and not args.synthetic:
        p.error("the flash method needs MANUAL exposure (auto-exposure adapts to the flash)")
    patch = tuple(float(v) for v in args.patch.split(",")) if args.patch else None
    rng = np.random.default_rng(args.seed)

    slug = args.slug or (f"p02-latency-{(cam['device']['backend'] or 'any').lower()}"
                         + ("-synthetic" if args.synthetic else ""))
    description = (
        f"Task 02.8 capture latency by screen-flash method on {args.hardware_id}: backend "
        f"{cam['device']['backend']}, {cam['resolution_px'][0]}x{cam['resolution_px'][1]}"
        f"@{cam['requested_fps']:g}, "
        f"exposure {cam['exposure']}, timestamp policy {cam['timestamp_source']}, {args.trials} trials. "
        f"Raw values are an upper bound (display latency included)."
    )
    with RunLog(phase="02", task="02.8", slug=slug, description=description, config=cfg,
                hardware_id=args.hardware_id, experiments_dir=args.experiments_dir, seed=args.seed) as run:
        settings = CaptureSettings.from_config(cfg.data)
        synthetic_cam: _FlashSyntheticCamera | None = None
        if args.synthetic:
            synthetic_cam = _FlashSyntheticCamera(width=64, height=48, fps=100, paced=True, latency_s=0.02)
            settings = CaptureSettings(camera_profile_id=settings.camera_profile_id, spec=CameraOpenSpec(),
                                       roi=Roi(0, 0, 64, 48), timestamp_source=TimestampSource.GRAB_RETURN,
                                       nominal_fps=100, warmup_frames=5)
            camera: Any = synthetic_cam
        else:
            camera = OpenCvCamera()
        display = _Display(enabled=not args.synthetic)
        src = LiveFrameSource(camera, settings)
        try:
            mode = src.start()
            print(f"negotiated {mode.width}x{mode.height} {mode.fourcc} fps_prop={mode.fps_prop} "
                  f"stamp_after={mode.stamp_after} driver_ts={mode.has_driver_timestamps}")
            out = run_trials(src=src, display=display, trials=args.trials, baseline_s=args.baseline,
                             k=args.k, min_delta=args.min_delta, patch=patch, timeout_s=args.timeout,
                             rng=rng, synthetic_cam=synthetic_cam, settle_s=args.settle,
                             baseline_frames=args.baseline_frames)
            out["negotiated"] = mode.to_dict()
            out["capture_stats"] = src.stats().to_dict()
            out["timestamp_report"] = src.timestamp_report()
        finally:
            src.stop()
            display.close()
        run.write_json_artefact("latency_trials.json", out)
        s = out["summary"]
        metrics: dict[str, Any] = {
            "trials": s["trials"], "detected": s["detected"], "frame_period_s": s["frame_period_s"],
        }
        if s["detected"]:
            metrics.update({
                "capture_latency_raw_median_s": s["raw_latency_s"]["median"],
                "capture_latency_raw_p90_s": s["raw_latency_s"]["p90"],
                "capture_latency_raw_p10_s": s["raw_latency_s"]["p10"],
                "capture_latency_raw_min_s": s["raw_latency_s"]["min"],
                "capture_latency_raw_max_s": s["raw_latency_s"]["max"],
                "t_capture_minus_flash_median_s": s["t_capture_minus_flash_s"]["median"],
                "corrected_half_period_median_s": s["corrected_half_period_median_s"],
                "contrast_sigma_min": s["contrast_sigma_min"],
                "label": "MEASURED upper bound (includes display latency); see protocol limitations",
            })
        run.finish(metrics)
        print(f"\nRESULT: COMPLETED {run.run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
