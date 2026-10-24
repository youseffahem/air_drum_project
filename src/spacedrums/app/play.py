"""Standing four-pad product candidate. Run: python -m spacedrums.app.play

Automatically calibrates each launch. R retries, Esc/Q closes. Developer logs
are saved locally; raw camera images are saved only with --record-frames.
Explicit --demo selects an uncalibrated fixed guide and a diagnostic camera view.
--red-tips tracks red painted stick tips by colour (a MARKER condition); --fingers
plays with index fingertips; neither flag keeps the visible-stick estimator.
--check verifies assets without opening the camera or an audio stream.
No participant protocol, lock or gate is opened by this entry point.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from spacedrums.app.audio_out import AudioOutput, OutputLatency
from spacedrums.app.main import Perception
from spacedrums.app.pipeline import DecisionPipeline
from spacedrums.app.red_tip_perception import RedTipPerception
from spacedrums.calib.automatic import AutomaticCalibration
from spacedrums.calib.developer_demo import DeveloperDemoLayout, check_kit_pads
from spacedrums.calib.reach import ReachSettings
from spacedrums.capture import (
    CaptureSettings,
    LiveFrameSource,
    OpenCvCamera,
    ReplayFrameSource,
    Roi,
    crop_roi,
)
from spacedrums.config import config_hash, load_config, load_yaml, validate
from spacedrums.contracts import Arm, FrameView, ImageRef
from spacedrums.contracts.schema import validator
from spacedrums.geometry import ZoneRegistry
from spacedrums.geometry.kit_layout import load_pads
from spacedrums.hands.body import BodyLandmarker
from spacedrums.timing import now, process_cpu_seconds, wall_clock_iso
from spacedrums.ui.developer_demo import DemoOverlay
from spacedrums.ui.kit import render_kit
from spacedrums.ui.layout_preview import LayoutPreview
from spacedrums.ui.preview_tone import PRESETS, PreviewSettings, PreviewTone
from spacedrums.ui.stage import DIM, StageRenderer

ROOT = Path(__file__).resolve().parents[3]


def distribution(values):
    return (
        dict(zip(("p50", "p95", "max"), map(float, np.percentile(values, [50, 95, 100])), strict=True))
        if values
        else None
    )


def stick_tip_override(path):
    """A tuned ``product: stick_tip:`` fragment (scripts/analyze_red_tips.py); nothing else may change."""
    doc = load_yaml(path)
    if not isinstance(doc, dict) or set(doc) != {"product"} or not isinstance(doc["product"], dict) \
            or set(doc["product"]) != {"stick_tip"}:
        raise ValueError(f"{path}: a stick-tip override contains only product: stick_tip: ...")
    return Path(path)


def exposure_override(text):
    """``--exposure``: ``auto`` or a backend exposure value (DirectShow log2 seconds, e.g. -5)."""
    if text.strip().lower() == "auto":
        return {"mode": "AUTO", "value": None}
    return {"mode": "MANUAL", "value": float(text)}


def display_roi(roi, scale):
    """The tracking ROI in the pixels of a display image ``scale`` times larger."""
    if scale == 1.0:
        return roi
    return Roi(round(roi.x * scale), round(roi.y * scale), round(roi.w * scale), round(roi.h * scale))


def toned_view(view, tone):
    """The tracking view through ``tone`` (opt-in ``--tracking-tone``); the recorded frame stays raw."""
    full = tone(view.full)
    if full is view.full:
        return view
    return FrameView(sample=view.sample, roi=crop_roi(full, Roi.from_rect(view.sample.roi_px)), full=full)


def play_config(*, demo=False, delegate="CPU", kit="four", exclusive=False, kit_layout=None, red_tips=False,
                stick_tip=None, hand_assist=False, camera="standard", exposure=None):
    """``camera="native"`` merges the native-capture fragment (ADR-0047); "standard" keeps the
    configuration byte-identical to the one before it existed. ``exposure`` overrides the profile."""
    if camera not in ("native", "standard"):
        raise ValueError(f"camera must be 'native' or 'standard', not {camera!r}")
    paths = [ROOT / "configs/prototype.candidate.yaml", ROOT / "configs/product.candidate.yaml"]
    if demo:
        paths.append(ROOT / "configs/demo.professor.candidate.yaml")
        if kit == "full":
            paths.append(ROOT / "configs/demo.fullkit.candidate.yaml")
    if red_tips:  # painted-tip MARKER mode only: fingertip and visible-stick configs stay byte-identical
        paths.append(ROOT / "configs/red-tip.candidate.yaml")
        if stick_tip is not None:
            paths.append(stick_tip_override(stick_tip))
    elif stick_tip is not None or hand_assist:
        raise ValueError("stick-tip settings and hand assist apply to --red-tips only")
    if camera == "native":
        paths.append(ROOT / "configs/camera/hw01-native-720p.candidate.yaml")
    cfg = load_config(*paths).data
    if exposure is not None:
        cfg["camera_profile"]["exposure"] = {**cfg["camera_profile"]["exposure"], **exposure}  # keeps a guard
    if hand_assist:
        cfg["product"]["stick_tip"]["hand_assist"] = True
    cfg["hands"]["delegate"] = delegate
    if demo and kit_layout is not None:  # a layout saved by --layout-preview replaces the configured pads
        cfg["product"]["developer_demo"]["pads"] = load_pads(kit_layout)
        cfg["product"]["developer_demo"]["source"] = str(kit_layout)
    if demo:
        cfg["zones"] = DeveloperDemoLayout(cfg).zones
    cfg["audio"]["wasapi_exclusive"] = bool(exclusive)
    cfg["audio"]["sample_bank"]["path"] = str(ROOT / "assets/samples")
    # The full-kit demo plays the acoustic Salamander bank; every other mode keeps the TR-505 bank.
    bank = "acoustic-manifest.json" if demo and kit == "full" else "recorded-manifest.json"
    cfg["audio"]["sample_bank"]["manifest"] = str(ROOT / "assets/samples" / bank)
    validate(cfg)
    return cfg


def missing_samples(cfg):
    """Sample files named by the manifest that are not on disk (the WAV binaries are git-ignored)."""
    manifest = Path(cfg["audio"]["sample_bank"]["manifest"])
    root = Path(cfg["audio"]["sample_bank"]["path"])
    files = [e["file"] for e in json.loads(manifest.read_text(encoding="utf-8"))["samples"]]
    return [f for f in files if not (root / f).exists()]


def require_samples(cfg):
    missing = missing_samples(cfg)
    if missing:
        script = ("fetch_acoustic_samples.py" if "acoustic" in cfg["audio"]["sample_bank"]["manifest"]
                  else "fetch_drum_samples.py")
        raise FileNotFoundError(
            f"{len(missing)} sample file(s) missing, e.g. {missing[0]}; run: python scripts/{script}")


def check_assets(cfg):
    """No camera, window, sound stream or fabricated strike is opened by preflight."""
    from spacedrums.audio import SampleBank
    from spacedrums.hands.model_asset import resolve_model_asset

    require_samples(cfg)
    asset = resolve_model_asset(cfg["hands"]["model_asset_id"])
    bank = SampleBank.load(**{
        "root": cfg["audio"]["sample_bank"]["path"],
        "manifest": cfg["audio"]["sample_bank"]["manifest"],
        "sample_rate_hz": cfg["audio"]["sample_rate_hz"],
    })
    for zone in cfg["zones"]:
        bank[zone["sample_id"]]
    return {"assets": "HASH_VERIFIED", "hands_sha256": asset.sha256,
            "samples": [z["sample_id"] for z in cfg["zones"]],
            "camera_opened": False, "audio_opened": False, "live_verified": False}


def run(args):
    cv2.setNumThreads(1)
    cfg = play_config(demo=args.demo, delegate=args.delegate, kit=args.kit, exclusive=args.exclusive_audio,
                      kit_layout=args.kit_layout, red_tips=args.red_tips, stick_tip=args.stick_tip_config,
                      hand_assist=args.hand_assist, camera=args.camera, exposure=args.exposure)
    preview_settings = PreviewSettings.from_config(cfg["product"].get("preview")).preset(args.preview)
    cfg["product"]["preview"] = preview_settings.to_dict()  # the record shows what the window used
    if args.check:
        print(json.dumps(check_assets(cfg), indent=2))
        return 0
    if not (args.no_audio or args.replay):
        require_samples(cfg)
    replay = ReplayFrameSource(args.replay, limit=args.max_frames) if args.replay else None
    if args.recorded_roi:
        if replay is None or replay.roi is None:
            raise ValueError("--recorded-roi requires a nonempty replay")
        cfg["roi"]["px"] = list(replay.roi.as_tuple())
    validate(cfg)
    roi = Roi.from_rect(cfg["roi"]["px"])
    session = datetime.fromisoformat(wall_clock_iso()).strftime("dev-product-%Y%m%d-%H%M%S")
    session += f"-{uuid4().hex[:8]}"
    directory = args.output or ROOT / "data/dev-product" / session
    directory.mkdir(parents=True, exist_ok=False)
    provenance = "DEVELOPER_REPLAY" if args.replay else "DEVELOPER_LIVE"
    reach_settings = ReachSettings(**cfg["product"].get("reach", {}))
    calibration = (DeveloperDemoLayout(cfg) if args.demo else
                   AutomaticCalibration((roi.w, roi.h), settings=reach_settings, provenance=provenance))
    source = perception = pose = audio = None
    pipeline = None
    metrics = defaultdict(list)
    records = frame_records = None
    attempts = []
    error = None
    delivered = dropped = commits = 0
    body = None
    last_pose = -float("inf")
    start, cpu_start = now(), process_cpu_seconds()
    last_status = start
    stage_times = defaultdict(list)
    source_report = {}
    counts = Counter()
    endpoint_reasons = Counter()
    demo_overlay = DemoOverlay() if args.demo and not args.no_window else None
    legacy_dim = preview_settings.dim is None  # each view's previous darkening
    stage_view = None
    if args.demo and not args.no_window and args.kit == "full":
        stage_view = StageRenderer(dim=DIM if legacy_dim else preview_settings.dim,
                                   vignette=preview_settings.vignette)
    kit_dim = {"dim": 0.60, "lift": 4} if legacy_dim else {"dim": preview_settings.dim, "lift": 0}
    tone = PreviewTone(preview_settings)  # display pixels only; never the tracking frame
    # Opt-in, HAND/fingertip/visible-stick only (ADR-0048): the same auto gamma on the frame the hand model
    # sees. Off by default; recordings keep the raw frame, so a replay with the flag reproduces it.
    tracking_tone = PreviewTone(PreviewSettings.from_config(cfg["product"].get("preview")).preset("natural")
                                ) if args.tracking_tone == "auto" else None
    show_diagnostics = False
    registry = None
    preview = None
    if args.layout_preview and stage_view is not None:
        preview = LayoutPreview(
            cfg["product"]["developer_demo"]["pads"],
            lambda pads: check_kit_pads(pads, (roi.w, roi.h), reach_settings),
            save_dir=directory,
        )

    def build_pipeline():
        nonlocal pipeline, registry
        cfg["zones"] = calibration.zones
        validate(cfg)
        registry = ZoneRegistry.from_config(cfg["zones"])
        pipeline = DecisionPipeline(
            cfg, registry=registry, session_id=session, active_arm=Arm.A,
            hardware_id="developer-host", config_hash=config_hash(cfg), audio=audio,
            developer_demo=args.demo,
        )

    def start_pipeline():
        nonlocal audio
        audio = AudioOutput(cfg, latency=OutputLatency.unmeasured(),
                            device_enabled=not args.no_audio and not args.replay)
        audio.start()
        build_pipeline()

    if args.record_frames:
        (directory / "frames").mkdir()
    try:
        if args.red_tips:
            perception = RedTipPerception(cfg)
        else:
            perception = Perception(cfg)
        if args.fingers:
            from spacedrums.stick.visible import FingertipEndpointEstimator

            perception.estimator = FingertipEndpointEstimator(perception.stick_settings)
        if not args.demo:
            pose = BodyLandmarker(cfg["product"]["pose_asset_id"])
        if args.replay:
            source = replay
            samples = iter(source)
            if source.roi != roi:
                raise ValueError(
                    "replay ROI differs from product configuration; use --recorded-roi to retain it"
                )
        else:
            source = LiveFrameSource(OpenCvCamera(), CaptureSettings.from_config(cfg))
            mode = source.start()
            source_report["negotiated"] = vars(mode)
            capture_mode = source.capture_report()
            source_report["capture_mode"] = capture_mode
            if capture_mode["mode"] == "STANDARD_FALLBACK":
                print(json.dumps({"camera": "native mode not delivered; using the standard mode",
                                  "reason": capture_mode["rejected"]}), flush=True)

            def live_samples():
                last_frame = now()
                while not args.max_seconds or now() - start < args.max_seconds:
                    sample = source.next_frame(timeout=0.2)
                    if sample is not None:
                        last_frame = now()
                        yield sample
                    elif now() - last_frame > 5:
                        raise RuntimeError("Camera stopped delivering frames")
                    elif not args.no_window and cv2.pollKey() & 0xFF in (27, ord("q")):
                        return

            samples = live_samples()
        if not args.no_window:
            cv2.namedWindow("Space Drums", cv2.WINDOW_NORMAL)
            cv2.resizeWindow("Space Drums", 960, 720)
        records = (directory / "observations.jsonl").open("w", encoding="utf-8")
        if args.record_frames:
            frame_records = (directory / "frames.jsonl").open("w", encoding="utf-8")
        if args.demo:
            start_pipeline()
        for sample in samples:
            begin = now()
            if args.max_seconds and begin - start >= args.max_seconds:
                break
            if args.max_frames and delivered >= args.max_frames:
                break
            delivered += 1
            stage_times[calibration.state].append(sample.t_capture)
            dropped += sample.dropped_since_last
            view = source.view(sample)
            recording_started = now()
            if args.record_frames:
                relative = f"frames/frame_{sample.frame_id:06d}.png"
                if view.full is None or not cv2.imwrite(str(directory / relative), view.full):
                    raise OSError("Could not save full camera frame")
                saved = replace(sample, image_ref=ImageRef.file(relative, sample.frame_id, "FULL"))
                frame_records.write(json.dumps(saved.to_dict()) + "\n")
                metrics["frame_recording_ms"].append((now() - recording_started) * 1000)
            perception_started = now()
            observations = perception(toned_view(view, tracking_tone) if tracking_tone else view)
            evidence = perception.estimator.evidence
            tips = perception.estimator.frame if args.red_tips else None
            endpoint_reasons.update(e.reason for e in evidence.values())
            metrics["hand_inference_ms"].append(perception.last_hands.processing_s * 1000)
            metrics["perception_ms"].append((now() - perception_started) * 1000)
            if tips is not None:
                metrics["red_tip_ms"].append(tips.ms)
            if calibration.state == "STAND" and sample.t_capture - last_pose >= 0.2:
                body = pose.detect(view)
                last_pose = sample.t_capture
                metrics["pose_inference_ms"].append(pose.processing_s * 1000)
            stage = now()
            result = None
            if pipeline is not None:
                decision_time = None if not args.replay else sample.t_frame_available + (now() - begin)
                for hand in tips.resets if tips is not None else ():
                    pipeline.reset_hand(hand)  # a new or possibly swapped tip identity restarts its strokes
                result = pipeline.step(
                    sample,
                    observations,
                    t_now=decision_time,
                    processing_started=begin,
                    endpoint_evidence=evidence,
                )
                commits += len(result.commits)
                counts.update(c.zone_id for c in result.commits)
                for rec in result.timing:
                    if rec.t_audio_scheduled is not None and not args.replay:
                        metrics["audio_schedule_ms"].append((rec.t_audio_scheduled - rec.t_commit) * 1000)
                        metrics["capture_to_schedule_ms"].append(
                            (rec.t_audio_scheduled - sample.t_capture) * 1000)
                if audio is not None:
                    audio.check_health(now())
            metrics["decision_ms"].append((now() - stage) * 1000)
            if preview is not None:
                preview.observe(evidence, result)
            # Replay decisions use capture time as their clock for calibration matching.
            cal_commits = result.commits if result is not None else ()
            calibration.update(sample.t_capture, evidence, body, cal_commits)
            if calibration.state == "VERIFY" and pipeline is None:
                start_pipeline()
            if calibration.state == "RETRY" and pipeline is not None:
                pipeline = None
                audio.stop()
                audio = None
            if not args.replay:
                metrics["queue_age_ms"].append(max(0, begin - sample.t_frame_available) * 1000)
                metrics["capture_to_decision_ms"].append((now() - sample.t_capture) * 1000)
            metrics["capture_t"].append(sample.t_capture)
            records.write(
                json.dumps(
                    {
                        "frame": sample.to_dict(),
                        "state": calibration.state,
                        "body_reference": body.to_dict() if body else None,
                        "hands": [o.to_dict() for o, s in observations.values()],
                        "endpoints": [e.to_dict() for e in evidence.values()],
                        "sticks": [s.to_dict() for o, s in observations.values()],
                        **({"red_tip": tips.to_record()} if tips is not None else {}),
                        "commits": [c.to_dict() for c in cal_commits],
                        "audio_events": [e.to_dict() for e in result.audio] if result else [],
                        "audio_device_state": audio.device_state if audio else "NOT_STARTED",
                        "timing": [r.to_dict() for r in result.timing] if result else [],
                        "decisions": {
                            str(h): {"track": hf.track.to_dict(),
                                     "candidates": [c.to_dict() for c in hf.candidates],
                                     "gates": hf.decision_traces,
                                     "stroke": pipeline.geometry.diagnostics.get(h)}
                            for h, hf in result.hands.items()
                        } if result else {},
                    },
                    allow_nan=False,
                )
                + "\n"
            )
            if not args.no_window:
                render_started = now()
                zones = calibration.zones or calibration.guide_zones
                display_registry = registry or (ZoneRegistry.from_config(zones) if zones else None)
                # Native capture: the same field of view at full sensor detail, for display only.
                hires = source.preview_image(sample) if isinstance(source, LiveFrameSource) else None
                scale = hires.shape[1] / view.full.shape[1] if hires is not None else 1.0
                shown, shown_roi = (hires, display_roi(roi, scale)) if hires is not None else (view.full, roi)
                tone_started = now()
                shown = tone(shown)  # a new array; the camera and tracking frames are untouched
                metrics["preview_tone_ms"].append((now() - tone_started) * 1000)
                img = stage_view.render(
                    view.full if hires is not None else shown, roi, registry, evidence, result, audio=audio,
                    latency_ms=(metrics["capture_to_schedule_ms"] or [None])[-1],
                    preview=shown if hires is not None else None,
                ) if stage_view and not show_diagnostics else demo_overlay.render(
                    shown, shown_roi, registry, evidence, result, dropped=dropped,
                    perception_ms=metrics["perception_ms"][-1], audio_state=audio.device_state,
                    stroke_diagnostics=pipeline.geometry.diagnostics, tip_diagnostics=tips, px_scale=scale,
                ) if demo_overlay else render_kit(
                    shown,
                    shown_roi,
                    display_registry,
                    sticks=[s for o, s in observations.values()],
                    body=calibration.body,
                    message=calibration.message,
                    target=calibration.target,
                    **kit_dim,
                )
                if args.developer and not args.demo:
                    cv2.putText(
                        img,
                        f"DEV {calibration.state} tips {sum(s.present for o, s in observations.values())}",
                        (12, 67),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.4,
                        (255, 210, 120),
                        1,
                    )
                if preview is not None and not show_diagnostics:
                    preview.draw(img, stage_view, roi, view.full.shape[1])
                metrics["render_ms"].append((now() - render_started) * 1000)
                shown_at = now()
                cv2.imshow("Space Drums", img)
                polled_at = now()
                metrics["imshow_ms"].append((polled_at - shown_at) * 1000)
                key = cv2.pollKey() & 0xFF
                metrics["pollkey_ms"].append((now() - polled_at) * 1000)
                if key in (27, ord("q")):
                    break
                if preview is not None:
                    moved = preview.handle_key(key)
                    if moved is not None:
                        # Only zones, registry and decision state change; the audio stream keeps running.
                        cfg["product"]["developer_demo"]["pads"] = moved
                        calibration = DeveloperDemoLayout(cfg)
                        build_pipeline()
                if key == ord("d") and stage_view:
                    show_diagnostics = not show_diagnostics
                if key == ord("r") and not args.demo:
                    attempts.append(calibration.report())
                    calibration = AutomaticCalibration(
                        (roi.w, roi.h), settings=reach_settings, provenance=provenance
                    )
                    perception.estimator.reset()
                    pipeline = None
                    registry = None
                    body = None
                    if audio:
                        audio.stop()
                        audio = None
            metrics["frame_work_ms"].append((now() - begin) * 1000)
            if now() - last_status >= 5:
                records.flush()
                if frame_records:
                    frame_records.flush()
                if args.developer or args.demo:
                    print(
                        json.dumps(
                            {
                                "state": calibration.state,
                                "message": calibration.message,
                                "frames": delivered,
                                "measured_tips": sum(e.kind == "MEASURED" for e in evidence.values()),
                                "commits_by_drum": dict(counts),
                                "audio": audio.device_state if audio else "NOT_STARTED",
                                "dropped": dropped,
                                **({"red_tip": {str(h): st.state for h, st in tips.slots.items()}}
                                   if tips is not None else {}),
                            }
                        ),
                        flush=True,
                    )
                last_status = now()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if records:
            records.close()
        if frame_records:
            frame_records.close()
        if isinstance(source, LiveFrameSource):
            source.stop()
            source_report.update(
                capture=source.stats().to_dict(),
                queue=source.queue_report(),
                timestamps=source.timestamp_report(),
                capture_mode=source.capture_report(),
            )
        audio_stats = audio.stats() if audio else None
        if audio:
            audio.stop()
        if perception:
            perception.close()
        if pose:
            pose.close()
        if not args.no_window:
            cv2.destroyAllWindows()
    elapsed = now() - start
    cpu_s = process_cpu_seconds() - cpu_start
    times = metrics.pop("capture_t", [])
    fps = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 else None
    capture_timing = source_report.get("timestamps", {})
    capture_wall = capture_timing.get("capture_thread_wall_s", 0)
    try:
        gpu = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used", "--format=csv"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        gpu = None
    hand_model = not args.red_tips or bool(cfg["product"]["stick_tip"]["hand_assist"])
    report = {
        "schema_version": "1.0",
        "provenance": provenance,
        "session_id": session,
        "participant_evidence": False,
        "record_frames": bool(args.record_frames),
        "error": error,
        "config": cfg,
        "config_hash": config_hash(cfg),
        "calibration": None if args.demo else {**calibration.report(), "provenance": provenance},
        "developer_demo": calibration.report() if args.demo else None,
        "live_physical_verification": "NOT_YET_VERIFIED",
        "previous_attempts": attempts,
        "delivered_frames": delivered,
        "dropped_frames": dropped,
        "commits": commits,
        "commits_by_drum": {z["zone_id"]: counts[z["zone_id"]] for z in cfg["zones"]},
        "endpoint_reasons": dict(endpoint_reasons),
        "source_timeline_fps": fps,
        "live_unique_fps": fps if not args.replay else None,
        "raw_capture_reads_per_s": capture_timing.get("raw_frames_read", 0) / capture_wall
        if capture_wall > 0
        else None,
        "stages": {
            k: {
                "frames": len(v),
                "source_timeline_fps": (len(v) - 1) / (v[-1] - v[0]) if len(v) > 1 else None,
            }
            for k, v in stage_times.items()
        },
        "compute_wall_s": elapsed,
        "process_cpu_s": cpu_s,
        "cpu_core_percent": 100 * cpu_s / elapsed,
        "gpu_snapshot": gpu,
        "latency_ms": {k: distribution(v) for k, v in metrics.items()},
        "capture": source_report,
        "preview": tone.report() if not args.no_window else None,
        "tracking_tone": tracking_tone.report() if tracking_tone else None,
        "audio": audio_stats,
        "action_to_sound_ms": None,
        "audio_output_latency_ms": None,
        "acceptance": "RUNTIME_ERROR" if error else
        "DEVELOPER_DEMO_AWAITING_PHYSICAL_VERIFICATION" if args.demo else
        "PENDING_INDEPENDENT_VALIDATION"
        if calibration.state == "READY"
        else "CALIBRATION_INCOMPLETE",
        "target_fps": 30,
        "models": {"hands": cfg["hands"]["model_asset_id"] if hand_model else None,
                   "pose": None if args.demo else cfg["product"]["pose_asset_id"]},
        "model_sha256": {
            "hands": perception.landmarker.asset.sha256 if perception and perception.landmarker else None,
            "pose": pose.asset.sha256 if pose else None,
        },
    }
    if args.red_tips:  # integrity I-7: painted tips are a coloured-marker condition, labelled as such
        report["tip_method"] = "MARKER"
        report["red_tip"] = perception.estimator.summary() if perception else None
    if not args.demo:
        validator("product-calibration").validate(report["calibration"])
    (directory / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "report": str(directory / "report.json"),
                "state": calibration.state,
                "frames": delivered,
                "error": error,
            },
            indent=2,
        )
    )
    return 1 if error else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--developer", action="store_true")
    p.add_argument("--demo", action="store_true", help="Explicit uncalibrated developer 2x2 live demo")
    p.add_argument("--check", action="store_true", help="Check config/model/samples without opening devices")
    p.add_argument("--delegate", choices=("CPU", "GPU"), default="CPU")
    p.add_argument("--no-audio", action="store_true")
    p.add_argument("--kit", choices=("full", "four"), default="full",
                   help="--demo layout: full 7-piece kit without kick (default) or the 2x2 guide")
    p.add_argument("--layout-preview", action="store_true",
                   help="--demo --kit full: show pad coordinates and your measured reach; i/k/j/l move, "
                        "[ ] scale, s saves kit-layout.yaml into the session directory")
    p.add_argument("--kit-layout", type=Path,
                   help="--demo --kit full: load pads saved by --layout-preview, not the configured kit")
    p.add_argument("--exclusive-audio", action="store_true",
                   help="WASAPI exclusive mode: ~5 ms output instead of ~22 ms, but other apps lose sound")
    p.add_argument("--fingers", action="store_true", help="Bare hands: index fingertips act as sticks")
    p.add_argument("--red-tips", action="store_true",
                   help="Sticks with red painted tips: colour tracking of both tips (a MARKER condition); "
                        "the hand model is not run unless --hand-assist")
    p.add_argument("--hand-assist", action="store_true",
                   help="--red-tips: also run the hand model to label new tips (~27 ms per frame)")
    p.add_argument("--stick-tip-config", type=Path,
                   help="--red-tips: YAML 'product: stick_tip:' fragment overriding the tip settings "
                        "(e.g. written by scripts/analyze_red_tips.py)")
    p.add_argument("--camera", choices=("native", "standard"), default="native",
                   help="native (default): capture the webcam's 1280x720 mode, track the same 640x480 "
                        "field of view and show it at full detail; falls back to standard if the mode is "
                        "not delivered. standard: the previous 640x480 capture, byte-identical config")
    p.add_argument("--preview", choices=PRESETS, default="natural",
                   help="live window only: natural (default; no darkening, gamma toward a natural "
                        "brightness), raw (camera pixels) or legacy (the previous dimmed look)")
    p.add_argument("--tracking-tone", choices=("off", "auto"), default="off",
                   help="opt-in: brighten the frames the hand model sees with the preview's auto gamma "
                        "(offline: more hands found in 6 of 7 dark recordings, fewer in 1; "
                        "not live-validated)")
    p.add_argument("--exposure", type=exposure_override, metavar="auto|VALUE",
                   help="override the camera exposure for this launch: auto, or a DirectShow log2 value "
                        "(-5 = 31 ms, the longest that keeps 30 FPS on the integrated webcam)")
    p.add_argument("--no-window", action="store_true")
    p.add_argument("--record-frames", action="store_true")
    p.add_argument("--max-seconds", type=float)
    p.add_argument("--max-frames", type=int)
    p.add_argument("--replay", type=Path)
    p.add_argument(
        "--recorded-roi", action="store_true", help="Use the recorded crop when replaying older captures"
    )
    p.add_argument("--output", type=Path)
    args = p.parse_args(argv)
    if args.demo and args.recorded_roi:
        p.error("fixed demo geometry requires its full-camera ROI; do not use --recorded-roi")
    if (args.layout_preview or args.kit_layout) and not (args.demo and args.kit == "full"):
        p.error("--layout-preview and --kit-layout need --demo with --kit full")
    if args.layout_preview and args.no_window:
        p.error("--layout-preview needs the window")
    if args.red_tips and args.fingers:
        p.error("--red-tips and --fingers are different tip modes; choose one")
    if args.tracking_tone == "auto" and args.red_tips:
        p.error("--tracking-tone auto is validated for the hand model only, "
                "not for red-tip colour thresholds")
    if (args.hand_assist or args.stick_tip_config) and not args.red_tips:
        p.error("--hand-assist and --stick-tip-config need --red-tips")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
