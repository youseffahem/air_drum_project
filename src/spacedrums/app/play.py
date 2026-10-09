"""Standing four-pad product candidate. Run: python -m spacedrums.app.play

Automatically calibrates each launch. R retries, Esc/Q closes. Developer logs
are saved locally; raw camera images are saved only with --record-frames.
Explicit --demo selects an uncalibrated fixed guide and a diagnostic camera view.
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
from spacedrums.calib.automatic import AutomaticCalibration
from spacedrums.calib.developer_demo import DeveloperDemoLayout
from spacedrums.calib.reach import ReachSettings
from spacedrums.capture import CaptureSettings, LiveFrameSource, OpenCvCamera, ReplayFrameSource, Roi
from spacedrums.config import config_hash, load_config, validate
from spacedrums.contracts import Arm, ImageRef
from spacedrums.contracts.schema import validator
from spacedrums.geometry import ZoneRegistry
from spacedrums.hands.body import BodyLandmarker
from spacedrums.timing import now, process_cpu_seconds, wall_clock_iso
from spacedrums.ui.developer_demo import DemoOverlay
from spacedrums.ui.kit import render_kit

ROOT = Path(__file__).resolve().parents[3]


def distribution(values):
    return (
        dict(zip(("p50", "p95", "max"), map(float, np.percentile(values, [50, 95, 100])), strict=True))
        if values
        else None
    )


def play_config(*, demo=False, delegate="CPU"):
    paths = [ROOT / "configs/prototype.candidate.yaml", ROOT / "configs/product.candidate.yaml"]
    if demo:
        paths.append(ROOT / "configs/demo.professor.candidate.yaml")
    cfg = load_config(*paths).data
    cfg["hands"]["delegate"] = delegate
    if demo:
        cfg["zones"] = DeveloperDemoLayout(cfg).zones
    cfg["audio"]["sample_bank"]["path"] = str(ROOT / "assets/samples")
    cfg["audio"]["sample_bank"]["manifest"] = str(ROOT / "assets/samples/recorded-manifest.json")
    validate(cfg)
    return cfg


def check_assets(cfg):
    """No camera, window, sound stream or fabricated strike is opened by preflight."""
    from spacedrums.audio import SampleBank
    from spacedrums.hands.model_asset import resolve_model_asset

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
    cfg = play_config(demo=args.demo, delegate=args.delegate)
    if args.check:
        print(json.dumps(check_assets(cfg), indent=2))
        return 0
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
    registry = None

    def start_pipeline():
        nonlocal audio, pipeline, registry
        cfg["zones"] = calibration.zones
        validate(cfg)
        registry = ZoneRegistry.from_config(cfg["zones"])
        audio = AudioOutput(cfg, latency=OutputLatency.unmeasured(),
                            device_enabled=not args.no_audio and not args.replay)
        audio.start()
        pipeline = DecisionPipeline(
            cfg, registry=registry, session_id=session, active_arm=Arm.A,
            hardware_id="developer-host", config_hash=config_hash(cfg), audio=audio,
            developer_demo=args.demo,
        )

    if args.record_frames:
        (directory / "frames").mkdir()
    try:
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
            observations = perception(view)
            evidence = perception.estimator.evidence
            endpoint_reasons.update(e.reason for e in evidence.values())
            metrics["hand_inference_ms"].append(perception.last_hands.processing_s * 1000)
            metrics["perception_ms"].append((now() - perception_started) * 1000)
            if calibration.state == "STAND" and sample.t_capture - last_pose >= 0.2:
                body = pose.detect(view)
                last_pose = sample.t_capture
                metrics["pose_inference_ms"].append(pose.processing_s * 1000)
            stage = now()
            result = None
            if pipeline is not None:
                decision_time = None if not args.replay else sample.t_frame_available + (now() - begin)
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
                zones = calibration.zones or calibration.guide_zones
                display_registry = registry or (ZoneRegistry.from_config(zones) if zones else None)
                img = demo_overlay.render(
                    view.full, roi, registry, evidence, result, dropped=dropped,
                    perception_ms=metrics["perception_ms"][-1], audio_state=audio.device_state,
                    stroke_diagnostics=pipeline.geometry.diagnostics,
                ) if demo_overlay else render_kit(
                    view.full,
                    roi,
                    display_registry,
                    sticks=[s for o, s in observations.values()],
                    body=calibration.body,
                    message=calibration.message,
                    target=calibration.target,
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
                cv2.imshow("Space Drums", img)
                key = cv2.pollKey() & 0xFF
                if key in (27, ord("q")):
                    break
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
        "commits_by_drum": {z: counts[z] for z in ("snare", "crash_ride", "hihat", "tom1")},
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
        "audio": audio_stats,
        "action_to_sound_ms": None,
        "audio_output_latency_ms": None,
        "acceptance": "RUNTIME_ERROR" if error else
        "DEVELOPER_DEMO_AWAITING_PHYSICAL_VERIFICATION" if args.demo else
        "PENDING_INDEPENDENT_VALIDATION"
        if calibration.state == "READY"
        else "CALIBRATION_INCOMPLETE",
        "target_fps": 30,
        "models": {"hands": cfg["hands"]["model_asset_id"],
                   "pose": None if args.demo else cfg["product"]["pose_asset_id"]},
        "model_sha256": {
            "hands": perception.landmarker.asset.sha256 if perception else None,
            "pose": pose.asset.sha256 if pose else None,
        },
    }
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
    p.add_argument("--fingers", action="store_true", help="Bare hands: index fingertips act as sticks")
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
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
