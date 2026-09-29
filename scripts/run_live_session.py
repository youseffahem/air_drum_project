"""Phase 18 Task 18.4: one live-experiment session (Experiment 2), or its SYNTHETIC rehearsal.

    python scripts/run_live_session.py --live --kind PARTICIPANT --participant P01 --participant-index 1 \
        --consent-status SIGNED --consent-record-id CF-LIVE-P01-... --calibration configs/calibration/<f> \
        [--pad-zone snare --mic-device <input>] [--overlap-with-dataset YES|NO|NOT_COLLECTED]  # PERSON
    python scripts/run_live_session.py --live --kind DEV_CAPTURE --slug pilot ...  # developer pilot (PERSON)
    python scripts/run_live_session.py --synthetic --participant-index 1 --pad-zone snare --synthetic-mic

A session is the Phase 06 guided recording, driven by the live protocol:

* familiarisation;
* one AIR block per arm in the Williams order given by ``--participant-index``;
* one PAD block per arm, when ``--pad-zone`` is set.

The unchanged application runs with all three arms, one sounding and two in shadow.
``ArmSwitcher`` makes each block's arm the sounding arm on the block's first frame. The participant
view is blinded: overlay off, zones and cues only, no arm name. The operator console prints every
switch.

Outputs, in the session directory:

* ``metadata.json``: Phase 06 ``SessionMetadata``, unchanged schema;
* ``live-session.json``: ``LiveSessionMetadata``, with blocks, switches, commits per arm, external
  methods and pre-registration provenance;
* the usual record streams, and the microphone track when a PAD block ran with ``--mic-device``.

**No mode records a person unless ``--live`` is given with an explicit ``--kind``.**
PILOT / PARTICIPANT sessions also need signed consent and the answered ethics question
(``docs/ethics/ethics-approval-note.md``: still an Open Question).
``--synthetic`` generates observations (no camera, no person, no audio device). With
``--synthetic-mic`` it also writes a SYNTHETIC M1 track built from the session's own truth and audio
events, which exercises ``external_sync.py`` and ``analyze_live.py`` end to end.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cv2  # noqa: E402
from _p06 import (
    add_metadata_options,
    git_sha,
    metadata_from_args,
    session_naming,
    synthetic_protocol_sequence,
)  # noqa: E402
from _p10 import write_json  # noqa: E402
from _p18 import (  # noqa: E402
    LIVE_CONFIG,
    PREREG_DOC,
    PREREG_PATH,
    RECORD_PATH,
    ROOT,
    add_executor_args,
    evidence,
)
from _p18_live import pad_windows, synthetic_microphone  # noqa: E402

from spacedrums import timing  # noqa: E402
from spacedrums.app.main import build_parser, run  # noqa: E402
from spacedrums.calib import load_calibrated_config  # noqa: E402
from spacedrums.contracts import Arm  # noqa: E402
from spacedrums.data.audio_capture import AudioCapture  # noqa: E402
from spacedrums.data.metadata import SessionKind, classification_label, participant_id_for  # noqa: E402
from spacedrums.data.recorder import GuidedRecorder, QuickCheckThresholds  # noqa: E402
from spacedrums.geometry import Ellipse, ZoneRegistry  # noqa: E402
from spacedrums.live_eval.metadata import LiveSessionMetadata  # noqa: E402
from spacedrums.live_eval.prereg import verify_document  # noqa: E402
from spacedrums.live_eval.protocol import ArmSwitcher, build_live_protocol  # noqa: E402
from spacedrums.ui import Canvas  # noqa: E402


def build_cli() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true", help="PERSON-DEPENDENT: record with the camera")
    mode.add_argument("--synthetic", action="store_true", help="SYNTHETIC rehearsal (no camera, no person)")
    ap.add_argument("--kind", choices=("PARTICIPANT", "PILOT", "DEV_CAPTURE"), default=None)
    ap.add_argument(
        "--participant-index", type=int, required=True, help="1-based live participant index (arm order)"
    )
    ap.add_argument("--slug", default=None)
    ap.add_argument("--config", type=Path, default=LIVE_CONFIG)
    ap.add_argument(
        "--calibration", type=Path, default=None, help="Phase 14 calib-v1 file (required with --live)"
    )
    ap.add_argument("--pad-zone", default=None, help="enable the PAD blocks (M1) on this zone")
    ap.add_argument("--mic-device", default=None, help="microphone for M1 (sounddevice name or index)")
    ap.add_argument("--mic-rate", type=int, default=48000)
    ap.add_argument("--synthetic-mic", action="store_true", help="SYNTHETIC M1 track (with --synthetic)")
    ap.add_argument("--duration-scale", type=float, default=None, help="default 1.0 live, 0.1 synthetic")
    ap.add_argument("--overlap-with-dataset", choices=("YES", "NO", "NOT_COLLECTED"), default="NOT_COLLECTED")
    ap.add_argument("--questionnaire", choices=("included", "not-included", "undecided"), default="undecided")
    ap.add_argument("--unblinded", action="store_true", help="operator overlay (records UNBLINDED)")
    ap.add_argument("--hardware-id", default="HW-01")
    ap.add_argument("--output", type=Path, default=ROOT / "experiments" / "phase-18")
    ap.add_argument("--output-root", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--max-frames", type=int, default=None)
    add_metadata_options(ap)
    add_executor_args(ap)
    return ap


def _kind(args: argparse.Namespace) -> SessionKind:
    if args.synthetic:
        return SessionKind.SYNTHETIC
    if args.kind is None:
        raise SystemExit("--live needs an explicit --kind PARTICIPANT | PILOT | DEV_CAPTURE")
    if args.calibration is None:
        raise SystemExit("--live needs --calibration (Phase 14 wizard output; pre-registration §9)")
    return SessionKind(args.kind)


def blinded_draw(recorder: GuidedRecorder):
    """Participant view: every zone outlined, the cued zone highlighted; nothing about the arm."""

    def draw(roi: Canvas, registry: ZoneRegistry) -> None:
        h, w = roi.height, roi.width
        for zone in registry:
            if isinstance(zone.shape, Ellipse):
                c = (round(zone.shape.center[0] * (w - 1)), round(zone.shape.center[1] * (h - 1)))
                axes = (max(1, round(zone.shape.rx * w)), max(1, round(zone.shape.ry * h)))
                roi.ellipse(c, axes, 0, 0, 360, (200, 200, 200), 1, cv2.LINE_AA)
        recorder.draw_cues(roi, registry)

    return draw


def record(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    kind = _kind(args)
    calibrated = load_calibrated_config(args.config, calibration=args.calibration)
    cfg = calibrated.config
    registry = ZoneRegistry.from_config(cfg["zones"])
    zone_ids = [z.zone_id for z in registry]
    pid = participant_id_for(kind, args.participant)
    scale = args.duration_scale if args.duration_scale is not None else (1.0 if args.live else 0.1)
    live = build_live_protocol(
        zone_ids,
        participant_index=args.participant_index,
        participant_id=pid,
        session_index=args.session_index,
        pad_zone_id=args.pad_zone,
        duration_scale=scale,
    )
    protocol = live.protocol
    slug = args.slug or f"live-{timing.wall_clock_local_compact()}"
    session_id = session_naming(kind, args, slug)
    model_label = Arm("C-" + cfg["anticipator"]["model"]["family"].upper())
    print(f"[live] {session_id} [{kind}] :: {classification_label(kind)}")
    print(
        f"[live] operator: arm order {live.order['order']} "
        f"(Williams sequence {live.order['sequence_index']}), "
        f"C = {model_label}; participant view {'UNBLINDED' if args.unblinded else 'BLINDED'}"
    )
    out_root = (
        Path(tempfile.mkdtemp(prefix="p18-synthetic-", dir=run_dir)) if args.synthetic else args.output_root
    )
    argv = [
        "--config",
        str(args.config),
        "--record",
        "--output-dir",
        str(out_root / pid),
        "--session-id",
        session_id,
        "--arm",
        "A",
        "--shadow",
        "B",
        str(model_label),
        "--overlay-mode",
        "experiment" if args.unblinded else "off",
        "--hardware-id",
        args.hardware_id,
    ]
    if args.calibration is not None:
        argv += ["--calibration", str(args.calibration)]
    if args.max_frames is not None:
        argv += ["--max-frames", str(args.max_frames)]
    source_factory, truth_holder = None, {}
    if args.synthetic:
        argv += ["--no-window", "--no-audio"]
        source = {
            "kind": "SYNTHETIC",
            "detail": {"generator": "scripts/_p06.synthetic_protocol_sequence", "seed": 18},
        }

        def source_factory(app_args, cfg_, registry_):  # noqa: ANN001
            seq = synthetic_protocol_sequence(
                protocol, registry_, seed=18, noise=0.0, enable_optional=args.pad_zone is not None
            )
            truth_holder["truth"] = [t.to_dict() for t in seq.truth]
            return (
                ((s, None, o) for s, o in seq),
                (lambda: None),
                {"source": "synthetic", **seq.params},
                truth_holder["truth"],
            )
    else:
        argv += ["--source", "live"]
        source = {"kind": "LIVE", "detail": {"note": "camera session (person-dependent)"}}
    app_args = build_parser().parse_args(argv)
    if args.synthetic:
        app_args.synthetic = "protocol"
    meta = metadata_from_args(
        args,
        kind=kind,
        session_id=session_id,
        cfg=cfg,
        protocol=protocol,
        source=source,
        git=git_sha(),
        arm_active="A",
        arms_shadow=["B", str(model_label)],
        t_mono_at_start=timing.now(),
        store_crop=cfg["debug"]["record_mode"]["store_crop"],
        pad_zone_id=args.pad_zone,
    )
    meta.data.update(calibrated.session_fields())
    recorder = GuidedRecorder(
        protocol, meta, thresholds=QuickCheckThresholds(), enable_optional=args.pad_zone is not None
    )
    switcher = ArmSwitcher(live, {"A": Arm.A, "B": Arm.B, "C": model_label})
    audio = None
    if args.live and args.pad_zone is not None and args.mic_device is not None:
        audio = AudioCapture(sample_rate_hz=args.mic_rate, channels=1, device=args.mic_device)
        audio.start()
    first: dict[str, Any] = {}

    def on_frame(sample, result, pipeline) -> bool:  # noqa: ANN001
        if not first:
            first["t"] = float(sample.t_capture)
            meta.data["t_mono_at_start"] = float(sample.t_capture)
            meta.data["camera_profile_id"] = sample.camera_profile_id
            meta.data["roi_px"] = list(sample.roi_px)
            meta.data["video"]["frame_size_px"] = list(sample.frame_size_px)
        keep = recorder.on_frame(sample, result)
        spec = recorder.spec
        switcher.update(
            spec.segment_id if spec else None, pipeline, t_now=result.t_now, frame_id=sample.frame_id
        )
        return keep

    summary = run(
        app_args,
        on_frame=on_frame,
        status_lines=lambda: switcher.participant_lines(recorder.spec),
        draw_hook=blinded_draw(recorder),
        on_key=recorder.on_key,
        source_factory=source_factory,
        session_meta={
            "phase18": {"live_protocol": live.to_dict()["protocol_id"], "live_session": "live-session.json"}
        },
    )
    session_dir = Path(summary["session_dir"])
    recorder.finish()
    meta.data["arm_active"] = summary["active_arm_final"]
    meta.data["arms_shadow"] = summary["counters"]["shadow_arms"]
    meta.data["model_id"] = summary["counters"]["model"]["model_id"]
    meta.data["fallback_events"].extend(summary["counters"]["fallback_events"])
    meta.finish(
        timing.wall_clock_iso(),
        capture_stats=(summary.get("source") or {}).get("capture_stats") if args.live else None,
    )
    recordings = []
    if audio is not None:
        audio.stop()
        info = audio.write(session_dir)
        meta.set_audio_track(info, None)
        recordings.append(
            {
                "path": info["path"],
                "sha256": info["sha256"],
                "kind": "AUDIO",
                "rate": info["sample_rate_hz"],
                "device": info["device"],
                "t_mono_first_sample": info["t_mono_first_sample"],
            }
        )
    meta.write(session_dir)
    from spacedrums.live_eval.prereg import file_digest
    from spacedrums.live_eval.software import read_stream

    committed = read_stream(session_dir / "records" / "CommittedStrike.jsonl")[1]
    synthetic_mic = None
    if args.synthetic and args.synthetic_mic and args.pad_zone is not None:
        synthetic_mic = synthetic_microphone(
            session_dir, cfg, truth_holder.get("truth", []), pad_windows(meta.data)
        )
        recordings.append(
            {
                "path": synthetic_mic["path"],
                "sha256": file_digest(session_dir / synthetic_mic["path"]),
                "kind": "AUDIO",
                "rate": synthetic_mic["rate"],
                "device": synthetic_mic["device"],
                "t_mono_first_sample": synthetic_mic["t_mono_first_sample"],
                "synthetic": True,
            }
        )
    check = verify_document(PREREG_PATH, RECORD_PATH, document=PREREG_DOC)
    evidence_label = classification_label(kind)
    live_meta = LiveSessionMetadata.new(
        session_metadata=meta.data,
        live=live,
        prereg={"path": PREREG_DOC, "version": check.get("version"), "sha256": check.get("sha256")},
        lock=None,
        blinding={
            "participant_view": "UNBLINDED" if args.unblinded else "BLINDED",
            "overlay_mode": "experiment" if args.unblinded else "off",
            "note": "zones and cues only; arm names on the operator console; "
            "a model-fallback message can reveal C",
        },
        external_methods=[
            {
                "method": "M1",
                "status": "PENDING",
                "validation_ref": "docs/reports/phase-18-external-methods.md",
                "u_s": None,
                "recordings": recordings,
                "sync": None,
            },
            {
                "method": "M2",
                "status": "NOT_USED",
                "validation_ref": None,
                "u_s": None,
                "recordings": [],
                "sync": None,
            },
            {
                "method": "M3",
                "status": "ESTIMATE_ONLY",
                "validation_ref": None,
                "u_s": None,
                "recordings": [],
                "sync": None,
            },
        ],
        overlap_with_dataset="NOT_APPLICABLE"
        if kind in (SessionKind.SYNTHETIC, SessionKind.DEV_CAPTURE)
        else args.overlap_with_dataset,
        questionnaire={
            "included": {"included": True, "not-included": False}.get(args.questionnaire),
            "ref": "docs/protocols/phase-18-questionnaire.md" if args.questionnaire == "included" else None,
        },
        evidence_label=evidence_label,
        notes="SYNTHETIC rehearsal: generated observations and a generated M1 track; never evidence"
        if args.synthetic
        else "",
    )
    live_meta.close_blocks(meta.data["segments"], switcher.switches, committed, meta.data["fallback_events"])
    live_meta.write(session_dir)
    result = {
        "session_id": session_id,
        "session_dir": str(session_dir),
        "label": evidence_label,
        "frames": summary["frames"],
        "arm_order": live.order["order"],
        "switches": switcher.switches,
        "refused_switches": switcher.refused,
        "blocks": [
            {k: b[k] for k in ("block_id", "arm", "kind", "status", "commits_by_arm")}
            for b in live_meta.data["arm_blocks"]
        ],
        "synthetic_mic": synthetic_mic,
        "truth_n": len(truth_holder.get("truth", [])),
    }
    write_json(run_dir / "session-result.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_cli().parse_args(argv)
    if args.synthetic_mic and not args.synthetic:
        raise SystemExit("--synthetic-mic is a SYNTHETIC rehearsal option")
    if args.live and args.kind in ("PARTICIPANT", "PILOT") and args.consent_status != "SIGNED":
        raise SystemExit(
            "PILOT / PARTICIPANT live sessions need --consent-status SIGNED with a consent record id"
        )
    with evidence(
        args,
        slug="live-session" if args.live else "live-rehearsal",
        task="18.4",
        description="Experiment 2 live session"
        if args.live
        else "Experiment 2 SYNTHETIC rehearsal (machinery only)",
        output=args.output,
        config_path=args.config,
    ) as (run_log, _cfg):
        result = record(args, run_log.dir)
        print(
            f"[live] session {result['session_id']}: {result['frames']} frames, "
            f"switches {len(result['switches'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
