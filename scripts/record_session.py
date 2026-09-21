"""Phase 06 recording tool (Task 06.1): the Phase 05 prototype in record mode driven by the structured
recording protocol (Task 06.2), with segment markers, on-screen cues, session-start metadata options,
automatic file naming under ``data/raw/<participant>/<session_id>/``, a post-segment quick check, the
``SessionMetadata`` document (Task 06.4), optional microphone capture (Task 06.6) and, with
``--verify``, the post-session verification (Task 06.7).

Modes:

    python scripts/record_session.py --live --kind PARTICIPANT --participant P01 --consent-status SIGNED \
        --consent-record-id CF-P01-... --lighting L2 [...]   # PERSON-DEPENDENT: participant at the camera
    python scripts/record_session.py --live --kind PILOT --participant PILOT01 [...]  # PERSON-DEPENDENT pilot
    python scripts/record_session.py --live --kind DEV_CAPTURE --slug <slug>          # developer dry run
    python scripts/record_session.py --synthetic [--pad-zone snare] [--verify]        # SYNTHETIC self-test
    python scripts/record_session.py --devcapture swing-L2-exp-5 [--verify]     # DEV CAPTURE ingest check

``--synthetic`` runs the whole protocol on generated observations (no camera, no person, no pixels
beyond black frames) and, with ``--pad-zone``, a SYNTHETIC click track through the microphone-capture
path; it proves the machinery end to end and nothing else. ``--devcapture`` re-processes an existing
Phase 02 developer capture through the same path (DEV CAPTURE: real recorded frames, never
participant data). **No mode records a person unless ``--live`` is given, and ``--live`` refuses to
run without an explicit ``--kind``.** The pilot (Task 06.10) and the campaign (Task 06.11) are
PENDING until a person is recorded under the protocol with the ethics question answered.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _p06 import (  # noqa: E402
    DEFAULT_CONFIG,
    RAW_ROOT,
    ROOT,
    add_metadata_options,
    git_sha,
    metadata_from_args,
    session_naming,
    synthetic_protocol_sequence,
)
from _runlog import RunLog  # noqa: E402

from spacedrums import timing  # noqa: E402
from spacedrums.app.main import build_parser, run  # noqa: E402
from spacedrums.config import load_config  # noqa: E402
from spacedrums.data.audio_capture import (  # noqa: E402
    AudioCapture,
    onsets_on_t_mono,
    sync_check,
    synthetic_clicks,
)
from spacedrums.data.metadata import SessionKind, classification_label  # noqa: E402
from spacedrums.data.protocol import PROTOCOL_VERSION, build_protocol  # noqa: E402
from spacedrums.data.recorder import GuidedRecorder, QuickCheckThresholds  # noqa: E402
from spacedrums.data.validation import VerifyThresholds, format_verdict, verify_session  # noqa: E402
from spacedrums.geometry import ZoneRegistry  # noqa: E402


def build_cli() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true", help="PERSON-DEPENDENT: record with the camera")
    mode.add_argument(
        "--synthetic", action="store_true", help="SYNTHETIC full-protocol self-test (no camera)"
    )
    mode.add_argument(
        "--devcapture",
        default=None,
        metavar="NAME",
        help="DEV CAPTURE ingest check on data/dev-captures/<NAME>",
    )
    ap.add_argument(
        "--kind", choices=("PARTICIPANT", "PILOT", "DEV_CAPTURE"), default=None, help="required with --live"
    )
    ap.add_argument("--slug", default=None, help="session slug for DEV_CAPTURE / SYNTHETIC sessions")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument(
        "--output-root",
        type=Path,
        default=RAW_ROOT,
        help="data/raw (sessions go to <root>/<participant>/<session_id>)",
    )
    ap.add_argument(
        "--arm",
        choices=("A", "B"),
        default="A",
        help="active (sounding) arm; recorded in the metadata (Open Question: A only for v1.0)",
    )
    ap.add_argument("--pad-zone", default=None, help="enable the optional pad+mic segment on this zone")
    ap.add_argument(
        "--mic-device", default=None, help="sounddevice input device (name or index) for the pad condition"
    )
    ap.add_argument("--mic-rate", type=int, default=48000)
    ap.add_argument(
        "--free-play", action="store_true", help="enable the optional free-play segment (Open Question Q47)"
    )
    ap.add_argument("--no-distance-variation", action="store_true")
    ap.add_argument("--no-lighting-variation", action="store_true")
    ap.add_argument(
        "--duration-scale",
        type=float,
        default=None,
        help="scale every candidate segment duration (default 1.0 live, 0.1 synthetic/devcapture)",
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=None,
        help="protocol zone-order seed (default: from pseudonym + session index)",
    )
    ap.add_argument("--synthetic-noise", type=float, default=0.0)
    ap.add_argument("--synthetic-seed", type=int, default=0)
    ap.add_argument("--hardware-id", default="HW-01")
    ap.add_argument("--verify", action="store_true", help="run verify_session on the recorded session")
    ap.add_argument("--thresholds", type=Path, default=None, help="YAML with VerifyThresholds overrides")
    ap.add_argument(
        "--experiments-dir",
        type=Path,
        default=None,
        help="experiment-log directory (synthetic / devcapture runs)",
    )
    ap.add_argument(
        "--no-runlog", action="store_true", help="do not write an experiment run (synthetic / devcapture)"
    )
    ap.add_argument(
        "--keep-temp",
        action="store_true",
        help="synthetic: keep the session under --output-root instead of a temp dir",
    )
    ap.add_argument("--max-frames", type=int, default=None)
    add_metadata_options(ap)
    return ap


def _kind(args: argparse.Namespace) -> SessionKind:
    if args.synthetic:
        return SessionKind.SYNTHETIC
    if args.devcapture:
        return SessionKind.DEV_CAPTURE
    if args.kind is None:
        raise SystemExit(
            "--live needs an explicit --kind PARTICIPANT | PILOT | DEV_CAPTURE "
            "(no session is recorded by default)"
        )
    return SessionKind(args.kind)


def record(args: argparse.Namespace) -> dict[str, Any]:
    kind = _kind(args)
    cfg = load_config(args.config)
    registry = ZoneRegistry.from_config(cfg["zones"])
    zone_ids = [z.zone_id for z in registry]
    pad_zone = args.pad_zone
    if pad_zone is not None and pad_zone not in zone_ids:
        raise SystemExit(f"--pad-zone {pad_zone!r} is not a configured zone {zone_ids}")
    scale = args.duration_scale if args.duration_scale is not None else (1.0 if args.live else 0.1)
    if kind in (SessionKind.PARTICIPANT, SessionKind.PILOT) and not args.participant:
        raise SystemExit(f"{kind} sessions need --participant (pseudonym)")
    slug = args.slug or (
        f"protocol-{timing.wall_clock_local_compact()}"
        if args.synthetic
        else (args.devcapture or f"live-{timing.wall_clock_local_compact()}")
    )
    session_id = session_naming(kind, args, slug)
    from spacedrums.data.metadata import participant_id_for

    pid = participant_id_for(kind, args.participant)
    protocol = build_protocol(
        zone_ids,
        participant_id=pid,
        session_index=args.session_index,
        seed=args.seed,
        include_distance_variation=not args.no_distance_variation,
        include_lighting_variation=not args.no_lighting_variation,
        include_pad_mic=pad_zone is not None,
        pad_zone_id=pad_zone,
        include_free_play=args.free_play,
        duration_scale=scale,
    )
    print(f"[record] {session_id} [{kind}] :: {classification_label(kind)}")
    print(
        f"[record] protocol {protocol.protocol_id} v{protocol.version}, {len(protocol.segments)} segments, "
        f"candidate total {protocol.total_duration_s:.0f} s, zone order {list(protocol.zone_order)} "
        f"(seed {protocol.seed})"
    )
    if args.live:
        print(
            "[record] LIVE MODE: person-dependent. Ethics status: see docs/ethics/ethics-approval-note.md "
            "(Open Question) - no participant/pilot session may be recorded before it is answered."
        )

    out_root = Path(args.output_root)
    temp_root: Path | None = None
    if args.synthetic and not args.keep_temp:
        temp_root = Path(tempfile.mkdtemp(prefix="p06-synthetic-"))
        out_root = temp_root
    output_dir = out_root / pid

    # --- source ------------------------------------------------------------------------------
    source_block: dict[str, Any]
    argv = [
        "--config",
        str(args.config),
        "--record",
        "--output-dir",
        str(output_dir),
        "--session-id",
        session_id,
        "--arm",
        args.arm,
    ]
    if args.max_frames is not None:
        argv += ["--max-frames", str(args.max_frames)]
    source_factory = None
    truth_holder: dict[str, Any] = {}
    if args.synthetic:
        argv += ["--no-window", "--no-audio"]
        source_block = {
            "kind": "SYNTHETIC",
            "detail": {
                "generator": "scripts/_p06.synthetic_protocol_sequence",
                "seed": args.synthetic_seed,
                "noise": args.synthetic_noise,
            },
        }

        def source_factory(app_args, cfg_, registry_):  # noqa: ANN001
            seq = synthetic_protocol_sequence(
                protocol,
                registry_,
                seed=args.synthetic_seed,
                noise=args.synthetic_noise,
                enable_optional=pad_zone is not None or args.free_play,
            )
            truth_holder["truth"] = [t.to_dict() for t in seq.truth]

            def gen():
                for sample, obs in seq:
                    yield sample, None, obs

            return (
                gen(),
                (lambda: None),
                {"source": "synthetic", "label": "SYNTHETIC", **seq.params},
                truth_holder["truth"],
            )

    elif args.devcapture:
        argv += ["--source", "devcapture", "--capture", args.devcapture, "--no-window", "--no-audio"]
        source_block = {
            "kind": "REPLAY",
            "detail": {
                "dev_capture": args.devcapture,
                "path": str(ROOT / "data" / "dev-captures" / args.devcapture),
            },
        }
    else:
        argv += ["--source", "live"]
        source_block = {"kind": "LIVE", "detail": {"note": "camera session (person-dependent)"}}
    app_args = build_parser().parse_args(argv)
    if args.synthetic:
        app_args.synthetic = (
            "protocol"  # no perception, no audio device; iter_source is replaced by the factory
        )

    # --- metadata + guided recorder ---------------------------------------------------------
    git = git_sha()
    meta = metadata_from_args(
        args,
        kind=kind,
        session_id=session_id,
        cfg=cfg,
        protocol=protocol,
        source=source_block,
        git=git,
        arm_active=args.arm,
        arms_shadow=[a for a in ("A", "B") if a != args.arm],
        t_mono_at_start=timing.now(),
        store_crop=cfg["debug"]["record_mode"]["store_crop"],
        pad_zone_id=pad_zone,
    )
    nominal_fps = cfg["camera_profile"].get("requested_fps")
    nfm = cfg["camera_profile"].get("native_fps_measured")
    if isinstance(nfm, dict) and nfm.get("value_fps"):
        nominal_fps = nfm["value_fps"]
    recorder = GuidedRecorder(
        protocol,
        meta,
        thresholds=QuickCheckThresholds(nominal_fps=float(nominal_fps) if nominal_fps else None),
        enable_optional=pad_zone is not None or args.free_play,
    )
    audio: AudioCapture | None = None
    if args.live and pad_zone is not None:
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
        return recorder.on_frame(sample, result)

    summary = run(
        app_args,
        on_frame=on_frame,
        status_lines=recorder.status_lines,
        draw_hook=recorder.draw_cues,
        on_key=recorder.on_key,
        source_factory=source_factory,
        session_meta={
            "phase06": {
                "protocol_version": PROTOCOL_VERSION,
                "session_kind": str(kind),
                "metadata": "metadata.json",
            }
        },
    )
    session_dir = Path(summary["session_dir"])
    recorder.finish()
    src_meta = summary.get("source", {}) or {}
    meta.finish(
        timing.wall_clock_iso(),
        capture_stats=src_meta.get("capture_stats") if kind is not SessionKind.SYNTHETIC else None,
    )

    # --- microphone track ---------------------------------------------------------------------
    if audio is not None:
        audio.stop()
        info = audio.write(session_dir)
        residual = _residual(meta, audio, info)
        meta.set_audio_track(info, residual)
    elif args.synthetic and pad_zone is not None:
        _synthetic_audio(meta, session_dir, args.mic_rate, args.synthetic_seed)
    meta.write(session_dir)
    print(
        f"[record] metadata.json written: session_kind={meta.data['session_kind']} "
        f"has_phys_gt={meta.data['has_phys_gt']} "
        f"segments={len(meta.data['segments'])}"
    )

    result: dict[str, Any] = {
        "session_id": session_id,
        "session_kind": str(kind),
        "label": classification_label(kind),
        "session_dir": str(session_dir),
        "frames": summary["frames"],
        "segments": [
            {k: s[k] for k in ("segment_id", "type", "take", "status", "t_start", "t_end", "quick_check")}
            for s in meta.data["segments"]
        ],
        "has_phys_gt": meta.data["has_phys_gt"],
        "protocol": {
            "version": protocol.version,
            "seed": protocol.seed,
            "zone_order": list(protocol.zone_order),
            "n_segments": len(protocol.segments),
        },
        "synthetic_truth_n": len(truth_holder.get("truth", [])),
        "commits_during_non_valid": summary.get("session_summary", {}).get("commits_during_non_valid"),
    }
    if args.verify:
        th = VerifyThresholds.from_file(args.thresholds) if args.thresholds else VerifyThresholds()
        doc = verify_session(session_dir, thresholds=th, git_sha=git)
        print(format_verdict(doc))
        result["verify"] = {
            "verdict": doc["verdict"],
            "reasons": doc["reasons"],
            "checks": {c["id"]: c["status"] for c in doc["checks"]},
            "quality": doc["quality"],
            "segments": doc["segments"],
            "sync": doc["sync"],
        }
    result["temp_root"] = str(temp_root) if temp_root else None
    return result


def _residual(meta, audio: AudioCapture, info: dict[str, Any]) -> float | None:  # noqa: ANN001
    markers = [m["t_mono"] for m in meta.data["pad_mic"]["sync_markers"]]
    if not markers or info["t_mono_first_sample"] is None:
        return None
    onsets = onsets_on_t_mono(audio.samples(), info["sample_rate_hz"], info["t_mono_first_sample"])
    res = sync_check(markers, onsets)
    return res.residual_rms_s


def _synthetic_audio(meta, session_dir: Path, rate: int, seed: int) -> None:  # noqa: ANN001
    """SYNTHETIC click track for the pad segment: markers 0.5 s inside the PAD take, clicks 12 ms
    after each marker (a fixed 'operator reaction' offset), blocks fed through the same on_block path
    a microphone would use, with a simulated device clock (offset -1000 s, slope 1). Machinery
    evidence only: no microphone latency or sync accuracy is measured here (pilot PENDING)."""
    pad_takes = [s for s in meta.data["segments"] if s["condition"] == "PAD" and s["t_end"] is not None]
    if not pad_takes:
        return
    take = pad_takes[-1]
    t0 = meta.data["t_mono_at_start"]
    quarter = 0.25 * (take["t_end"] - take["t_start"])  # markers at 25 % / 75 % of the take
    marker_ts = [take["t_start"] + quarter, take["t_end"] - quarter]
    for t in marker_ts:
        meta.add_sync_marker("CLAP", t, take["segment_id"], "SYNTHETIC marker")
    t_last = max(s["t_end"] for s in meta.data["segments"] if s["t_end"] is not None)
    duration = (t_last - t0) + 0.5
    offset = 0.012
    x = synthetic_clicks(rate, duration, [t - t0 + offset for t in marker_ts], seed=seed)
    cap = AudioCapture(sample_rate_hz=rate, channels=1, device="SYNTHETIC")
    cap.device_name = "SYNTHETIC click generator (no microphone)"
    block = 1024
    for i in range(0, len(x), block):
        t_block = t0 + i / rate
        cap.on_block(
            x[i : i + block],
            adc_time=t_block - 1000.0,
            current_time=t_block - 1000.0 + 0.010,
            t_mono_now=t_block + 0.010,
        )
    info = cap.write(session_dir)
    onsets = onsets_on_t_mono(cap.samples(), rate, info["t_mono_first_sample"])
    res = sync_check(marker_ts, onsets)
    meta.set_audio_track(info, res.residual_rms_s)
    meta.data["operator_notes"] = (
        meta.data["operator_notes"] + " " if meta.data["operator_notes"] else ""
    ) + (
        "SYNTHETIC audio track: generated clicks, no microphone; sync residual is a machinery check, "
        "not a measurement."
    )


def main(argv: list[str] | None = None) -> int:
    args = build_cli().parse_args(argv)
    if args.live or args.no_runlog:
        result = record(args)
        print(json.dumps({k: v for k, v in result.items() if k not in ("segments",)}, indent=2, default=str))
        if args.live:
            print(
                "[record] Live session recorded. Run scripts/verify_session.py on the session directory, "
                "then "
                "scripts/build_raw_manifest.py. This recording is " + result["label"]
            )
        return 0
    cfg = load_config(args.config)
    label = "SYNTHETIC" if args.synthetic else "DEV CAPTURE"
    slug = "p06-record-synthetic" if args.synthetic else "p06-record-devcapture"
    desc = (
        f"Task 06.1/06.10 {label} self-test of the recording tool: the full draft protocol "
        f"(v{PROTOCOL_VERSION}) through the prototype pipeline in record mode with segment markers, "
        "quick checks, SessionMetadata and (optionally) verification. Machinery evidence only - NOT a pilot, "
        "NOT participant data; pilot measurements remain PENDING."
    )
    with RunLog(
        phase="06",
        task="06.10",
        slug=slug,
        config=cfg,
        experiments_dir=args.experiments_dir,
        description=desc,
        arm=args.arm,
    ) as runlog:
        result = record(args)
        runlog.write_json_artefact(
            "record_session.json",
            {"label": f"{label} - machinery self-test; not a pilot, not participant evidence", **result},
        )
        sd = Path(result["session_dir"])
        for name in ("metadata.json", "verify.json"):
            if (sd / name).exists():
                shutil.copy(sd / name, runlog.dir / name)
                runlog.add_artefact(runlog.dir / name, "table")
        metrics = {
            "label": label,
            "frames": result["frames"],
            "n_segments_recorded": len(result["segments"]),
            "commits_during_non_valid": result.get("commits_during_non_valid"),
            "verdict": result.get("verify", {}).get("verdict"),
        }
        runlog.finish(metrics)
        print(
            f"\nRESULT: COMPLETED {runlog.run_id} ({label} self-test - machinery evidence only; "
            "the pilot measurements of Task 06.10 and the campaign of Task 06.11 remain PENDING)"
        )
    if result.get("temp_root"):
        shutil.rmtree(result["temp_root"], ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
