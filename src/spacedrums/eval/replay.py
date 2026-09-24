"""Frame-ordered replay through the production geometry and commit policy."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from spacedrums.commit import CommitSettings, PerHandCommitPolicy
from spacedrums.contracts import (
    Arm,
    CandidateSource,
    HandId,
    StrikeCandidate,
    TrackState,
    TrajectoryPrediction,
)
from spacedrums.eval.constants import DELAY_POLICIES
from spacedrums.eval.temporal import temporal_candidate
from spacedrums.features.streaming import StreamingFeatures, history_arrays
from spacedrums.geometry import GeometryEngine, ZoneRegistry
from spacedrums.prediction import RuleBasedAnticipator, RuleSettings


@dataclass(frozen=True)
class DelayPolicy:
    name: str = "zero"
    fixed_s: float = 0.0
    per_frame_s: Mapping[int, float] = field(default_factory=dict)

    def __post_init__(self):
        if self.name not in DELAY_POLICIES or self.fixed_s < 0:
            raise ValueError("invalid delay policy")

    def at(self, frame_id: int) -> float:
        if self.name == "zero":
            return 0.0
        if self.name == "fixed":
            return self.fixed_s
        value = float(self.per_frame_s[frame_id])
        if value < 0:
            raise ValueError("processing delay must be nonnegative")
        return value


@dataclass
class ReplayResult:
    arm: str
    candidates: list[StrikeCandidate]
    committed: list
    decisions: list[dict[str, Any]]
    predictions: list[TrajectoryPrediction]

    def strike_rows(self, session_id: str, participant_id: str | None = None) -> list[dict]:
        by_id = {c.candidate_id: c for c in self.candidates}
        return [
            {
                **s.to_dict(),
                "session_id": session_id,
                "participant_id": participant_id,
                "t_impact_pred": by_id[s.candidate_id].t_impact_pred,
                "t_impact_est": by_id[s.candidate_id].t_impact_est,
                "impact_position": list(by_id[s.candidate_id].impact_position),
            }
            for s in self.committed
        ]


ModelFn = Callable[
    [TrackState, Sequence[TrackState], object | None], TrajectoryPrediction | StrikeCandidate | None
]


def replay(
    tracks: Sequence[TrackState],
    *,
    arm: str,
    registry: ZoneRegistry,
    commit_settings: CommitSettings,
    v_min: float,
    session_id: str,
    delay: DelayPolicy | None = None,
    rule_settings: RuleSettings | None = None,
    model: ModelFn | None = None,
    feature_schema: object | None = None,
    feature_window_n: int = 8,
    norm_stats: object | None = None,
    feature_records: Sequence | None = None,
    dropped_by_frame: Mapping[int, int] | None = None,
) -> ReplayResult:
    """Each call owns fresh per-hand state. The model sees only current/past inputs."""
    if arm not in ("A", "B", "MODEL:C-GBDT", "MODEL:C-GRU", "MODEL:C-TCN"):
        raise ValueError("unknown replay arm")
    delay = delay or DelayPolicy()
    if arm == "B" and rule_settings is None or arm.startswith("MODEL:") and model is None:
        raise ValueError("arm settings/model missing")
    if feature_schema is None and norm_stats is not None:
        raise ValueError("normalization requires feature schema")
    if feature_records is not None and (feature_schema is None or len(feature_records) != len(tracks)):
        raise ValueError("feature records must align with tracks and a schema")
    clock_t = [0.0]
    geometry = GeometryEngine(registry, v_min=v_min, session_id=session_id)
    arm_enum = {
        "A": Arm.A,
        "B": Arm.B,
        "MODEL:C-GBDT": Arm.C_GBDT,
        "MODEL:C-GRU": Arm.C_GRU,
        "MODEL:C-TCN": Arm.C_TCN,
    }[arm]
    policies = {
        h: PerHandCommitPolicy(
            h,
            commit_settings,
            registry,
            arm=arm_enum,
            shadow=False,
            gain_fn=lambda _z, _v: 1.0,
            session_id=session_id,
            episode_fn=geometry.episode_id,
        )
        for h in HandId
    }
    anticipators = (
        {h: RuleBasedAnticipator(rule_settings, clock=lambda: clock_t[0]) for h in HandId}
        if rule_settings
        else {}
    )
    histories = {h: deque(maxlen=128) for h in HandId}
    features = (
        StreamingFeatures(feature_schema, history_n=feature_window_n)
        if feature_schema and feature_records is None
        else None
    )
    feature_rings = {h: deque(maxlen=feature_window_n) for h in HandId}
    result = ReplayResult(arm=arm, candidates=[], committed=[], decisions=[], predictions=[])
    previous_key: tuple[float, int, str] | None = None
    for index, track in enumerate(tracks):
        key = (track.t_capture, track.frame_id, str(track.hand_id))
        if previous_key is not None and key <= previous_key:
            raise ValueError("tracks must be strictly ordered by capture time, frame and hand")
        previous_key = key
        h = track.hand_id
        clock_t[0] = track.t_capture + delay.at(track.frame_id)
        if track.reset_reason is not None:
            geometry.reset_hand(h)
            policies[h].reset(track.reset_reason)
            if h in anticipators:
                anticipators[h].reset(track.reset_reason)
            histories[h].clear()
            if features:
                features.reset(h)
            feature_rings[h].clear()
        histories[h].append(track)
        if features:
            features.update(track)
        if feature_records is not None:
            record = feature_records[index]
            if (record.frame_id, record.t_capture, record.hand_id) != (
                track.frame_id,
                track.t_capture,
                str(h),
            ):
                raise ValueError("feature record/track alignment mismatch")
            feature_rings[h].append(record)
        observed = geometry.observe(
            frame_id=track.frame_id,
            t_capture=track.t_capture,
            hand_id=h,
            position=track.tip_filtered,
            status=track.status,
            t_candidate=clock_t[0],
        )
        candidates: tuple[StrikeCandidate, ...] = ()
        if arm == "A":
            candidates = observed
        elif arm == "B":
            pred = anticipators[h].predict(tuple(histories[h]))
            if pred is not None:
                result.predictions.append(pred)
                assert track.tip_filtered is not None
                candidate = geometry.intersect_prediction(
                    pred,
                    current_position=track.tip_filtered,
                    source=CandidateSource.RULE,
                    t_candidate=clock_t[0],
                )
                candidates = (candidate,) if candidate else ()
        else:
            if feature_records is not None and len(feature_rings[h]) == feature_window_n:
                x, m = history_arrays(list(feature_rings[h]), feature_schema)
                window = norm_stats.apply(x, m, feature_schema) if norm_stats else (x, m)
            else:
                window = features.window(h, stats=norm_stats) if features else None
            output = model(track, tuple(histories[h]), window)  # type: ignore[misc]
            if isinstance(output, TrajectoryPrediction):
                result.predictions.append(output)
                if track.tip_filtered is not None:
                    candidate = geometry.intersect_prediction(
                        output,
                        current_position=track.tip_filtered,
                        source=CandidateSource.MODEL,
                        t_candidate=clock_t[0],
                    )
                    if arm in ("MODEL:C-GRU", "MODEL:C-TCN"):
                        candidate = temporal_candidate(candidate, registry)
                    candidates = (candidate,) if candidate else ()
            elif isinstance(output, StrikeCandidate):
                if arm in ("MODEL:C-GRU", "MODEL:C-TCN"):
                    raise ValueError("temporal arms require a trajectory through geometry")
                if output.source is not CandidateSource.MODEL or output.frame_id != track.frame_id:
                    raise ValueError("model candidate has wrong source/frame")
                candidates = (output,)
            elif output is not None:
                raise TypeError("model must return a trajectory, candidate, or None")
        result.candidates.extend(candidates)
        result.committed.extend(
            policies[h].step(
                candidates,
                track,
                clock_t[0],
                dropped_since_last=(dropped_by_frame or {}).get(track.frame_id, 0),
            )
        )
        result.decisions.extend({"hand_id": str(h), **trace.to_dict()} for trace in policies[h].trace)
    return result
