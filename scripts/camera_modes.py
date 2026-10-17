"""Camera mode and image-quality diagnostics (ADR-0047). Never starts decisions, audio or tracking.

``modes``   opens each backend x requested size x FOURCC request with the app's camera wrapper and
            records what was REQUESTED, what the driver REPORTS (advertised) and what was VERIFIED on
            the delivered frames: their actual size, unique-frame rate, duplicate share, interval
            stability, brightness, temporal noise and detail. A mode counts as delivered only when
            every frame has the requested size at >= 80 % of the requested rate.
``exposure`` AUTO and fixed exposures (default auto, -7 ... -3) on the app's capture path with the
            exposure guard off, forward then reverse order: requested setting, driver read-back
            (unreliable on HW-01), unique FPS, interval stability, tracking-frame brightness, black
            and white levels, saturation, noise, the natural preview's brightness and gamma, and with
            ``--perception`` the tracking cost and hands seen per frame.
``compare`` A/B of the app's capture paths (``app.play --camera standard`` vs ``native``), alternated
            for ``--repeats``: capture mode and its open probe, delivered FPS, drops, duplicates,
            interval stability, hand-over lag, crop/downscale cost, process CPU, the display image
            each path produces and a field-of-view registration of the two tracking frames.

Image metrics are scene-dependent: run with a static, unchanged scene and compare arms of one run,
never numbers across runs. "detail" is the mean squared Sobel gradient after a sigma-1 Gaussian; it
also rises with noise, so read it with the temporal-noise column. Driver properties are reported as
advertised only. Outputs (JSON + PNG, possibly showing the room) stay in the --output directory.

Usage:
    python scripts/camera_modes.py modes   [--backends DSHOW,MSMF] [--exposure profile|auto|-5 ...]
    python scripts/camera_modes.py exposure [--camera native|standard] [--exposure auto --exposure -5 ...]
                                            [--perception hands|red-tips]
    python scripts/camera_modes.py compare [--seconds 10] [--repeats 2] [--exposure profile|auto|-5]
                                           [--perception none|hands|red-tips]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spacedrums.app.play import exposure_override, play_config  # noqa: E402
from spacedrums.capture import CaptureSettings, LiveFrameSource, OpenCvCamera  # noqa: E402
from spacedrums.capture.backend import CameraOpenSpec  # noqa: E402
from spacedrums.timing import now, process_cpu_seconds, wall_clock_local_compact  # noqa: E402

SIZES = ((640, 480), (1280, 720), (1920, 1080))
FOURCCS = (None, "MJPG")
STAGE_SCALE = 1.5  # ui.stage.SCALE: the window shows the 640x480 frame at 960x720


def gray(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def detail(g):
    """Mean squared Sobel gradient after a sigma-1 Gaussian (noise-sensitive; see module doc)."""
    s = cv2.GaussianBlur(g, (0, 0), 1.0).astype(np.float32)
    gx = cv2.Sobel(s, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(s, cv2.CV_32F, 0, 1, ksize=3)
    return float(np.mean(gx * gx + gy * gy))


def temporal_noise(a, b):
    """Per-pixel std estimate from two consecutive grey frames (includes any scene motion)."""
    return float(np.std(a.astype(np.int16) - b.astype(np.int16)) / math.sqrt(2))


def dist(values):
    if not values:
        return None
    v = np.asarray(values, float)
    return {"n": len(v), "min": float(v.min()), "p50": float(np.median(v)),
            "p95": float(np.percentile(v, 95)), "max": float(v.max()), "mean": float(v.mean())}


def interval_summary(times, fps):
    """Unique-frame intervals: rate, spread and the share within 1.5x the median (stability)."""
    if len(times) < 3:
        return {"unique_fps": None}
    iv = np.diff(np.asarray(times)) * 1000
    med = float(np.median(iv))
    return {"unique_fps": (len(times) - 1) / (times[-1] - times[0]),
            "interval_ms": {"p50": med, "p95": float(np.percentile(iv, 95)), "max": float(iv.max()),
                            "std": float(iv.std())},
            "stable_fraction": float(np.mean(iv <= 1.5 * med)),
            "gaps_vs_requested": int(np.sum(iv > 1500 / fps)) if fps else None}


def parse_exposure(text, cfg):
    return dict(cfg["camera_profile"]["exposure"]) if text == "profile" else exposure_override(text)


# ----------------------------------------------------------------------------- modes


def probe_mode(backend, size, fourcc, exposure, seconds, index, fps, out):
    cam = OpenCvCamera()
    w, h = size
    row = {"backend": backend, "requested": {"width": w, "height": h, "fps": fps, "fourcc": fourcc,
                                             "exposure": exposure}}
    try:
        neg = cam.open(CameraOpenSpec(index=index, backend=backend, width=w, height=h, fps=fps,
                                      pixel_format=fourcc, exposure_mode=exposure["mode"],
                                      exposure_value=exposure["value"]))
        for _ in range(10):
            cam.read()
        cam.apply_exposure(exposure["mode"], exposure["value"])  # MSMF honours it only once streaming
        for _ in range(10):
            cam.read()
        shapes, unique_t, lum, noise, det = set(), [], [], [], []
        reads = 0
        prev = prev_g = best = None
        cpu0, t0 = process_cpu_seconds(), now()
        while now() - t0 < seconds:
            raw = cam.read()
            if raw is None:
                continue
            reads += 1
            shapes.add((raw.image.shape[1], raw.image.shape[0]))
            if prev is not None and np.array_equal(prev, raw.image):
                continue
            prev = raw.image
            unique_t.append(raw.t_grab_return)
            if len(unique_t) % 3 == 0:  # keep the reader fast: metrics on every third unique frame
                g = gray(raw.image)
                lum.append(float(g.mean()))
                det.append(detail(g))
                if prev_g is not None and prev_g.shape == g.shape:
                    noise.append(temporal_noise(prev_g, g))
                prev_g, best = g, raw.image
        wall = now() - t0
        cpu = process_cpu_seconds() - cpu0
        neg = cam.negotiated()
        timing = interval_summary(unique_t, fps)
        delivered = sorted(list(s) for s in shapes)
        same_size = delivered == [[w, h]]
        fast = timing["unique_fps"] is not None and timing["unique_fps"] >= 0.8 * fps
        row.update({
            "advertised": {"width": neg.width, "height": neg.height, "fourcc": neg.fourcc,
                           "fps_prop": neg.fps_prop, "exposure_prop": neg.exposure_prop,
                           "note": "driver properties, not verified"},
            "verified": {"delivered_px": delivered, "reads": reads, "unique_frames": len(unique_t),
                         "reads_per_s": reads / wall,
                         "duplicate_fraction": 1 - len(unique_t) / reads if reads else None,
                         **timing},
            "image": {"luminance": dist(lum), "temporal_noise": dist(noise), "detail": dist(det)},
            "process_cpu_percent": 100 * cpu / wall,
            "verdict": ("DELIVERED" if same_size and fast else "SLOW" if same_size
                        else f"OTHER_SIZE {delivered}" if delivered else "NO_FRAMES"),
        })
        if best is not None:
            name = f"{backend}-{w}x{h}-{fourcc or 'default'}-{exposure['mode']}{exposure['value'] or ''}.png"
            cv2.imwrite(str(out / name), best)
            row["frame_png"] = name
    except Exception as exc:  # noqa: BLE001 - a mode that does not open is a result
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["verdict"] = "OPEN_FAILED"
    finally:
        cam.close()
    return row


def cmd_modes(args, cfg, out):
    exposures = [parse_exposure(e, cfg) for e in args.exposure]
    rows = []
    for exposure in exposures:
        for backend in args.backends.split(","):
            for size in SIZES:
                for fourcc in FOURCCS:
                    row = probe_mode(backend.strip().upper(), size, fourcc, exposure, args.seconds,
                                     args.index, args.fps, out)
                    rows.append(row)
                    v = row.get("verified", {})
                    value = exposure["value"] if exposure["value"] is not None else ""
                    print(f"{row['backend']:5} {size[0]}x{size[1]} {fourcc or '-':4} "
                          f"{exposure['mode']}{value}: {row['verdict']:<22} "
                          f"unique {v.get('unique_fps') or 0:5.1f} fps, "
                          f"dup {v.get('duplicate_fraction') or 0:.2f}, "
                          f"fourcc {row.get('advertised', {}).get('fourcc')}", flush=True)
    return {"command": "modes", "rows": rows}


# ----------------------------------------------------------------------------- compare


def display_image(track, hires):
    """What the full-kit window shows before overlays (ui.stage: flip, then 1.5x or the native window)."""
    if hires is None:
        small = cv2.flip(track, 1)
        size = (round(small.shape[1] * STAGE_SCALE), round(small.shape[0] * STAGE_SCALE))
        return cv2.resize(small, size, interpolation=cv2.INTER_LINEAR)
    return cv2.flip(hires, 1)


def make_perception(kind, cfg):
    if kind == "hands":
        from spacedrums.app.main import Perception

        return Perception(cfg)
    if kind == "red-tips":
        from spacedrums.app.red_tip_perception import RedTipPerception

        return RedTipPerception(cfg)
    return None


def run_arm(cfg, arm, seconds, settle, perception_kind="none"):
    src = LiveFrameSource(OpenCvCamera(), CaptureSettings.from_config(cfg))
    rec = {"arm": arm, "error": None, "perception": perception_kind}
    lags, lum, noise, det_track, det_disp, disp_ms, times, perc_ms = [], [], [], [], [], [], [], []
    present = []
    perception = None
    last = {}
    prev_g = None
    try:
        perception = make_perception(perception_kind, cfg)
        open_t = now()
        rec["negotiated"] = src.start().to_dict()
        rec["open_s"] = now() - open_t
        t0 = now()
        cpu0, wall0 = None, None
        n = 0
        while now() - t0 < settle + seconds:
            s = src.next_frame(timeout=0.5)
            if s is None:
                continue
            view = src.view(s)
            hires = src.preview_image(s)
            if perception is not None:  # the app's per-frame tracking work, on the tracking frame
                p0 = now()
                obs = perception(view)
                if now() - t0 >= settle:
                    perc_ms.append((now() - p0) * 1000)
                    present.append(sum(o.present for o, _ in obs.values()))
            d0 = now()
            disp = display_image(view.full, hires)
            if now() - t0 < settle:
                continue
            if cpu0 is None:
                cpu0, wall0 = process_cpu_seconds(), now()
            disp_ms.append((now() - d0) * 1000)
            times.append(s.t_capture)
            lags.append((s.t_frame_available - s.t_capture) * 1000)
            n += 1
            if n % 3 == 0:
                g = gray(view.full)
                lum.append(float(g.mean()))
                det_track.append(detail(g))
                det_disp.append(detail(gray(disp)))
                if prev_g is not None:
                    noise.append(temporal_noise(prev_g, g))
                prev_g = g
                last = {"track": view.full.copy(), "display": disp}
        wall = now() - wall0 if wall0 else None
        cpu = process_cpu_seconds() - cpu0 if cpu0 is not None else None
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {exc}"
        wall = cpu = None
    finally:
        src.stop()
        if perception is not None:
            perception.close()
    stats = src.stats().to_dict()
    ts = src.timestamp_report()
    rec.update({
        "capture_mode": src.capture_report(),
        "delivered": interval_summary(times, cfg["camera_profile"]["requested_fps"]),
        "capture_stats": stats,
        "raw_reads": ts["raw_frames_read"],
        "capture_thread_cpu_fraction": ts["capture_thread_cpu_fraction"],
        "process_cpu_percent": 100 * cpu / wall if cpu is not None and wall else None,
        "hand_over_lag_ms": dist(lags),
        "display_prep_ms": dist(disp_ms),
        "perception_ms": dist(perc_ms),
        "hands_present_per_frame": float(np.mean(present)) if present else None,
        "tracking_image": {"px": list(last["track"].shape[1::-1]) if last else None,
                           "luminance": dist(lum), "temporal_noise": dist(noise), "detail": dist(det_track)},
        "display_image": {"px": list(last["display"].shape[1::-1]) if last else None,
                          "detail": dist(det_disp)},
    })
    return rec, last


def fov_registration(a, b):
    """ECC affine from tracking frame ``a`` to ``b`` (identity = same field of view)."""
    try:
        warp = np.eye(2, 3, dtype=np.float32)
        ga = cv2.GaussianBlur(gray(a), (5, 5), 0).astype(np.float32)
        gb = cv2.GaussianBlur(gray(b), (5, 5), 0).astype(np.float32)
        crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-6)
        cc, warp = cv2.findTransformECC(ga, gb, warp, cv2.MOTION_AFFINE, crit, None, 5)
        return {"ecc": float(cc), "scale_x": float(warp[0, 0]), "scale_y": float(warp[1, 1]),
                "dx_px": float(warp[0, 2]), "dy_px": float(warp[1, 2]),
                "note": "tracking-frame pixels; static scene required; dx/dy ~0 and scale ~1 = same view"}
    except cv2.error as exc:
        return {"error": str(exc)}


def cmd_compare(args, out):
    exposure = None if args.exposure[0] == "profile" else exposure_override(args.exposure[0])
    red = args.perception == "red-tips"
    cfgs = {arm: play_config(camera=arm, exposure=exposure, red_tips=red) for arm in ("standard", "native")}
    runs, frames = [], {}
    for r in range(args.repeats):
        for arm in ("standard", "native") if r % 2 == 0 else ("native", "standard"):
            rec, last = run_arm(cfgs[arm], arm, args.seconds, args.settle, args.perception)
            rec["repeat"] = r
            runs.append(rec)
            if last:
                frames[arm] = last
                cv2.imwrite(str(out / f"{arm}-r{r}-tracking.png"), last["track"])
                cv2.imwrite(str(out / f"{arm}-r{r}-display.png"), last["display"])
            d, c, lag = rec["delivered"], rec["capture_mode"], rec["hand_over_lag_ms"] or {}
            print(f"r{r} {arm:8} mode {c.get('mode')}: {d.get('unique_fps') or 0:5.2f} fps, drops "
                  f"{rec['capture_stats']['dropped']}, dup {rec['capture_stats']['duplicates']}, lag p50 "
                  f"{lag.get('p50', 0):.1f} ms, cpu {rec['process_cpu_percent'] or 0:.1f} %"
                  f"{', error ' + rec['error'] if rec['error'] else ''}", flush=True)
    report = {"command": "compare", "exposure": cfgs["native"]["camera_profile"]["exposure"],
              "perception": args.perception, "runs": runs}
    if len(frames) == 2:
        report["fov_registration_standard_to_native"] = fov_registration(frames["standard"]["track"],
                                                                         frames["native"]["track"])
        s, n = frames["standard"]["display"], frames["native"]["display"]
        if s.shape == n.shape:
            side = np.hstack([s, np.full((s.shape[0], 8, 3), 255, np.uint8), n])
            cv2.imwrite(str(out / "display-standard-vs-native.png"), side)
    return report


def run_exposure(cfg, label, seconds, settle, perception_kind, out):
    """One exposure setting on the app's capture path, guard off: what the camera really does."""
    from spacedrums.ui.preview_tone import PreviewSettings, PreviewTone

    cfg["camera_profile"]["exposure"].pop("guard", None)
    src = LiveFrameSource(OpenCvCamera(), CaptureSettings.from_config(cfg))
    tone = PreviewTone(PreviewSettings.from_config(cfg["product"].get("preview")).preset("natural"))
    rec = {"setting": label, "requested": dict(cfg["camera_profile"]["exposure"]), "error": None}
    times, lum, p1, p99, sat, noise, toned, perc_ms, present = [], [], [], [], [], [], [], [], []
    perception, prev_g, last = None, None, None
    try:
        perception = make_perception(perception_kind, cfg)
        rec["capture_mode"] = src.start().to_dict() and src.capture_report().get("mode")
        t0 = now()
        while now() - t0 < settle + seconds:
            s = src.next_frame(timeout=0.5)
            if s is None:
                continue
            view = src.view(s)
            hires = src.preview_image(s)
            shown = tone(hires if hires is not None else view.full)  # tone state follows every frame
            if perception is not None:
                p0 = now()
                obs = perception(view)
                if now() - t0 >= settle:
                    perc_ms.append((now() - p0) * 1000)
                    present.append(sum(o.present for o, _ in obs.values()))
            if now() - t0 < settle:
                continue
            times.append(s.t_capture)
            if len(times) % 3 == 0:
                g = gray(view.full)
                lum.append(float(g.mean()))
                p1.append(float(np.percentile(g[::4, ::4], 1)))
                p99.append(float(np.percentile(g[::4, ::4], 99)))
                sat.append(float(cv2.cvtColor(view.full[::4, ::4], cv2.COLOR_BGR2HSV)[..., 1].mean()))
                toned.append(float(gray(shown[::4, ::4]).mean()))
                if prev_g is not None:
                    noise.append(temporal_noise(prev_g, g))
                prev_g, last = g, (view.full.copy(), shown.copy())
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        rec["readback_after"] = {k: src.camera.get_prop("CAP_PROP_" + k)
                                 for k in ("AUTO_EXPOSURE", "EXPOSURE", "GAIN")} if src.camera._cap else None
        src.stop()
        if perception is not None:
            perception.close()
    value = rec["requested"]["value"]
    rec.update({
        "exposure_ms_requested": 1000 * 2.0 ** value if value is not None else None,
        "delivered": interval_summary(times, 30.0),
        "capture_stats": src.stats().to_dict(),
        "exposure_report": src.capture_report()["exposure"],
        "tracking_image": {"luminance": dist(lum), "p1": dist(p1), "p99": dist(p99), "saturation": dist(sat),
                           "temporal_noise": dist(noise)},
        "preview_natural": {"luminance": dist(toned), **tone.report()},
        "perception_ms": dist(perc_ms),
        "hands_present_per_frame": float(np.mean(present)) if present else None,
    })
    if last is not None:
        cv2.imwrite(str(out / f"{label}-tracking.png"), last[0])
        cv2.imwrite(str(out / f"{label}-preview-natural.png"), cv2.flip(last[1], 1))
    return rec


def cmd_exposure(args, out):
    """AUTO and fixed exposures on the same path, forward then reverse order (room-light drift)."""
    default = ["auto", "-7", "-6", "-5", "-4.5", "-4", "-3"]
    settings = args.exposure if args.exposure != ["profile"] else default
    order = settings + settings[::-1] if args.repeats > 1 else settings
    red = args.perception == "red-tips"
    runs = []
    for i, label in enumerate(order):
        cfg = play_config(camera=args.camera, exposure=exposure_override(label), red_tips=red)
        rec = run_exposure(cfg, f"{i:02d}_{label}", args.seconds, args.settle, args.perception, out)
        runs.append(rec)
        d, t, pv = rec["delivered"], rec["tracking_image"], rec["preview_natural"]
        iv = d.get("interval_ms") or {}

        def p50(block):
            return (block or {}).get("p50", 0)

        print(f"{label:>5}: {d.get('unique_fps') or 0:5.2f} fps, p50/p95 {iv.get('p50', 0):5.1f}/"
              f"{iv.get('p95', 0):5.1f} ms, lum {p50(t['luminance']):5.1f}, "
              f"noise {p50(t['temporal_noise']):4.2f}, "
              f"preview {p50(pv['luminance']):5.1f} (gamma {(pv.get('gamma') or {}).get('p50', 1):.2f})"
              f"{', error ' + rec['error'] if rec['error'] else ''}", flush=True)
    return {"command": "exposure", "camera": args.camera, "perception": args.perception,
            "settle_s": args.settle, "runs": runs}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=("modes", "compare", "exposure"))
    p.add_argument("--camera", choices=("native", "standard"), default="native",
                   help="exposure: capture path")
    p.add_argument("--output", type=Path,
                   help="new directory (default experiments/camera-quality-<time>-<command>)")
    p.add_argument("--exposure", action="append",
                   help="profile (default: the play configuration's exposure), auto, or a value such as -5; "
                        "modes accepts it repeatedly")
    p.add_argument("--seconds", type=float, default=None, help="measured seconds per mode (4) / per arm (10)")
    p.add_argument("--backends", default="DSHOW,MSMF")
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--fps", type=float, default=30.0)
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--settle", type=float, default=1.0)
    p.add_argument("--perception", choices=("none", "hands", "red-tips"), default="none",
                   help="compare: also run the app's tracking on every frame (processed FPS under load)")
    args = p.parse_args(argv)
    args.exposure = args.exposure or ["profile"]
    if args.seconds is None:
        args.seconds = {"modes": 4.0, "compare": 10.0, "exposure": 8.0}[args.command]
    if args.command == "exposure" and args.settle == 1.0:
        args.settle = 6.0  # AUTO exposure and white balance converge after every open
    out = args.output or ROOT / "experiments" / f"camera-quality-{wall_clock_local_compact()}-{args.command}"
    out.mkdir(parents=True, exist_ok=False)
    cv2.setNumThreads(1)  # as app.play
    cfg = play_config()
    run = {"modes": lambda: cmd_modes(args, cfg, out), "compare": lambda: cmd_compare(args, out),
           "exposure": lambda: cmd_exposure(args, out)}
    report = run[args.command]()
    report.update({"opencv": cv2.__version__, "participant_evidence": False, "argv": sys.argv[1:],
                   "limitations": ["Development evidence on one camera, one room, one session.",
                                   "Image metrics depend on the scene; compare arms of the same run only.",
                                   "Hand-over lag is t_frame_available - t_capture; t_capture is the DSHOW "
                                   "grab return, so camera/USB/decode latency before it is not measured "
                                   "here."]})
    (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(out / "report.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
