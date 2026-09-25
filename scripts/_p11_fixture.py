"""SYNTHETIC kinematic fixture for Phase 11 development runs. No recording is made.

Scripted two-hand strokes descend onto the configured zones, accelerate through the impact
surface and rebound; some strokes are feints that stop above the surface. Observations are the
scripted path plus correlated noise, a causal smoothed velocity and short tracking dropouts.
POSITIVE targets are every valid outside-to-inside crossing of the dense noiseless path found
by the unchanged Phase 04 impact test (``geometry.first_impact``), intensity per labelling rule
R2 (inward-normal velocity at the crossing). These are scripted test values: not annotation,
not measurement, not participant evidence. Identities are grouping keys, never pseudonyms.
"""

import bisect
import math

import numpy as np

from spacedrums.config import config_hash
from spacedrums.contracts import TrackState
from spacedrums.data.feature_dataset import FeatureSession
from spacedrums.data.splits import Roster, build_split
from spacedrums.features.batch import build_features
from spacedrums.features.normalize import FeatureTable
from spacedrums.features.schema import FeatureSchema
from spacedrums.features.streaming import StreamingFeatures
from spacedrums.geometry import ZoneRegistry
from spacedrums.geometry.intersect import TrajectoryPoint, first_impact

VERSION = "ds-v0.0-selftest-p11-kinematic"
FIXTURE_ID = "p11-kinematic-v1"
NOTE = "SCRIPTED SYNTHETIC KINEMATIC TARGET; not human annotation or measurement"


def _stroke_plan(rng, zones, hand, start, end, style):
    """Scripted stroke list: zone, x, start/end heights, timings, feint flag."""
    strokes, t = [], start + rng.uniform(0.0, 0.3)
    preferred = style["zones"][hand]
    while t < end - 1.0:
        zone = zones[preferred[rng.integers(len(preferred))]]
        cx, cy, rx, ry = zone["center"][0], zone["center"][1], zone["rx"], zone["ry"]
        top = cy - ry  # upper arc = impact surface (ROI y down)
        feint = rng.random() < style["feint_rate"]
        lift = rng.uniform(*style["lift"])
        down = rng.uniform(*style["down_s"])
        strokes.append(
            {
                "zone_id": zone["zone_id"],
                "x": cx + rng.uniform(-0.45, 0.45) * rx,
                "y_start": top - lift,
                "y_bottom": top - rng.uniform(0.012, 0.03) if feint else cy - 0.15 * ry,
                "t0": t,
                "down_s": down,
                "up_s": rng.uniform(0.14, 0.22),
                "feint": feint,
            }
        )
        t += down + rng.uniform(*style["period_s"])
    return strokes


def _path(strokes):
    """Continuous scripted tip path; x glides between strokes, y accelerates into each impact."""
    starts = [s["t0"] for s in strokes]

    def position(t):
        i = bisect.bisect_right(starts, t) - 1
        if i < 0:
            return strokes[0]["x"], strokes[0]["y_start"]
        s = strokes[i]
        t_bottom = s["t0"] + s["down_s"]
        if t <= t_bottom:
            u = (t - s["t0"]) / s["down_s"]
            return s["x"], s["y_start"] + (s["y_bottom"] - s["y_start"]) * u * u
        if t <= t_bottom + s["up_s"]:
            u = (t - t_bottom) / s["up_s"]
            return s["x"], s["y_bottom"] + (s["y_start"] - s["y_bottom"]) * (1 - math.cos(math.pi * u)) / 2
        if i + 1 == len(strokes):
            return s["x"], s["y_start"]
        following, released = strokes[i + 1], t_bottom + s["up_s"]
        u = min(1.0, max(0.0, (t - released) / max(following["t0"] - released, 1e-6)))
        blend = (1 - math.cos(math.pi * u)) / 2
        return (
            s["x"] + (following["x"] - s["x"]) * blend,
            s["y_start"] + (following["y_start"] - s["y_start"]) * blend,
        )

    return position


def _crossings(position, registry, hand, start, end, v_min, step=0.001):
    times = np.arange(start, end, step)
    points = [TrajectoryPoint(float(t), position(float(t))) for t in times]
    found = []
    for zone in registry:
        if hand not in zone.allowed_hands:
            continue
        for a, b in zip(points, points[1:], strict=False):
            if zone.shape.contains(a.position) or not zone.shape.contains(b.position, include_boundary=False):
                continue
            impact = first_impact((a, b), zone, v_min)
            if impact is not None:
                inward = sum(v * n for v, n in zip(impact.velocity, zone.inward_normal, strict=True))
                found.append((impact, inward))
    return sorted(found, key=lambda item: item[0].t_cross)


def kinematic_fixture(config, *, identities=5, seconds=24.0, fps=30.0, seed=1100):
    zones_cfg = config["zones"]
    schema, registry = FeatureSchema(zones_cfg), ZoneRegistry.from_config(zones_cfg)
    v_min = float(config["geometry"]["v_min"])
    zones = {
        z["zone_id"]: {"zone_id": z["zone_id"], **{k: z["shape"][k] for k in ("center", "rx", "ry")}}
        for z in zones_cfg
    }
    sessions = []
    for identity in range(identities):
        rng = np.random.default_rng(seed + identity)
        participant, session_id = f"SYNTHETIC-K{identity}", f"synthetic-p11-kinematic-{identity}"
        style = {
            "zones": {"LEFT": ["hihat", "snare", "snare"], "RIGHT": ["snare", "tom1", "crash_ride"]},
            "feint_rate": rng.uniform(0.12, 0.22),
            "lift": sorted(rng.uniform(0.08, 0.2, 2)),
            "down_s": sorted(rng.uniform(0.15, 0.26, 2)),
            "period_s": sorted(rng.uniform(0.3, 0.6, 2)),
            "noise": rng.uniform(0.0015, 0.0035),
        }
        t0 = 100.0
        frame_times = t0 + np.cumsum(1 / fps + rng.uniform(-0.003, 0.003, int(seconds * fps)))
        end = float(frame_times[-1])
        labels, per_hand = [], {}
        for hand in ("LEFT", "RIGHT"):
            strokes = _stroke_plan(rng, zones, hand, t0, end, style)
            position = _path(strokes)
            for j, (impact, inward) in enumerate(_crossings(position, registry, hand, t0, end, v_min)):
                labels.append(
                    {
                        "session_id": session_id,
                        "participant_id": participant,
                        "source_kind": "SYNTHETIC",
                        "segment_id": "unit-segment",
                        "segment_take": 1,
                        "hand_id": hand,
                        "label_id": f"{session_id}-{hand}-POSITIVE-{j}",
                        "label_class": "POSITIVE",
                        "t_impact_est": impact.t_cross,
                        "t_event": impact.t_cross,
                        "t_start": None,
                        "t_end": None,
                        "excluded": False,
                        "zone_id": impact.zone.zone_id,
                        "impact_position": list(impact.position),
                        "intensity_proxy_gt": inward,
                        "notes": NOTE,
                    }
                )
            for j, s in enumerate(x for x in strokes if x["feint"]):
                labels.append(
                    {
                        "session_id": session_id,
                        "participant_id": participant,
                        "source_kind": "SYNTHETIC",
                        "segment_id": "unit-segment",
                        "segment_take": 1,
                        "hand_id": hand,
                        "label_id": f"{session_id}-{hand}-NEG_STOP_BEFORE_IMPACT-{j}",
                        "label_class": "NEG_STOP_BEFORE_IMPACT",
                        "t_impact_est": None,
                        "t_event": s["t0"] + s["down_s"],
                        "t_start": s["t0"],
                        "t_end": s["t0"] + s["down_s"] + s["up_s"],
                        "excluded": False,
                        "zone_id": s["zone_id"],
                        "impact_position": None,
                        "intensity_proxy_gt": None,
                        "notes": NOTE,
                    }
                )
            dropouts = set()
            for start in rng.choice(np.arange(30, len(frame_times) - 10), 3, replace=False):
                dropouts.update(range(int(start), int(start) + int(rng.integers(2, 4))))
            per_hand[hand] = (position, dropouts)
        tracks = []
        state = {
            h: {"noise": np.zeros(2), "last": None, "vel": None, "since": 0, "t_valid": None}
            for h in per_hand
        }
        for i, t in enumerate(frame_times):
            for hand in ("LEFT", "RIGHT"):
                position, dropouts = per_hand[hand]
                st = state[hand]
                common = {
                    "frame_id": i,
                    "t_capture": float(t),
                    "hand_id": hand,
                    "tracker_id": "synthetic-p11-kinematic",
                    "tip_method": "GEOM",
                    "axis_angle": None,
                    "axis_angular_velocity": None,
                    "history_ref": None,
                    "reset_reason": None,
                }
                if i in dropouts:
                    st["since"] += 1
                    st["last"], st["vel"] = None, None
                    tracks.append(
                        TrackState(
                            **common,
                            status="INVALID",
                            tip_filtered=None,
                            tip_velocity=None,
                            tip_acceleration=None,
                            confidence=0.2,
                            frames_since_valid=st["since"],
                            last_valid_t=st["t_valid"],
                        )
                    )
                    continue
                st["noise"] = 0.6 * st["noise"] + rng.normal(0, style["noise"], 2)
                observed = np.asarray(position(float(t))) + st["noise"]
                velocity, acceleration = np.zeros(2), np.zeros(2)
                if st["last"] is not None:
                    raw = (observed - st["last"][1]) / (t - st["last"][0])
                    velocity = raw if st["vel"] is None else 0.5 * raw + 0.5 * st["vel"]
                    if st["vel"] is not None:
                        acceleration = (velocity - st["vel"]) / (t - st["last"][0])
                st["last"], st["vel"] = (float(t), observed), velocity
                st["since"], st["t_valid"] = 0, float(t)
                tracks.append(
                    TrackState(
                        **common,
                        status="VALID",
                        tip_filtered=tuple(map(float, observed)),
                        tip_velocity=tuple(map(float, velocity)),
                        tip_acceleration=tuple(map(float, acceleration)),
                        confidence=0.9,
                        frames_since_valid=0,
                        last_valid_t=float(t),
                    )
                )
        for hand, (_, dropouts) in per_hand.items():
            for k, run in enumerate(_runs(sorted(dropouts))):
                labels.append(
                    {
                        "session_id": session_id,
                        "participant_id": participant,
                        "source_kind": "SYNTHETIC",
                        "segment_id": "unit-segment",
                        "segment_take": 1,
                        "hand_id": hand,
                        "label_id": f"{session_id}-{hand}-NEG_TRACKING_LOSS-{k}",
                        "label_class": "NEG_TRACKING_LOSS",
                        "t_impact_est": None,
                        "t_event": None,
                        "t_start": float(frame_times[run[0]]),
                        "t_end": float(frame_times[run[-1]]),
                        "excluded": False,
                        "zone_id": None,
                        "impact_position": None,
                        "intensity_proxy_gt": None,
                        "notes": NOTE,
                    }
                )
        records = build_features(tracks, schema)
        stream = StreamingFeatures(schema)
        assert records == [stream.update(track) for track in tracks]
        table = FeatureTable(participant, session_id, "SYNTHETIC", records, [True] * len(records))
        sessions.append(
            FeatureSession(
                table,
                tracks,
                labels,
                [
                    {
                        "segment_id": "unit-segment",
                        "take": 1,
                        "t_start": t0,
                        "t_end": end + 0.001,
                        "eligible": True,
                    }
                ],
                schema,
                {"bit_identical": True, "records_compared": len(records)},
                {FIXTURE_ID: config_hash([track.to_dict() for track in tracks])},
            )
        )
    roster = Roster(
        VERSION, "labels-v1.0", "SYNTHETIC", {s.table.participant: [s.table.session_id] for s in sessions}
    )
    _, cv = build_split(roster)
    manifest = {
        "dataset_version": VERSION,
        "manifest_hash": config_hash({"fixture": FIXTURE_ID, "inputs": [s.input_hashes for s in sessions]}),
        "kind": "SELFTEST",
    }
    return manifest, cv, sessions


def _runs(indices):
    runs = []
    for i in indices:
        if runs and i == runs[-1][-1] + 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    return runs
