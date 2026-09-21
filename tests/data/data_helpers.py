"""Helpers for the Phase 06 ``spacedrums.data`` tests: build a small SYNTHETIC session on disk through
the real Phase 05 record mode + the Phase 06 guided recorder and metadata (no camera, no person).

Kept in a uniquely named module (not ``conftest``) because ``from conftest import …`` is
order-fragile across test directories (tests/README.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from spacedrums.app import AudioOutput, DecisionPipeline, OutputLatency, SessionRecorder
from spacedrums.app.synthetic import Swing, build_sequence
from spacedrums.config import load_config
from spacedrums.contracts import HandId
from spacedrums.data.metadata import ConsentStatus, SessionKind, SessionMetadata
from spacedrums.data.protocol import Protocol, SegmentSpec, SegmentType, build_protocol
from spacedrums.data.recorder import GuidedRecorder, QuickCheckThresholds
from spacedrums.geometry import ZoneRegistry

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "prototype.candidate.yaml"
GIT = "b" * 40


class Ticker:
    def __init__(self, start: float = 500.0, step: float = 0.001) -> None:
        self.t, self.step = start, step

    def __call__(self) -> float:
        self.t += self.step
        return self.t


def short_protocol(zone_ids, *, participant_id="SYNTHETIC", pad_zone: str | None = None) -> Protocol:
    """Three short segments (single hits R, fake swing, optional pad) — enough for every marker rule."""
    z1 = "snare" if "snare" in zone_ids else zone_ids[0]
    segs = [
        SegmentSpec(
            "s01_single", SegmentType.SINGLE_HITS, "SINGLE hits", 2.0, zone_ids=(z1,), hands=(HandId.RIGHT,)
        ),
        SegmentSpec(
            "s02_fake", SegmentType.FAKE_SWING, "FAKE swings", 1.5, zone_ids=(z1,), expects_strikes=False
        ),
    ]
    if pad_zone:
        segs.append(
            SegmentSpec(
                "s03_pad",
                SegmentType.PAD_MIC,
                "PAD",
                2.0,
                zone_ids=(pad_zone,),
                condition="PAD",
                pad_zone_id=pad_zone,
                core=False,
                optional=True,
            )
        )
    return Protocol(
        protocol_id="test-protocol",
        version="test",
        segments=tuple(segs),
        zone_order=tuple(zone_ids),
        seed=1,
        seed_source="explicit",
        options={"primary_zone": z1, "secondary_zone": zone_ids[1]},
    )


def synthetic_sequence(registry: ZoneRegistry, protocol: Protocol, *, seed: int = 3):
    """Swings matching the short protocol on its time slots (lead-in 0.2 s)."""
    t = 0.2
    swings = []
    for spec in protocol.segments:
        if spec.type is SegmentType.SINGLE_HITS or spec.type is SegmentType.PAD_MIC:
            swings += [Swing(HandId.RIGHT, spec.zone_ids[0], t + 0.3 + 0.7 * k) for k in range(2)]
        elif spec.type is SegmentType.FAKE_SWING:
            swings += [Swing(HandId.LEFT, spec.zone_ids[0], t + 0.3, depth=-0.03)]
        t += spec.duration_s
    return build_sequence(registry, swings, duration_s=t + 0.2, image=True, noise=0.002, seed=seed)


def make_session(
    out_root: Path,
    *,
    kind: SessionKind | str = SessionKind.SYNTHETIC,
    session_id: str = "synthetic-unit",
    participant_id: str | None = None,
    pad_zone: str | None = None,
    consent_status: str | None = None,
    consent_record_id: str | None = None,
    metadata_overrides: dict[str, Any] | None = None,
    seed: int = 3,
) -> tuple[Path, SessionMetadata, dict[str, Any]]:
    """Record a short SYNTHETIC protocol session under ``out_root/<participant>/<session_id>``."""
    kind = SessionKind(kind)
    cfg = load_config(CONFIG)
    registry = ZoneRegistry.from_config(cfg["zones"])
    zone_ids = [z.zone_id for z in registry]
    pid = participant_id or ("SYNTHETIC" if kind is SessionKind.SYNTHETIC else "DEV")
    protocol = short_protocol(zone_ids, participant_id=pid, pad_zone=pad_zone)
    seq = synthetic_sequence(registry, protocol, seed=seed)
    clk = Ticker()
    pipe = DecisionPipeline(
        cfg.data,
        registry=registry,
        session_id=session_id,
        active_arm="A",
        shadow_arms=("B",),
        hardware_id="HW-01",
        config_hash=cfg.config_hash,
        audio=AudioOutput(cfg.data, latency=OutputLatency.unmeasured(), device_enabled=False, clock=clk),
        clock=clk,
    )
    rec = SessionRecorder(
        out_root / pid,
        session_id=session_id,
        config=cfg,
        git_sha=GIT,
        producer="REPLAY",
        store_crop="FULL",
        extra_meta={"synthetic_truth": [t.to_dict() for t in seq.truth]},
    )
    first = seq.frames[0][0]
    meta = SessionMetadata.new(
        kind=kind,
        session_id=session_id,
        participant_id=pid,
        session_index=1,
        date="2026-09-21",
        started_at="2026-09-21T12:00:00+03:00",
        t_mono_at_start=first.t_capture,
        hardware_id="HW-01",
        camera_profile_id=first.camera_profile_id,
        audio_profile_id=cfg["audio"]["audio_profile_id"],
        roi_px=first.roi_px,
        config_hash=cfg.config_hash,
        git_sha=GIT,
        clock_id="perf_counter",
        zone_layout_id="mvp4",
        arm_active="A",
        arms_shadow=["B"],
        tip_method_active=cfg["stick"]["method_id"],
        protocol={
            "protocol_id": protocol.protocol_id,
            "version": protocol.version,
            "seed": protocol.seed,
            "seed_source": protocol.seed_source,
            "zone_order": list(protocol.zone_order),
            "options": protocol.options,
        },
        source={
            "kind": "SYNTHETIC" if kind is SessionKind.SYNTHETIC else "REPLAY",
            "detail": {"unit_test": True},
        },
        video={
            "container": "PNG_SEQUENCE",
            "codec": "png",
            "lossless": True,
            "crop": "FULL",
            "frame_size_px": list(first.frame_size_px),
            "parameters": {},
        },
        consent_status=consent_status,
        consent_record_id=consent_record_id,
        pad_zone_id=pad_zone,
    )
    guided = GuidedRecorder(
        protocol, meta, thresholds=QuickCheckThresholds(nominal_fps=30.0), enable_optional=True, log=None
    )
    results = []
    for sample, obs in seq:
        r = pipe.step(sample, obs, t_now=sample.t_frame_available)
        rec.write_frame(sample, sample.image_ref.array, r, obs)
        results.append(r)
        if not guided.on_frame(sample, r):
            pass  # keep recording frames after the protocol ends (tail frames outside segments)
    guided.finish()
    session_dir = rec.close({"frames": len(seq)})
    meta.finish("2026-09-21T12:01:00+03:00")
    if metadata_overrides:
        meta.data.update(metadata_overrides)
    meta.write(session_dir, validate=not metadata_overrides)
    return (
        session_dir,
        meta,
        {"truth": [t.to_dict() for t in seq.truth], "results": results, "protocol": protocol},
    )


__all__ = [
    "CONFIG",
    "GIT",
    "ROOT",
    "ConsentStatus",
    "Ticker",
    "make_session",
    "short_protocol",
    "synthetic_sequence",
]
