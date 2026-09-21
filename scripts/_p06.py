"""Shared helpers for the Phase 06 scripts: metadata assembly from CLI options, the SYNTHETIC
full-protocol sequence, and git provenance.

Everything produced by the ``--synthetic`` path is SYNTHETIC (labelled in ids, file names and the
metadata's ``session_kind``); the ``--devcapture`` path re-processes an existing Phase 02 developer
capture (DEV CAPTURE; never participant data). Neither records a person.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _runlog import ROOT, git_dirty, git_sha  # noqa: E402

from spacedrums import timing  # noqa: E402
from spacedrums.app.synthetic import DT, Swing, build_sequence  # noqa: E402
from spacedrums.config import ResolvedConfig  # noqa: E402
from spacedrums.contracts import HandId  # noqa: E402
from spacedrums.data.metadata import (  # noqa: E402
    ConsentStatus,
    SessionKind,
    SessionMetadata,
    default_background,
    default_lighting,
    default_sticks,
    participant_id_for,
    participant_meta_not_collected,
    session_id_for,
)
from spacedrums.data.protocol import Protocol, SegmentType  # noqa: E402
from spacedrums.geometry import ZoneRegistry  # noqa: E402

DEFAULT_CONFIG = ROOT / "configs" / "prototype.candidate.yaml"
RAW_ROOT = ROOT / "data" / "raw"
MANIFESTS_DIR = ROOT / "data" / "manifests"

__all__ = [
    "DEFAULT_CONFIG",
    "MANIFESTS_DIR",
    "RAW_ROOT",
    "ROOT",
    "add_metadata_options",
    "git_dirty",
    "git_sha",
    "metadata_from_args",
    "synthetic_protocol_sequence",
]


# ----------------------------------------------------------------------------- CLI metadata prompts


def add_metadata_options(ap: argparse.ArgumentParser) -> None:
    """Session-start metadata prompts (Task 06.1) as options; anything not given stays NOT_COLLECTED /
    null — never a guessed value."""
    g = ap.add_argument_group("session metadata")
    g.add_argument("--participant", default=None, help="pseudonym P<NN> (participant) or PILOT<NN> (pilot)")
    g.add_argument("--session-index", type=int, default=1)
    g.add_argument("--location", default="", help="location tag (room)")
    g.add_argument("--lighting", default=None, choices=("L0", "L1", "L2", "L3", "L4", "L5"))
    g.add_argument("--lighting-description", default="")
    g.add_argument("--second-lighting", default=None, choices=("L0", "L1", "L2", "L3", "L4", "L5"))
    g.add_argument(
        "--background", default=None, choices=("CLEAN", "CLUTTER", "PEOPLE", "CLUTTER_PEOPLE", "UNSPECIFIED")
    )
    g.add_argument("--people-present", default=None, choices=("yes", "no"))
    g.add_argument("--background-description", default="")
    g.add_argument("--stick-colour", default="")
    g.add_argument("--stick-length", default=None, choices=("SHORT", "STANDARD", "LONG", "UNSPECIFIED"))
    g.add_argument("--stick-marker", default="NONE", choices=("NONE", "TAPE"))
    g.add_argument("--stick-owner", default=None, choices=("OWN", "PROJECT"))
    g.add_argument("--handedness", default=None, choices=("RIGHT", "LEFT", "MIXED"))
    g.add_argument("--experience", default=None, choices=("NONE", "SOME", "REGULAR"))
    g.add_argument("--height-range", default=None, choices=("UNDER_160", "160_175", "175_190", "OVER_190"))
    g.add_argument("--consent-status", default=None, choices=("SIGNED", "PENDING"))
    g.add_argument("--consent-record-id", default=None)
    g.add_argument(
        "--distance-mark", default=None, help="floor mark id used for the core segments (e.g. D100)"
    )
    g.add_argument(
        "--distance-m", type=float, default=None, help="nominal distance of that mark (set-up value)"
    )
    g.add_argument("--second-distance-mark", default=None)
    g.add_argument("--second-distance-m", type=float, default=None)
    g.add_argument("--operator-notes", default="")


def metadata_from_args(
    args: argparse.Namespace,
    *,
    kind: SessionKind,
    session_id: str,
    cfg: ResolvedConfig,
    protocol: Protocol,
    source: dict[str, Any],
    git: str,
    arm_active: str,
    arms_shadow: list[str],
    t_mono_at_start: float,
    store_crop: str,
    pad_zone_id: str | None,
) -> SessionMetadata:
    pid = participant_id_for(kind, args.participant)
    people = None if args.people_present is None else args.people_present == "yes"
    lighting = default_lighting(kind, args.lighting, args.lighting_description)
    lighting["second_condition_id"] = args.second_lighting
    if kind is not SessionKind.SYNTHETIC and cfg["camera_profile"].get("exposure"):
        lighting["exposure_used"] = {
            "mode": cfg["camera_profile"]["exposure"]["mode"],
            "value": cfg["camera_profile"]["exposure"].get("value"),
        }
    background = default_background(kind, args.background, args.background_description)
    background["people_present"] = people if kind is not SessionKind.SYNTHETIC else None
    sticks = default_sticks(kind)
    if kind is not SessionKind.SYNTHETIC:
        sticks.update(
            colour=args.stick_colour,
            length_class=args.stick_length or "UNSPECIFIED",
            marker=args.stick_marker,
            ownership=args.stick_owner or "OWN",
        )
    pm = participant_meta_not_collected(kind)
    if kind in (SessionKind.PARTICIPANT, SessionKind.PILOT):
        given = {
            k: v
            for k, v in (
                ("handedness", args.handedness),
                ("experience", args.experience),
                ("height_range", args.height_range),
            )
            if v
        }
        pm.update(given)
        if given:
            pm["source"] = "CONSENT_FORM_PART_D"
    consent = (
        ConsentStatus.NOT_REQUIRED
        if kind in (SessionKind.SYNTHETIC, SessionKind.DEV_CAPTURE)
        else ConsentStatus(args.consent_status or "PENDING")
    )
    return SessionMetadata.new(
        kind=kind,
        session_id=session_id,
        participant_id=pid,
        session_index=args.session_index,
        date=timing.wall_clock_iso()[:10],
        started_at=timing.wall_clock_iso(),
        t_mono_at_start=t_mono_at_start,
        hardware_id=args.hardware_id,
        camera_profile_id=source.get("camera_profile_id") or cfg["camera_profile"]["profile_id"],
        audio_profile_id=cfg["audio"]["audio_profile_id"],
        roi_px=tuple(source.get("roi_px") or cfg["roi"]["px"]),
        config_hash=cfg.config_hash,
        git_sha=git,
        clock_id=timing.CLOCK_ID,
        zone_layout_id=f"{len(cfg['zones'])}-zones:" + ",".join(z["zone_id"] for z in cfg["zones"]),
        arm_active=arm_active,
        arms_shadow=arms_shadow,
        tip_method_active=cfg["stick"]["method_id"],
        protocol=_protocol_block(protocol),
        source=source,
        video={
            "container": "PNG_SEQUENCE",
            "codec": "png",
            "lossless": True,
            "crop": store_crop,
            "frame_size_px": list(source.get("frame_size_px") or cfg["camera_profile"]["resolution_px"]),
            "parameters": {"cv2_imwrite_png_compression": 1, "note": "ADR-0019: intra-frame lossless"},
        },
        location_tag=args.location,
        distance_mark={
            "label": args.distance_mark
            or ("none (synthetic)" if kind is SessionKind.SYNTHETIC else "unspecified"),
            "nominal_distance_m": args.distance_m,
            "second_mark_label": args.second_distance_mark,
            "second_mark_nominal_distance_m": args.second_distance_m,
        },
        lighting=lighting,
        background=background,
        stick_description=sticks,
        participant_meta=pm,
        consent_status=consent,
        consent_record_id=args.consent_record_id
        if kind in (SessionKind.PARTICIPANT, SessionKind.PILOT)
        else None,
        pad_zone_id=pad_zone_id,
        operator_notes=args.operator_notes,
    )


def _protocol_block(protocol: Protocol) -> dict[str, Any]:
    d = protocol.to_dict()
    return {k: d[k] for k in ("protocol_id", "version", "seed", "seed_source", "zone_order", "options")}


def session_naming(kind: SessionKind, args: argparse.Namespace, slug: str | None) -> str:
    return session_id_for(kind, participant_id_for(kind, args.participant), args.session_index, slug)


# ----------------------------------------------------------------------------- SYNTHETIC protocol


def synthetic_protocol_sequence(
    protocol: Protocol,
    registry: ZoneRegistry,
    *,
    seed: int = 0,
    noise: float = 0.0,
    enable_optional: bool = False,
    lead_in_s: float = 0.3,
):
    """One SYNTHETIC observation sequence spanning the whole protocol: per segment, the strokes the
    cue asks for (strikes, stop-short, lateral moves, occlusions, a covered camera), on the segment's
    time slot, so that the guided recorder's segment markers line up with generated behaviour."""
    L, R = HandId.LEFT, HandId.RIGHT
    swings: list[Swing] = []
    occluded: dict[HandId, set[int]] = {L: set(), R: set()}
    t = lead_in_s
    z1, z2 = protocol.options["primary_zone"], protocol.options["secondary_zone"]

    def frames_between(a: float, b: float) -> set[int]:
        return {k for k in range(int(round(a / DT)), int(round(b / DT)))}

    for spec in protocol.segments:
        if spec.optional and not enable_optional:
            continue
        D = spec.duration_s
        st = spec.type
        hands = spec.hands
        zones = spec.zone_ids or (z1,)
        if st is SegmentType.WARMUP:
            k = 0
            while 0.2 + 1.2 * k + 0.5 < D:
                swings.append(Swing(R if k % 2 == 0 else L, z1, t + 0.2 + 1.2 * k, kind="lateral"))
                k += 1
        elif st in (
            SegmentType.SINGLE_HITS,
            SegmentType.DISTANCE_VARIATION,
            SegmentType.LIGHTING_VARIATION,
            SegmentType.PAD_MIC,
            SegmentType.FREE_PLAY,
        ):
            k = 0
            while 0.4 + 1.0 * k + 0.5 < D:
                h = hands[k % len(hands)]
                swings.append(Swing(h, zones[k % len(zones)], t + 0.4 + 1.0 * k))
                k += 1
        elif st is SegmentType.ALTERNATING_ONE_ZONE:
            k = 0
            while 0.4 + 0.5 * k + 0.5 < D:
                swings.append(Swing(R if k % 2 == 0 else L, z1, t + 0.4 + 0.5 * k))
                k += 1
        elif st is SegmentType.ALTERNATING_TWO_ZONES:
            k = 0
            while 0.4 + 0.5 * k + 0.5 < D:
                swings.append(
                    Swing(R, z1, t + 0.4 + 0.5 * k) if k % 2 == 0 else Swing(L, z2, t + 0.4 + 0.5 * k)
                )
                k += 1
        elif st is SegmentType.TEMPO:
            period = 60.0 / float(spec.tempo_bpm or 60)
            k = 0
            while 0.4 + period * k + 0.5 < D:
                swings.append(Swing(R, z1, t + 0.4 + period * k, t_down=min(0.2, period / 2.5)))
                k += 1
        elif st is SegmentType.RAPID:
            k = 0
            while 0.4 + 0.3 * k + 0.3 < D:
                swings.append(Swing(hands[0], z1, t + 0.4 + 0.3 * k, t_down=0.10))
                k += 1
        elif st is SegmentType.NEAR_SIMULTANEOUS:
            k = 0
            while 0.4 + 1.0 * k + 0.5 < D:
                swings.append(Swing(R, z1, t + 0.4 + 1.0 * k))
                swings.append(Swing(L, z2, t + 0.41 + 1.0 * k))
                k += 1
        elif st is SegmentType.MOVE_BETWEEN_ZONES:
            k = 0
            order = list(protocol.zone_order)
            while 0.3 + 1.0 * k + 0.5 < D:
                swings.append(Swing(R, order[k % len(order)], t + 0.3 + 1.0 * k, kind="lateral"))
                k += 1
        elif st in (SegmentType.FAKE_SWING, SegmentType.STOP_BEFORE_IMPACT):
            k = 0
            while 0.4 + 1.0 * k + 0.5 < D:
                swings.append(
                    Swing(
                        R if k % 2 == 0 else L,
                        z1,
                        t + 0.4 + 1.0 * k,
                        depth=-0.03,
                        t_down=0.15 if st is SegmentType.FAKE_SWING else 0.2,
                    )
                )
                k += 1
        elif st is SegmentType.OCCLUSION:
            k = 0
            while 0.4 + 1.0 * k + 0.5 < D:
                swings.append(Swing(R, z1, t + 0.4 + 1.0 * k))
                occluded[L] |= frames_between(
                    t + 0.4 + 1.0 * k, t + 0.6 + 1.0 * k
                )  # left hand behind the stick
                k += 1
        elif st is SegmentType.TRACKING_INTERRUPTION:
            k = 0
            while 0.4 + 1.0 * k + 0.5 < D:
                swings.append(Swing(R, z1, t + 0.4 + 1.0 * k))
                k += 1
            mid = t + D / 2
            for h in (L, R):
                occluded[h] |= frames_between(mid, min(t + D - 0.05, mid + 0.25))  # camera covered ~250 ms
        t += D
    total = t + lead_in_s
    return build_sequence(
        registry,
        swings,
        duration_s=total,
        noise=noise,
        seed=seed,
        occluded=occluded,
        image=True,
        name="synthetic-protocol",
    )
