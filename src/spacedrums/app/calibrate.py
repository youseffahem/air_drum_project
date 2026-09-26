"""Calibration Wizard application (Phase 14, Q57; Tasks 14.2-14.6; ADR-0037).

    python -m spacedrums.app.calibrate --user-tag dev-jo                        # live, MVP-4, per-user file
    python -m spacedrums.app.calibrate --scope SETUP --setup-tag hw01-desk --layout v1-7
    python -m spacedrums.app.calibrate --synthetic --output <dir>/x.calib.yaml   # SYNTHETIC self-test
    python -m spacedrums.app.calibrate --source replay --session-dir data/dev-captures/swing-L2-exp-5 \\
        --window-scale 0.2 --output <dir>/replay.calib.yaml                      # DEVELOPER_REPLAY diagnostic
    python -m spacedrums.app.calibrate --check configs/calibration/<file>.calib.yaml   # triggers only

Per frame: live camera / replayed frames -> Phase 03 perception (the stick axis support comes from the
same analysis the GEOM tip uses), or the SYNTHETIC actor -> an **Arm-A-only** ``DecisionPipeline``
(tracking, reactive geometry, commit; no rule arm, no model: calibration never depends on model
behaviour) -> ``WizardFrame`` -> ``CalibrationWizard`` -> ``ui.wizard_views``. The pipeline is rebuilt
with the fitted zones for the validation step, and perception uses the calibrated per-hand L_prior
after the stick-prior step.

Keys: SPACE start | ENTER accept | r retry | f use default | p redo placement | v skip validation |
n next zone | i/j/k/l nudge the selected zone | s next sound for it | q quit (progress kept: --resume).
Unfinished wizard = no calibration file: the app then runs UNCALIBRATED with the config's default
layout, and session metadata says so (phase Fallback Strategy).
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import cv2
import numpy as np

import spacedrums
from spacedrums import timing
from spacedrums.app.audio_out import AudioOutput, OutputLatency
from spacedrums.app.main import Perception, iter_source
from spacedrums.app.pipeline import HANDS, DecisionPipeline
from spacedrums.calib import (
    CalibrationError,
    CalibrationWizard,
    LayoutError,
    ProvenanceKind,
    Stage,
    Step,
    StickSample,
    Template,
    WizardFrame,
    WizardSettings,
    autopilot,
    load_calibration,
    recalibration_triggers,
    save_calibration,
)
from spacedrums.calib.synthetic import SyntheticUser
from spacedrums.capture import Roi
from spacedrums.config import ResolvedConfig, config_hash, resolve, validate
from spacedrums.contracts import Arm, FrameView, HandId
from spacedrums.geometry import ZoneRegistry
from spacedrums.ui import WizardView, draw_wizard

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "configs" / "prototype.candidate.yaml"
DEFAULT_SETTINGS = ROOT / "configs" / "calibration" / "wizard.candidate.yaml"
WINDOW = "Space Drums - Calibration Wizard"
SCALED = (
    "countdown_s",
    "camera_window_s",
    "playing_window_s",
    "stick_window_s",
    "sweep_window_s",
    "cue_period_s",
    "validation_lead_in_s",
)


def git_state() -> tuple[str, bool]:
    """(HEAD sha, dirty) - dirty ignores data/, experiments/, .venv/ (as the run logs do)."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return "0" * 40, True
    dirty = any(
        not line[3:].strip().strip('"').startswith(("data/", "experiments/", ".venv/"))
        for line in status.splitlines()
    )
    return sha, dirty


def base_config(paths: list[Path]) -> dict[str, Any]:
    """The uncalibrated setup the wizard calibrates (a configured calibration_path is ignored)."""
    doc = resolve(*paths)
    if doc.get("calibration") is not None:
        raise CalibrationError("pass the base configuration, not a calibrated snapshot")
    doc.pop("calibration_path", None)
    validate(doc)
    if "stick" not in doc or "hands" not in doc or "geometry" not in doc:
        raise CalibrationError("the wizard needs hands, stick and geometry blocks (schema >= 1.3)")
    return doc


def available_samples(cfg: dict[str, Any]) -> list[str] | None:
    manifest = cfg.get("audio", {}).get("sample_bank", {}).get("manifest")
    if not manifest:
        return None
    path = Path(manifest) if Path(manifest).is_absolute() else ROOT / manifest
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return sorted(str(s["sample_id"]) for s in doc.get("samples", []))


class WizardPerception(Perception):
    """Phase 03 perception that also exposes each hand's stick axis support (``StickAnalysis``)."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        super().__init__(cfg)
        self.analyses: dict[HandId, Any] = {}

    def __call__(self, view: FrameView) -> dict[HandId, tuple[Any, Any]]:  # same contract as Perception
        res = self.landmarker.detect(view)
        self.last_hands = res
        out = {}
        for h in HANDS:
            hand_obs = res.left if h is HandId.LEFT else res.right
            stick = self.estimator.estimate(view, hand_obs)
            self.analyses[h] = self.estimator.last_analysis if hand_obs.present else None
            out[h] = (hand_obs, stick)
        return out

    def stick_samples(self) -> dict[HandId, StickSample]:
        out = {}
        for h in HANDS:
            an = self.analyses.get(h)
            if an is None or an.axis is None:
                out[h] = StickSample(None, 0.0)
            else:
                out[h] = StickSample(float(an.axis.support_len_px) / an.roi.h, float(an.axis.confidence))
        return out

    def set_l_prior_by_hand(self, l_prior: dict[str, float]) -> None:
        from spacedrums.stick import make_tip_estimator

        geom = replace(self.stick_settings.geom, l_prior_by_hand=tuple(sorted(l_prior.items())))
        self.stick_settings = replace(self.stick_settings, geom=geom)
        self.estimator = make_tip_estimator(self.stick_settings.method_id, self.stick_settings)


def _parse_pairs(items: list[str] | None, kind: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items or []:
        zone, _, value = item.partition("=")
        if not zone or not value:
            raise SystemExit(f"--{kind} expects zone=value, got {item!r}")
        if kind == "nudge":
            dx, _, dy = value.partition(",")
            out[zone] = [float(dx), float(dy)]
        else:
            out[zone] = value
    return out


def default_output(args: argparse.Namespace, kind: ProvenanceKind) -> Path:
    if kind is ProvenanceKind.PARTICIPANT_LIVE:
        return ROOT / "data" / "calibration" / f"user-{args.user_tag}.calib.yaml"
    if args.scope == "USER":
        return (
            ROOT / "configs" / "calibration" / f"user-{args.user_tag}-{args.hardware_id.lower()}.calib.yaml"
        )
    return ROOT / "configs" / "calibration" / f"setup-{args.setup_tag}.calib.yaml"


def build_pipeline(
    cfg: dict[str, Any],
    zones: list[dict[str, Any]],
    *,
    audio: AudioOutput | None,
    session_id: str,
    hardware_id: str,
) -> DecisionPipeline:
    """Arm A only: no rule arm, no model (calibration outcomes must not depend on model behaviour)."""
    doc = copy.deepcopy(cfg)
    doc["zones"] = zones
    return DecisionPipeline(
        doc,
        registry=ZoneRegistry.from_config(zones),
        session_id=session_id,
        active_arm=Arm.A,
        shadow_arms=(),
        hardware_id=hardware_id,
        config_hash=config_hash(doc),
        audio=audio,
        gain_fn=None if audio is not None else (lambda _z, _v: 1.0),
    )


def to_view(wizard: CalibrationWizard, status: list[str]) -> WizardView:
    v = wizard.view()
    zones = v["zones"]
    return WizardView(
        step_number=v["step_number"],
        n_steps=v["n_steps"],
        title=v["title"],
        stage=v["stage"],
        lines=tuple(v["lines"]),
        keys=v["keys"],
        progress=v["progress"],
        ok=v["ok"],
        band=tuple(v["band"]) if v["band"] else None,
        envelope=tuple(v["envelope"]) if v["envelope"] else None,
        registry=ZoneRegistry.from_config(zones) if zones else None,
        highlight_zone=v["highlight_zone"],
        status_lines=tuple(status),
    )


def handle_key(wizard: CalibrationWizard, key: int, samples: list[str] | None) -> str | None:
    """Apply one key press; returns 'quit' or a message for the status line."""
    ch = chr(key) if 0 <= key < 128 else ""
    try:
        if ch == "q":
            return "quit"
        if key == 32 and wizard.stage is Stage.INSTRUCT:
            wizard.begin()
        elif key in (10, 13) and wizard.can_accept():
            wizard.accept()
        elif ch == "r" and wizard.stage is Stage.REVIEW and wizard.step is not Step.SAVE:
            wizard.retry()
        elif ch == "f" and wizard.can_fallback():
            wizard.fallback()
        elif ch == "p" and wizard.step is Step.VALIDATION:
            wizard.back_to_placement()
        elif ch == "v" and wizard.step is Step.VALIDATION:
            wizard.skip_validation()
        elif wizard.step is Step.ZONE_PLACEMENT and wizard.stage is Stage.REVIEW:
            d = wizard.settings.nudge_step
            moves = {"i": (0.0, -d), "k": (0.0, d), "j": (-d, 0.0), "l": (d, 0.0)}
            if ch == "n":
                return f"selected {wizard.select_next_zone()}"
            if ch in moves:
                wizard.nudge(wizard.selected_zone_id, *moves[ch])
            elif ch == "s" and samples:
                zone = wizard.selected_zone_id
                current = next(z["sample_id"] for z in wizard.display_zones() if z["zone_id"] == zone)
                nxt = (
                    samples[(samples.index(current) + 1) % len(samples)] if current in samples else samples[0]
                )
                wizard.set_sample(zone, nxt)
                return f"{zone} sound -> {nxt}"
    except (CalibrationError, LayoutError) as exc:
        return str(exc)
    return None


def run_autopilot(wizard: CalibrationWizard, *, skip_validation: bool) -> None:
    """Unattended decisions until the wizard needs frames again (a data window) or is done."""
    while not wizard.done and wizard.stage not in (Stage.COUNTDOWN, Stage.COLLECT):
        if autopilot(wizard, skip_validation=skip_validation) is None:
            return


def check(args: argparse.Namespace) -> int:
    cfg = base_config(args.config)
    calib = load_calibration(args.check)
    triggers = recalibration_triggers(calib, cfg, user_request=args.recalibrate)
    print(f"[calibrate] {args.check}: {calib.calibration_id} {calib.hash}")
    for t in triggers:
        print(f"[calibrate] trigger {t['code']}: {t['detail']}")
    print("[calibrate] " + ("RE-CALIBRATION REQUIRED" if triggers else "calibration valid for this setup"))
    return 3 if triggers else 0


def run(args: argparse.Namespace) -> dict[str, Any]:
    cfg = base_config(args.config)
    kind = (
        ProvenanceKind.SYNTHETIC
        if args.synthetic
        else ProvenanceKind.DEVELOPER_REPLAY
        if args.source == "replay"
        else ProvenanceKind.PARTICIPANT_LIVE
        if args.participant
        else ProvenanceKind.DEVELOPER_LIVE
    )
    if args.scope == "USER" and not args.user_tag:
        raise SystemExit("--scope USER needs --user-tag <pseudonym> (never a real name)")
    if args.scope == "SETUP" and not args.setup_tag:
        raise SystemExit("--scope SETUP needs --setup-tag")
    output = Path(args.output) if args.output else default_output(args, kind)
    if kind is ProvenanceKind.PARTICIPANT_LIVE and (ROOT / "configs") in output.resolve().parents:
        raise SystemExit("participant calibrations are stored under data/, never in configs/")
    note = args.note
    if output.exists():
        old = load_calibration(output)
        triggers = recalibration_triggers(old, cfg, user_request=args.recalibrate)
        if not triggers and not args.recalibrate:
            raise SystemExit(f"{output} is still valid for this setup; pass --recalibrate to replace it")
        codes = ",".join(t["code"] for t in triggers)
        note = (note + " " if note else "") + f"replaces {old.hash} ({codes})"
    settings = WizardSettings.load(args.settings)
    if args.window_scale != 1.0:
        scaled = settings.to_dict()
        for key in SCALED:
            scaled[key] = scaled[key] * args.window_scale
        settings = WizardSettings.from_dict(scaled)
        note = (note + " " if note else "") + f"windows scaled x{args.window_scale}"
    template = Template.load(args.layout)
    sha, dirty = git_state()
    stamp = timing.wall_clock_local_compact()
    tag = args.user_tag if args.scope == "USER" else args.setup_tag
    wizard = CalibrationWizard(
        cfg,
        template,
        settings,
        calibration_id=args.calibration_id or f"{args.scope.lower()}-{tag}-{stamp}",
        created_at=timing.wall_clock_iso(),
        provenance={
            "kind": str(kind),
            "scope": args.scope,
            "user_tag": args.user_tag,
            "setup_tag": args.setup_tag,
            "hardware_id": args.hardware_id,
            "operator_note": note,
        },
        app={"version": spacedrums.__version__, "git_sha": sha, "git_dirty": dirty},
        fit_mode=args.fit_mode,
        nudges=_parse_pairs(args.nudge, "nudge"),
        sample_overrides=_parse_pairs(args.sample, "sample"),
        available_samples=available_samples(cfg),
        clock="synthetic" if args.synthetic else "replay" if args.source == "replay" else "t_mono",
    )
    partial = output.with_name(output.name + ".partial.json")
    if args.resume:
        wizard.restore(json.loads(partial.read_text(encoding="utf-8")))
        print(f"[calibrate] resumed {wizard.calibration_id} at step {wizard.step}")
    samples = available_samples(cfg)
    audio = None
    if kind in (ProvenanceKind.DEVELOPER_LIVE, ProvenanceKind.PARTICIPANT_LIVE) and not args.no_audio:
        audio = AudioOutput(cfg, latency=OutputLatency.unmeasured(), device_enabled=True)
    session_id = f"calib-{wizard.calibration_id}"
    zones = wizard.required_zones()
    pipe = build_pipeline(cfg, zones, audio=audio, session_id=session_id, hardware_id=args.hardware_id)
    actor = frames = perception = None

    def stop() -> None:
        return None

    source_meta: dict[str, Any] = {"source": "synthetic" if args.synthetic else args.source}
    if args.synthetic:
        actor = SyntheticUser(
            cfg,
            seed=args.seed,
            noise=args.synthetic_noise,
            support_noise=args.synthetic_support_noise,
            presence=args.synthetic_presence,
        )
        source_meta.update(label="SYNTHETIC", seed=args.seed, noise=args.synthetic_noise)
    else:
        ns = argparse.Namespace(
            synthetic=None,
            source=args.source,
            capture=None,
            session_dir=args.session_dir,
            max_frames=None,
            max_seconds=None,
        )
        resolved = ResolvedConfig(cfg, config_hash(cfg), tuple(str(p) for p in args.config))
        frames, stop, meta, _truth = iter_source(ns, resolved, ZoneRegistry.from_config(zones))
        source_meta.update(meta)
        perception = WizardPerception(cfg)
    roi = Roi.from_rect(cfg["roi"]["px"])
    replay_like = args.synthetic or args.source == "replay"
    # without a window there are no key presses: headless runs are unattended
    auto = args.auto or args.synthetic or args.source == "replay" or args.no_window
    skip = args.skip_validation or kind is ProvenanceKind.DEVELOPER_REPLAY
    window = not args.no_window and not args.synthetic
    l_prior = None
    n = 0
    status: list[str] = []
    try:
        if audio is not None:
            audio.start()
        if window:
            cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        while not wizard.done:
            view = None
            if actor is not None:
                sample, obs, sticks, gray = actor.frame(wizard)
            else:
                item = next(frames, None)
                if item is None:
                    break
                sample, view, _ = item
                obs = perception(view)
                sticks = perception.stick_samples()
                gray = float(np.mean(view.roi)) if wizard.step is Step.CAMERA_CHECK else None
            required = wizard.required_zones()
            if required != zones:
                zones = required
                pipe = build_pipeline(
                    cfg, zones, audio=audio, session_id=session_id, hardware_id=args.hardware_id
                )
            lp = wizard.required_l_prior()
            if perception is not None and lp is not None and lp != l_prior:
                l_prior = lp
                perception.set_l_prior_by_hand(lp)
            result = pipe.step(sample, obs, t_now=sample.t_frame_available if replay_like else None)
            wizard.update(
                WizardFrame(
                    sample,
                    {h: obs[h][0] for h in HANDS},
                    sticks,
                    {h: result.hands[h].track for h in HANDS},
                    tuple(c for c in result.commits if not c.shadow),
                    gray,
                )
            )
            before = (wizard.step_index, wizard.stage)
            if auto:
                run_autopilot(wizard, skip_validation=skip)
            if window:
                img = draw_wizard(
                    view.full if view is not None else None,
                    roi,
                    to_view(wizard, status),
                    frame_size=tuple(cfg["camera_profile"]["resolution_px"]),
                )
                cv2.imshow(WINDOW, img)
                key = cv2.waitKey(1) & 0xFF
                if key != 255:
                    message = handle_key(wizard, key, samples)
                    if message == "quit":
                        break
                    status = [message] if message else status
            if wizard.step_index != before[0] and not wizard.done:
                partial.parent.mkdir(parents=True, exist_ok=True)
                partial.write_text(json.dumps(wizard.snapshot(), indent=2) + "\n", encoding="utf-8")
            n += 1
            if args.max_frames is not None and n >= args.max_frames:
                break
    finally:
        stop()
        if audio is not None:
            audio.stop()
        if perception is not None:
            perception.close()
        if window:
            cv2.destroyAllWindows()
            cv2.waitKey(1)
    summary: dict[str, Any] = {
        "frames": n,
        "source": source_meta,
        "provenance_kind": str(kind),
        "output": str(output),
    }
    if not wizard.done:
        if wizard.outcomes:
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_text(json.dumps(wizard.snapshot(), indent=2) + "\n", encoding="utf-8")
        summary.update(
            status="INCOMPLETE", step=str(wizard.step), partial=str(partial) if wizard.outcomes else None
        )
        print(
            f"[calibrate] wizard incomplete at {wizard.step}: NO calibration written. Sessions run "
            "UNCALIBRATED with the config's default layout until the wizard completes (--resume continues)."
        )
        return summary
    calib = save_calibration(wizard.document, output)
    if partial.exists():
        partial.unlink()
    doc = calib.doc
    summary.update(
        status="SAVED",
        calibration_id=calib.calibration_id,
        calibration_hash=calib.hash,
        l_prior=doc["stick_prior"]["l_prior"],
        fit={k: doc["layout"]["fit"][k] for k in ("mode", "scale", "translate")},
        steps={k: doc[k]["status"] for k in ("playing_area", "stick_prior", "reach_envelope", "validation")},
        validation=doc["validation"]["per_zone"],
        durations_s=doc["durations_s"],
    )
    print(f"[calibrate] saved {output} ({calib.hash})")
    print(
        f"[calibrate] L_prior {doc['stick_prior']['l_prior']} | fit {summary['fit']} | "
        f"validation {doc['validation']['status']} passed={doc['validation']['passed']}"
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", nargs="+", type=Path, default=[DEFAULT_CONFIG])
    ap.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS, help="wizard settings (candidates)")
    ap.add_argument(
        "--layout", default="mvp4", help="template: mvp4 | v1-7 | a Phase 04 layout fragment path"
    )
    ap.add_argument("--fit-mode", choices=("ENVELOPE", "FIXED"), default="ENVELOPE")
    ap.add_argument("--nudge", action="append", help="zone=dx,dy (ROI units, bounded by max_nudge)")
    ap.add_argument("--sample", action="append", help="zone=sample_id (REQ-056 sound choice)")
    ap.add_argument("--scope", choices=("USER", "SETUP"), default="USER")
    ap.add_argument("--user-tag", default=None, help="pseudonym (never a real name)")
    ap.add_argument("--setup-tag", default=None)
    ap.add_argument(
        "--participant", action="store_true", help="Phase 18 participant calibration (data/ only)"
    )
    ap.add_argument("--output", type=Path, default=None)
    ap.add_argument("--calibration-id", default=None)
    ap.add_argument("--note", default="")
    ap.add_argument("--source", choices=("live", "replay"), default="live")
    ap.add_argument("--session-dir", type=Path, default=None, help="recorded frames for --source replay")
    ap.add_argument("--synthetic", action="store_true", help="SYNTHETIC scripted actor (never evidence)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--synthetic-noise", type=float, default=0.0)
    ap.add_argument("--synthetic-support-noise", type=float, default=0.0)
    ap.add_argument("--synthetic-presence", type=float, default=1.0)
    ap.add_argument(
        "--window-scale", type=float, default=1.0, help="scale every data window (replay diagnostics)"
    )
    ap.add_argument("--auto", action="store_true", help="unattended: start/accept automatically")
    ap.add_argument("--skip-validation", action="store_true")
    ap.add_argument("--resume", action="store_true", help="continue from <output>.partial.json")
    ap.add_argument(
        "--recalibrate", action="store_true", help="user request: replace a still-valid calibration"
    )
    ap.add_argument("--check", type=Path, default=None, help="only report re-calibration triggers for a file")
    ap.add_argument("--no-window", action="store_true")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--hardware-id", default="HW-01")
    ap.add_argument("--summary-json", type=Path, default=None)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.check is not None:
            return check(args)
        summary = run(args)
    except CalibrationError as exc:
        print(f"[calibrate] refused: {exc}")
        return 2
    if args.summary_json is not None:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    return 0 if summary["status"] == "SAVED" else 1


if __name__ == "__main__":
    sys.exit(main())
