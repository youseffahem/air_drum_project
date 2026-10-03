"""Playable prototype application (Phase 05, Task 05.5): capture -> hands -> stick -> tracking -> (A | B) ->
geometry -> commit -> audio, both hands, with zone rendering, minimal overlay, keyboard arm switch and
record mode.

    python -m spacedrums.app.main --config configs/prototype.candidate.yaml                 # live camera
    python -m spacedrums.app.main --source devcapture --capture swing-L2-exp-5 --record      # dev capture
    python -m spacedrums.app.main --source replay --session-dir data/sessions/<id>   # recorded session
    python -m spacedrums.app.main --synthetic single --record --no-window            # SYNTHETIC self-test

Keys (window): ``a`` / ``b`` / ``c`` select a running arm (c = configured temporal model);
``q`` quits. Sources: ``live`` (``LiveFrameSource``), ``replay`` / ``devcapture``
(``ReplayFrameSource``: original timestamps, ``timestamp_source = REPLAY``), ``--synthetic <scenario>``
(labelled SYNTHETIC observations straight into the decision pipeline; no perception, no camera).

``t_now`` for commit decisions: live = ``timing.now()``; replay/synthetic = ``t_frame_available +
replay_delta_proc_s`` (provisional constant, default 0.0, so a replay reproduces the committed-strike
list; Phase 09 defines the ``Delta_proc`` policy). Audio: the device plays unless ``--no-audio``; the
scheduler always runs. The audio output latency is PENDING on HW-01 (Phase 04 gate): pass
``--audio-output-latency-s`` **with** ``--audio-latency-run-id`` only for an accepted measurement;
otherwise ``t_audio_out_est`` is withheld from the timing records.

Phase 17 (Task 17.9, ADR-0040): every session runs the safety-invariant monitor (``--invariants
log`` by default, ``raise`` for test builds), the health monitor (camera / tracking / model / audio;
non-OK components are shown on the overlay and the dashboard), a structured event log
(``--log-dir``; in memory when not given, ``data/logs`` for live sessions) and supervises the audio
device. An unexpected exception writes a crash report (config / model / calibration hashes) before
it propagates; a missing camera is a user message and exit code 3, not a traceback.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from spacedrums import timing
from spacedrums.app.audio_out import AudioOutput, OutputLatency
from spacedrums.app.errors import EventLog, ReportedError, user_text, write_crash_report
from spacedrums.app.health import HealthMonitor, HealthSettings, Level
from spacedrums.app.invariants import InvariantMonitor
from spacedrums.app.loss_diagnosis import RuntimeDiagnostics
from spacedrums.app.pipeline import HANDS, DecisionPipeline, FrameResult
from spacedrums.app.recorder import SessionRecorder
from spacedrums.app.session_summary import summarise_session
from spacedrums.app.synthetic import SCENARIOS, scenario
from spacedrums.calib import CalibrationError, load_calibrated_config
from spacedrums.capture import CaptureSettings, LiveFrameSource, OpenCvCamera, ReplayFrameSource, Roi
from spacedrums.config import ResolvedConfig
from spacedrums.contracts import (
    Arm,
    FrameSample,
    FrameView,
    HandId,
    HandObservation,
    StickObservation,
)
from spacedrums.geometry import ZoneRegistry
from spacedrums.ui import (
    Canvas,
    DashboardRecord,
    DashboardWorker,
    OverlayConfig,
    OverlayRecords,
    OverlayStyle,
    RecordBus,
    RuntimeStats,
    draw_scientific_overlay,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "configs" / "prototype.candidate.yaml"
WINDOW = "Space Drums - live arms A/B/C"
Observations = dict[HandId, tuple[HandObservation, StickObservation]]


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "0" * 40


# ----------------------------------------------------------------------------- perception


class Perception:
    """hands -> stick for both hands (Phase 03 modules); one instance per session."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        from spacedrums.hands import HandLandmarker, HandLandmarkerSettings
        from spacedrums.stick import StickSettings, make_tip_estimator

        self.landmarker = HandLandmarker(HandLandmarkerSettings.from_config(cfg))
        self.stick_settings = StickSettings.from_config(cfg)
        self.estimator = make_tip_estimator(self.stick_settings.method_id, self.stick_settings)
        if cfg.get("product", {}).get("enabled", False):
            from spacedrums.stick.visible import VisibleEndpointEstimator, VisibleSettings

            settings = VisibleSettings(**cfg["product"].get("endpoint", {}))
            self.estimator = VisibleEndpointEstimator(self.stick_settings, settings)
        self.last_hands: HandsResult | None = None
        self.last_analyses: dict[HandId, Any] = {}

    def __call__(self, view: FrameView) -> Observations:
        res = self.landmarker.detect(view)
        self.last_hands = res
        out: Observations = {}
        for h in HANDS:
            hand_obs = res.left if h is HandId.LEFT else res.right
            stick = self.estimator.estimate(view, hand_obs)
            out[h] = (hand_obs, stick)
            self.last_analyses[h] = self.estimator.last_analysis
        return out

    def close(self) -> None:
        self.landmarker.close()


HandsResult = Any


# ----------------------------------------------------------------------------- overlay


def render(
    view_image: np.ndarray | None,
    roi: Roi,
    registry: ZoneRegistry,
    result: FrameResult,
    observations: Observations,
    active_arm: Arm,
    style: OverlayStyle,
    status_lines: list[str] | None = None,
    draw_hook: Callable[[Canvas, ZoneRegistry], None] | None = None,
    overlay_config: OverlayConfig | None = None,
    runtime: RuntimeStats | None = None,
    analyses: dict[HandId, Any] | None = None,
    mirror: bool = False,
) -> np.ndarray:
    """Window image. ``mirror`` (live) mirrors only the camera image; overlays, protocol cues and
    status text are drawn on it afterwards in display space, so text stays readable."""
    full = view_image if view_image is not None else np.zeros((roi.y1 + 8, roi.x1 + 8, 3), np.uint8)
    hands = {h: observations[h][0] for h in HANDS}
    sticks = {h: observations[h][1] for h in HANDS}
    tracks = {h: result.hands[h].track for h in HANDS}
    records = OverlayRecords(
        predictions=tuple(("B", hf.prediction) for hf in result.hands.values() if hf.prediction is not None)
        + tuple(
            ("C", hf.model_prediction) for hf in result.hands.values() if hf.model_prediction is not None
        ),
        candidates=tuple(c for hf in result.hands.values() for c in hf.candidates),
        commits=tuple(result.commits),
        decisions=tuple(trace for hf in result.hands.values() for trace in hf.decision_traces),
        runtime=runtime,
    )
    img = draw_scientific_overlay(
        full,
        roi,
        config=overlay_config or OverlayConfig(),
        hands=hands,
        analyses=analyses,
        sticks=sticks,
        tracks=tracks,
        records=records,
        registry=registry,
        mirror=mirror,
    )
    canvas = Canvas.for_display(img, mirror)
    if draw_hook is not None:  # Phase 06 guided-protocol cues (zone highlight, countdown) on the ROI
        draw_hook(canvas.roi(roi), registry)
    status = canvas.upright(roi.x, roi.x1)
    y = 60
    for line in status_lines or []:  # protocol instructions (playability / induced-loss scripts)
        status.put_text(line, (roi.x + 6, roi.y + y), style.font, 0.6, (0, 255, 255), 2)
        y += 22
    return img


# ----------------------------------------------------------------------------- sources


def camera_factory():
    """The live camera backend (a seam for the Phase 17 system tests' failing camera)."""
    return OpenCvCamera()


def iter_source(
    args: argparse.Namespace,
    cfg: ResolvedConfig,
    registry: ZoneRegistry,
    on_idle: Callable[[float], None] | None = None,
) -> tuple[
    Iterator[tuple[FrameSample, FrameView | None, Observations | None]],
    Callable[[], None],
    dict[str, Any],
    Any,
]:
    """(frames, stop, source_meta, synthetic_truth); a frame is (sample, view | None, observations | None)."""
    if args.synthetic:
        seq = scenario(
            args.synthetic, registry, seed=args.seed, noise=args.synthetic_noise, image=bool(args.record)
        )

        def gen_synth():
            for sample, obs in seq:
                yield sample, None, obs

        return (
            gen_synth(),
            (lambda: None),
            {"source": "synthetic", "scenario": args.synthetic, "label": "SYNTHETIC", **seq.params},
            [t.to_dict() for t in seq.truth],
        )
    if args.source in ("replay", "devcapture"):
        session_dir = (
            (ROOT / "data" / "dev-captures" / args.capture)
            if args.source == "devcapture"
            else Path(args.session_dir)
        )
        src = ReplayFrameSource(session_dir, limit=args.max_frames)

        def gen_replay():
            for sample in src:
                yield sample, src.view(sample), None

        return (
            gen_replay(),
            (lambda: None),
            {
                "source": args.source,
                "path": str(session_dir),
                "frames": len(src),
                "timestamp_source": "REPLAY",
            },
            None,
        )
    settings = CaptureSettings.from_config(cfg.data)
    live = LiveFrameSource(camera_factory(), settings)
    try:
        mode = live.start()
    except (RuntimeError, OSError, ValueError) as exc:
        raise ReportedError("SD-CAM-001", f"{type(exc).__name__}: {exc}") from exc
    print(
        f"[app] negotiated {mode.backend} {mode.width}x{mode.height} {mode.fourcc} "
        f"fps_prop={mode.fps_prop} (advertised)"
    )

    def gen_live():
        n = 0
        t_end = timing.now() + args.max_seconds if args.max_seconds else None
        while True:
            if t_end is not None and timing.now() >= t_end:
                return
            if args.max_frames is not None and n >= args.max_frames:
                return
            f = live.next_frame(timeout=0.5)
            if f is None:
                if live._queue.closed:
                    return
                if on_idle is not None:  # Phase 17: a camera stall is reported while waiting
                    on_idle(timing.now())
                continue
            n += 1
            try:
                live_meta["capture_stats"] = live.stats().to_dict()
            except Exception:  # noqa: BLE001 - display provenance must never stop capture
                pass
            yield f, live.view(f), None

    live_meta: dict[str, Any] = {
        "source": "live",
        "negotiated": mode.__dict__ if hasattr(mode, "__dict__") else str(mode),
        "capture_stats": None,  # filled at stop (Phase 06 SessionMetadata.capture_stats)
    }

    def stop_live() -> None:
        try:
            live_meta["capture_stats"] = live.stats().to_dict()
        except Exception:  # noqa: BLE001 - stats are best-effort provenance, never block the stop
            pass
        live.stop()
        live_meta["queue"] = live.queue_report()  # consumer-side depth at delivery (diagnostics)

    return gen_live(), stop_live, live_meta, None


# ----------------------------------------------------------------------------- main loop


FrameHook = Callable[[FrameSample, FrameResult, "DecisionPipeline"], bool]
SourceFactory = Callable[[argparse.Namespace, ResolvedConfig, ZoneRegistry], tuple[Any, Any, Any, Any]]


def run(
    args: argparse.Namespace,
    *,
    on_frame: FrameHook | None = None,
    status_lines: Callable[[], list[str]] | None = None,
    session_meta: dict[str, Any] | None = None,
    source_factory: SourceFactory | None = None,
    draw_hook: Callable[[Canvas, ZoneRegistry], None] | None = None,
    on_key: Callable[[str], None] | None = None,
    observation_hook: Callable[[FrameSample, Observations], Observations] | None = None,
    gain_scale: float = 1.0,
) -> dict[str, Any]:
    """Run one session. ``on_frame`` (returns False to stop) and ``status_lines`` (overlay text) let the
    protocol scripts drive the loop without re-implementing it; ``session_meta`` is merged into
    session.json. Phase 06 additions: ``source_factory`` replaces :func:`iter_source` (a composed
    SYNTHETIC protocol sequence), ``draw_hook`` draws cues on the ROI ``Canvas`` (mirrored in live
    windows; drawing through its methods keeps cues on the image and text readable), ``on_key``
    receives every printable key the loop does not consume itself (``a`` / ``b`` / ``c`` / ``q``). Phase 17:
    ``observation_hook`` (test builds only: ``app.faults``) replaces perception output per frame
    (fault injection, the soak's scripted strokes); ``gain_scale`` attenuates played samples only."""
    if observation_hook is not None:
        from spacedrums.app.faults import require_test_build

        require_test_build()
    opencv_threads = getattr(args, "opencv_threads", 1)
    if type(opencv_threads) is not int or opencv_threads < 1:
        raise ValueError("opencv_threads must be a positive integer")
    cv2.setNumThreads(opencv_threads)
    calibrated = load_calibrated_config(*args.config, calibration=getattr(args, "calibration", None))
    cfg = calibrated.config
    if cfg.get("product", {}).get("enabled", False):
        raise ValueError("Product mode needs automatic calibration: run python -m spacedrums.app.play")
    calib_fields = calibrated.session_fields()
    detail = (
        f" {calib_fields['calibration_id']} ({calib_fields['calibration_hash']})"
        if calib_fields["calibration_id"]
        else " (default layout from the config)"
    )
    print(f"[app] calibration: {calibrated.status}{detail}")
    for warning in calibrated.warnings:
        print(f"[app] calibration warning: {warning}")
    if "arms" not in cfg.data:
        raise ValueError("config needs an arms block (active / shadow) from Phase 05 on")
    registry = ZoneRegistry.from_config(cfg["zones"])
    active = Arm(args.arm or cfg["arms"]["active"])
    shadow = tuple(Arm(a) for a in (cfg["arms"]["shadow"] if args.shadow is None else args.shadow))
    latency = (
        OutputLatency(float(args.audio_output_latency_s), True, args.audio_latency_run_id)
        if args.audio_output_latency_s is not None
        else OutputLatency.unmeasured()
    )
    if args.audio_output_latency_s is not None and not args.audio_latency_run_id:
        raise ValueError(
            "--audio-output-latency-s requires --audio-latency-run-id (an accepted measurement run)"
        )
    audio = AudioOutput(
        cfg.data,
        latency=latency,
        device_enabled=not args.no_audio and not args.synthetic,
        output_scale=gain_scale,
    )
    session_id = args.session_id or f"dev-{timing.wall_clock_local_compact()}-{args.synthetic or args.source}"
    live_source = not args.synthetic and args.source == "live"
    log_dir = getattr(args, "log_dir", None) or (ROOT / "data" / "logs" if live_source else None)
    session_log_dir = Path(log_dir) / session_id if log_dir is not None else None
    events = EventLog(
        session_log_dir / "events.jsonl" if session_log_dir is not None else None,
        context={"session_id": session_id, "config_hash": cfg.config_hash},
    )
    crash_context = {
        "session_id": session_id,
        "config_hash": cfg.config_hash,
        "calibration_hash": calib_fields.get("calibration_hash"),
        "git_sha": git_sha(),
        "model": {
            k: (cfg["anticipator"].get("model") or {}).get(k)
            for k in ("path", "hash", "manifest_hash", "family")
        },
        "source": getattr(args, "source", None),
        "synthetic": getattr(args, "synthetic", None),
    }
    try:
        pipeline = DecisionPipeline(
            cfg.data,
            registry=registry,
            session_id=session_id,
            active_arm=active,
            shadow_arms=shadow,
            hardware_id=args.hardware_id,
            config_hash=cfg.config_hash,
            audio=audio,
        )
    except Exception as exc:
        report = write_crash_report(
            exc, session_log_dir or ROOT / "data" / "logs", context=crash_context, events=events
        )
        print(user_text("SD-APP-001", str(report)))
        raise
    if pipeline.model_error:
        events.emit("SD-MDL-002", detail={"reason": pipeline.model_error[:300]})
        print(user_text("SD-MDL-002", pipeline.model_error[:160]))
    invariant_mode = getattr(args, "invariants", "log")
    monitor = (
        None if invariant_mode == "off" else InvariantMonitor.for_pipeline(pipeline, mode=invariant_mode)
    )
    health = HealthMonitor(HealthSettings.from_config(cfg.data), events=events)
    # Diagnostics only (live responsiveness, 2026-10-02): why tracks were lost, frame freshness and
    # hand-model cost; written to counters["diagnostics"], never a decision input.
    diagnostics = RuntimeDiagnostics(
        c_valid=pipeline.tracker_settings.machine.c_valid,
        max_gap_s=pipeline.tracker_settings.max_frame_gap_s,
        live=not args.synthetic and args.source == "live",
    )
    reported: set[str] = set()
    previous_status: dict[HandId, str] = {}

    def announce(status) -> None:
        """Print a component's user message once per transition into a non-OK state."""
        for comp in status.components().values():
            if comp.code and comp.level in (Level.WARN, Level.FAIL) and comp.code not in reported:
                reported.add(comp.code)
                print(user_text(comp.code))
        for code in list(reported):
            if not any(c.code == code for c in status.components().values()):
                reported.discard(code)

    def on_idle(t: float) -> None:
        status = health.observe_no_frame(t)
        if status is not None:
            announce(status)
    # Initialize native libraries before the capture thread starts filling its bounded queue.
    # Phase 16's unattended baseline lost 23 frames during this initialization.
    perception = None if args.synthetic else Perception(cfg.data)
    try:
        if source_factory is None:
            frames, stop, source_meta, truth = iter_source(args, cfg, registry, on_idle=on_idle)
        else:
            frames, stop, source_meta, truth = source_factory(args, cfg, registry)
    except BaseException as exc:
        if perception is not None:
            perception.close()
        if isinstance(exc, ReportedError):
            events.emit(exc.code, detail={"error": exc.detail})
        raise
    replay_like = bool(args.synthetic) or args.source in ("replay", "devcapture")
    recorder: SessionRecorder | None = None
    if args.record:
        out_dir = Path(args.output_dir or cfg["debug"]["record_mode"]["output_dir"])
        recorder = SessionRecorder(
            out_dir,
            session_id=session_id,
            config=cfg,
            git_sha=git_sha(),
            producer=("REGENERATED" if args.regenerated else "REPLAY") if replay_like else "LIVE",
            store_crop=cfg["debug"]["record_mode"]["store_crop"],
            extra_meta={
                "hardware_id": args.hardware_id,
                "arm_active": str(active),
                "arms_shadow": [str(a) for a in shadow],
                "source": source_meta,
                "replay_delta_proc_s": args.replay_delta_proc_s if replay_like else None,
                "audio": {"device_enabled": audio.device_enabled, "output_latency": latency.to_dict()},
                "synthetic_truth": truth,
                "calibration": {
                    **calib_fields,
                    "path": cfg.data.get("calibration_path"),
                    "warnings": list(calibrated.warnings),
                },
                **(session_meta or {}),
            },
        )
        if calibrated.calibration is not None and calibrated.calibration.path is not None:
            # the session is self-contained: the applied calibration travels with it (hash in session.json)
            shutil.copyfile(calibrated.calibration.path, recorder.dir / "calibration.calib.yaml")
    style = OverlayStyle(show_candidates=False, show_region=False)
    overlay_config = OverlayConfig.for_mode(getattr(args, "overlay_mode", "experiment"))
    window = not args.no_window and not args.synthetic
    record_bus = RecordBus()
    dashboard_subscription = (
        record_bus.subscribe("dashboard", maxsize=2) if getattr(args, "dashboard", False) else None
    )
    dashboard = (
        DashboardWorker(dashboard_subscription, live=not replay_like)
        if dashboard_subscription is not None
        else None
    )
    roi = Roi.from_rect(cfg["roi"]["px"])
    n = 0
    capture_drops_total = 0
    previous_capture_t: float | None = None
    per_frame_s: list[float] = []
    try:
        audio.start()
        if audio.device_state == "DOWN":
            events.emit("SD-AUD-001", detail={"reason": audio.last_error})
            print(user_text("SD-AUD-001", audio.last_error))
        if dashboard is not None:
            dashboard.start()
        if window:
            cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
            if dashboard is not None:
                cv2.namedWindow("Space Drums - dashboard", cv2.WINDOW_NORMAL)
        for sample, view, obs in frames:
            t0 = timing.now()
            if obs is None:
                assert perception is not None and view is not None
                obs = perception(view)
            if observation_hook is not None:
                obs = observation_hook(sample, obs)
            t_now = (sample.t_frame_available + args.replay_delta_proc_s) if replay_like else None
            audio.check_health(timing.now())
            result = pipeline.step(sample, obs, t_now=t_now, processing_started=t0)
            if monitor is not None:
                for violation in monitor.observe(result, pipeline):
                    if monitor.counts[violation.invariant] <= 20:  # bounded log (release mode)
                        events.emit("SD-INV-001", detail=violation.to_dict())
            processing_s = timing.now() - t0
            per_frame_s.append(processing_s)
            diagnostics.observe(sample, obs, result, perception, t_start=t0)
            audio_stats = audio.stats() if audio is not None else {}
            audio_underruns = int((audio_stats.get("mixer") or {}).get("underruns", 0))
            status = health.observe_frame(
                result,
                pipeline,
                t_now=timing.now(),
                audio_state=audio.device_state,
                audio_underruns=audio_underruns,
                clamped_timestamps=(source_meta.get("capture_stats") or {}).get("clamped_timestamps"),
            )
            announce(status)
            for h, hf in result.hands.items():  # re-acquisition after a loss (INFO event)
                if previous_status.get(h) in ("INVALID", "STALE") and hf.track.status == "VALID":
                    events.emit(
                        "SD-TRK-002",
                        detail={
                            "hand_id": str(h),
                            "frame_id": sample.frame_id,
                            "loss_cause": diagnostics.reacquired_cause(h),
                        },
                    )
                previous_status[h] = str(hf.track.status)
            capture_drops_total += sample.dropped_since_last
            capture_stats = source_meta.get("capture_stats") or {}
            capture_fps = capture_stats.get("fps_measured")
            if capture_fps is None and previous_capture_t is not None:
                dt_capture = sample.t_capture - previous_capture_t
                capture_fps = 1.0 / dt_capture if dt_capture > 0 else None
            previous_capture_t = sample.t_capture
            if dashboard_subscription is not None:
                record_bus.publish(
                    DashboardRecord(
                        frame_id=sample.frame_id,
                        t_capture=sample.t_capture,
                        active_arm=str(pipeline.active_arm),
                        fallback_status=pipeline.model_error,
                        capture_fps=capture_fps,
                        capture_drops=capture_drops_total,
                        audio_underruns=audio_underruns,
                        processing_s=processing_s,
                        timing=tuple(result.timing),
                        hands=tuple(
                            {
                                "hand_id": str(h),
                                "track": result.hands[h].track.to_dict(),
                                "candidates": tuple(c.to_dict() for c in result.hands[h].candidates),
                                "decisions": tuple(result.hands[h].decision_traces),
                            }
                            for h in HANDS
                        ),
                        strike_zones=tuple((commit.strike_id, commit.zone_id) for commit in result.commits),
                        health=_health_line(status),
                    )
                )
            n += 1
            if recorder is not None:
                image = (
                    view.full
                    if (view is not None and view.full is not None)
                    else (view.roi if view is not None else sample.image_ref.array)
                )
                recorder.write_frame(sample, image, result, obs)
            for s in result.commits:
                if args.verbose or not s.shadow:
                    print(
                        f"[commit] f{sample.frame_id} {s.hand_id} {s.arm}{' shadow' if s.shadow else ''} "
                        f"{s.zone_id} "
                        f"t_commit={s.t_commit:.4f} target={s.t_impact_target:.4f}"
                    )
            if on_frame is not None and not on_frame(sample, result, pipeline):
                break
            if window:
                img = render(
                    view.full if view is not None else None,
                    roi,
                    registry,
                    result,
                    obs,
                    pipeline.active_arm,
                    style,
                    (status_lines() if status_lines is not None else [])
                    + ([f"MODEL DISABLED: {pipeline.model_error}"] if pipeline.model_error else [])
                    + [m for m in status.messages() if not m.startswith(("[SD-MDL", "[SD-TRK-002"))],
                    draw_hook,
                    overlay_config,
                    RuntimeStats(
                        active_arm=str(pipeline.active_arm),
                        fallback_status=pipeline.model_error,
                        capture_fps=capture_fps,
                        capture_drops=capture_drops_total,
                        audio_underruns=audio_underruns,
                        ui_drops=dashboard_subscription.dropped if dashboard_subscription else 0,
                    ),
                    perception.last_analyses if perception is not None else None,
                    mirror=not replay_like,
                )
                cv2.imshow(WINDOW, img)
                if dashboard is not None and dashboard.latest_image is not None:
                    cv2.imshow("Space Drums - dashboard", dashboard.latest_image)
                key = cv2.pollKey() & 0xFF  # does not wait; waitKey(1) waits on the Windows timer (T2)
                if key == ord("q"):
                    break
                if key in (ord("a"), ord("b"), ord("c")):
                    selected = {ord("a"): Arm.A, ord("b"): Arm.B, ord("c"): pipeline.model_label}[key]
                    try:
                        pipeline.set_active_arm(selected, result.t_now)
                        print(f"[app] active arm -> {pipeline.active_arm}")
                    except ValueError as exc:
                        print(f"[app] arm switch refused: {exc}")
                elif on_key is not None and 32 <= key < 127:
                    on_key(chr(key))
            if args.max_frames is not None and n >= args.max_frames:
                break
    except (KeyboardInterrupt, ReportedError):
        raise
    except Exception as exc:
        report = write_crash_report(
            exc,
            session_log_dir or ROOT / "data" / "logs",
            context={**crash_context, "frames": n},
            events=events,
        )
        print(user_text("SD-APP-001", str(report)))
        raise
    finally:
        stop()
        audio.stop()
        if dashboard is not None:
            dashboard.stop()
        if perception is not None:
            perception.close()
        if window:
            cv2.destroyAllWindows()
            cv2.waitKey(1)
    counters = pipeline.counters()
    counters["runtime_threads"] = {"opencv": cv2.getNumThreads()}
    counters["invariants"] = monitor.finish() if monitor is not None else {"mode": "off"}
    counters["diagnostics"] = diagnostics.summary(source_meta)
    counters["health"] = {
        "final": health.status.to_dict() if health.status is not None else None,
        "transitions": health.transitions,
    }
    counters["events"] = {
        **events.summary(),
        "log": str(session_log_dir / "events.jsonl") if session_log_dir is not None else None,
    }
    counters["ui"] = {
        "overlay_mode": getattr(args, "overlay_mode", "experiment"),
        "dashboard": dashboard_subscription.stats() if dashboard_subscription is not None else None,
        "processing_note": (
            "dashboard publication is non-blocking; UI queue drops do not count as capture drops"
        ),
    }
    proc = sorted(per_frame_s)
    counters["per_frame_processing_s"] = {
        "n": len(proc),
        "p50": proc[len(proc) // 2] if proc else None,
        "p95": proc[min(len(proc) - 1, int(0.95 * len(proc)))] if proc else None,
        "max": proc[-1] if proc else None,
        "note": "wall-clock of perception + decision per frame on this machine "
        "(software-stamped, development only)",
    }
    summary: dict[str, Any] = {
        "session_id": session_id,
        "frames": n,
        "source": source_meta,
        "counters": counters,
        "config_hash": cfg.config_hash,
        "active_arm_final": str(pipeline.active_arm),
        "calibration": calib_fields,
    }
    if recorder is not None:
        if session_meta is not None:
            recorder.meta.update(session_meta)  # scripts may fill segment boundaries during the run
        recorder.meta.update(
            arm_active=str(pipeline.active_arm),
            arms_shadow=[str(a) for a in pipeline.shadow_arms],
            arm_switches=pipeline.arm_switches,
            fallback_events=pipeline.fallback_events,
            model_id=pipeline.model_arm.model_id if pipeline.model_arm else None,
            model_runtime=counters["model"],
        )
        session_dir = recorder.close(summary)
        summary["session_dir"] = str(session_dir)
        summary["session_summary"] = summarise_session(session_dir, truth=truth)
    return summary


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--config",
        nargs="+",
        type=Path,
        default=[DEFAULT_CONFIG],
        help="config file(s) merged in order (default: configs/prototype.candidate.yaml)",
    )
    ap.add_argument("--source", choices=("live", "replay", "devcapture"), default="live")
    ap.add_argument(
        "--session-dir", type=Path, default=None, help="recorded session directory (--source replay)"
    )
    ap.add_argument("--capture", default="swing-L2-exp-5", help="dev capture name (--source devcapture)")
    ap.add_argument(
        "--synthetic",
        choices=SCENARIOS,
        default=None,
        help="run a labelled SYNTHETIC scenario through the decision pipeline (no camera, no audio device)",
    )
    ap.add_argument("--synthetic-noise", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument(
        "--arm",
        choices=("A", "B", "C-GRU", "C-TCN"),
        default=None,
        help="active arm (default: config arms.active)",
    )
    ap.add_argument(
        "--shadow",
        nargs="*",
        choices=("A", "B", "C-GRU", "C-TCN"),
        default=None,
        help="shadow arms (default: config)",
    )
    ap.add_argument(
        "--record", action="store_true", help="record mode (frames + every record stream + timing)"
    )
    ap.add_argument("--output-dir", type=Path, default=None)
    ap.add_argument("--session-id", default=None)
    ap.add_argument(
        "--no-audio", action="store_true", help="do not open the audio device (scheduler still runs)"
    )
    ap.add_argument(
        "--audio-output-latency-s",
        type=float,
        default=None,
        help="MEASURED output latency of the audio profile (only with --audio-latency-run-id)",
    )
    ap.add_argument("--audio-latency-run-id", default=None)
    ap.add_argument("--no-window", action="store_true")
    ap.add_argument(
        "--opencv-threads",
        type=int,
        default=1,
        help="OpenCV CPU worker count (Phase 16 default 1; use 8 to reproduce the HW-01 baseline)",
    )
    ap.add_argument(
        "--overlay-mode",
        choices=("off", "experiment", "full"),
        default="experiment",
        help="in-frame overlay preset (experiment is the measured low-overhead set)",
    )
    ap.add_argument(
        "--dashboard",
        action="store_true",
        help="run the secondary diagnostic panel on a bounded drop-if-full subscriber",
    )
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--max-seconds", type=float, default=None)
    ap.add_argument(
        "--regenerated",
        action="store_true",
        help="record-mode streams carry producer REGENERATED (offline re-derivation from raw frames, "
        "architecture.md section 12.3; Phase 06 scripts/regenerate_session.py)",
    )
    ap.add_argument(
        "--replay-delta-proc-s",
        type=float,
        default=0.0,
        help="t_now = t_frame_available + this in replay/synthetic runs (provisional; Phase 09 decides)",
    )
    ap.add_argument(
        "--calibration",
        type=Path,
        default=None,
        help="calib-v1 file to apply (sets calibration_path); made by python -m spacedrums.app.calibrate",
    )
    ap.add_argument(
        "--invariants",
        choices=("log", "raise", "off"),
        default="log",
        help="safety-invariant monitor I1-I6 (Phase 17): log in release, raise in test builds",
    )
    ap.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="structured event log + crash reports (<dir>/<session>/); default data/logs for live sessions",
    )
    ap.add_argument("--hardware-id", default="HW-01")
    ap.add_argument("--summary-json", type=Path, default=None, help="write the run summary here")
    ap.add_argument("--verbose", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = run(args)
    except CalibrationError as exc:
        print(f"[app] calibration refused: {exc}")
        return 2
    except ReportedError as exc:
        print(user_text(exc.code, exc.detail))
        return 3
    c = summary["counters"]
    print(
        f"[app] {summary['session_id']}: {summary['frames']} frames; commits "
        + ", ".join(f"{arm}={sum(v['commits'] for v in per.values())}" for arm, per in c["commit"].items())
        + f"; audio events {c['audio']['events_scheduled'] if c['audio'] else 0}"
    )
    if "session_summary" in summary:
        ss = summary["session_summary"]
        print(
            f"[app] recorded -> {summary['session_dir']}; commits during non-VALID frames: "
            f"{ss['commits_during_non_valid']}"
        )
        print(ss["timing_table_markdown"])
    if args.summary_json is not None:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(
            json.dumps(summary, indent=2, allow_nan=False, default=str), encoding="utf-8"
        )
    return 0


def _health_line(status) -> str | None:
    if status is None:
        return None
    parts = [
        f"{name} {c.level}" + (f" {c.code}" if c.code else "") for name, c in status.components().items()
    ]
    return "health: " + " | ".join(parts)


if __name__ == "__main__":
    sys.exit(main())
