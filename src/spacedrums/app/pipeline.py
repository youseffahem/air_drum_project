"""The per-frame decision pipeline of the playable prototype (Phase 05, Tasks 05.1 / 05.2 / 05.3 / 05.4).

    for each hand h (LEFT then RIGHT, fixed order; independent state, ADR-0006):
      tracking[h].update(...)                        -> TrackState[h]
      geometry.observe(TrackState[h])                -> StrikeCandidate(A)*   (REACTIVE: observed crossing,
                                                                               Phase 04 episode rule)
      anticipator[h].predict(tracking[h].history)    -> TrajectoryPrediction | None   (RULE, CV/CA)
      geometry.intersect_prediction(...)             -> StrikeCandidate(B) | None     (same intersect)
      for each arm: commit[arm][h].step(candidates(arm), TrackState[h], t_now) -> CommittedStrike*
      active arm, shadow=False -> audio.play(...) -> AudioEvent;  shadow arms -> logged only
    timing: FRAME record per frame; STRIKE record per commit (shadow included)

``t_now`` is supplied by the driver: ``timing.now()`` live; ``t_frame_available + delta_proc_s``
in replay (a documented provisional constant so a replay reproduces the committed-strike list;
Phase 09 defines the ``Delta_proc`` policy — architecture.md section 12.1). Decision fields never
depend on wall-clock stamps other than ``t_now``.

The pipeline consumes **observations** (``HandObservation``, ``StickObservation`` per hand) so it
runs unchanged on live perception, replayed video and labelled SYNTHETIC observation sequences
(tests); ``FramePipeline`` adds the perception stage in front of it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from spacedrums.app.audio_out import AudioOutput
from spacedrums.commit import CommitSettings, PerHandCommitPolicy
from spacedrums.contracts import (
    Arm,
    AudioEvent,
    CandidateSource,
    CommittedStrike,
    FrameSample,
    HandId,
    HandObservation,
    ResetReason,
    StickObservation,
    StrikeCandidate,
    TimingRecord,
    TrackState,
    TrajectoryPrediction,
)
from spacedrums.geometry import GeometryEngine, ZoneRegistry
from spacedrums.prediction import RuleBasedAnticipator, RuleSettings
from spacedrums.timing import now
from spacedrums.timing.records import TimingCollector
from spacedrums.tracking import CausalTracker, TrackerSettings

HANDS = (HandId.LEFT, HandId.RIGHT)
SUPPORTED_ARMS = (Arm.A, Arm.B)
Observations = Mapping[HandId, tuple[HandObservation, StickObservation]]


@dataclass
class HandFrame:
    track: TrackState
    prediction: TrajectoryPrediction | None = None
    reactive: tuple[StrikeCandidate, ...] = ()
    rule: StrikeCandidate | None = None
    commits: list[CommittedStrike] = field(default_factory=list)
    audio: list[AudioEvent] = field(default_factory=list)

    @property
    def candidates(self) -> tuple[StrikeCandidate, ...]:
        return self.reactive + ((self.rule,) if self.rule is not None else ())


@dataclass
class FrameResult:
    sample: FrameSample
    t_now: float
    t_tracking_done: float
    t_inference_done: float | None
    hands: dict[HandId, HandFrame]
    timing: list[TimingRecord]

    @property
    def commits(self) -> list[CommittedStrike]:
        return [c for h in HANDS for c in self.hands[h].commits]

    @property
    def audio(self) -> list[AudioEvent]:
        return [e for h in HANDS for e in self.hands[h].audio]


def _arm_of(source: CandidateSource) -> Arm:
    return Arm.A if source is CandidateSource.REACTIVE else Arm.B


class DecisionPipeline:
    """Tracking -> geometry (A) -> rule extrapolation (B) -> commit per arm -> audio -> timing."""

    def __init__(
        self,
        cfg: dict[str, Any],
        *,
        registry: ZoneRegistry,
        session_id: str,
        active_arm: Arm | str,
        shadow_arms: tuple[Arm | str, ...] = (),
        hardware_id: str,
        config_hash: str,
        audio: AudioOutput | None,
        clock: Callable[[], float] = now,
        gain_fn: Callable[[str, float], float] | None = None,
    ) -> None:
        self.cfg = cfg
        self.registry = registry
        self.session_id = session_id
        self.clock = clock
        self.active_arm = Arm(active_arm)
        self.shadow_arms = tuple(Arm(a) for a in shadow_arms if Arm(a) is not self.active_arm)
        for arm in (self.active_arm, *self.shadow_arms):
            if arm not in SUPPORTED_ARMS:
                raise ValueError(f"Phase 05 supports arms A and B only, got {arm}")
        self.arms: tuple[Arm, ...] = tuple(dict.fromkeys((self.active_arm, *self.shadow_arms)))
        self.audio = audio
        if gain_fn is None and audio is None:
            raise ValueError("DecisionPipeline needs an AudioOutput or a gain_fn for CommittedStrike.gain")
        self.gain_fn = gain_fn or audio.gain  # type: ignore[union-attr]
        self.tracker_settings = TrackerSettings.from_config(cfg)
        self.trackers = {h: CausalTracker(h, self.tracker_settings) for h in HANDS}
        if "geometry" not in cfg:  # schema 1.3 block (ADR-0018): the app never guesses v_min
            raise ValueError(
                "config has no geometry block (v_min); the app never guesses geometry thresholds"
            )
        self.geometry = GeometryEngine(registry, v_min=float(cfg["geometry"]["v_min"]), session_id=session_id)
        self.rule_settings = RuleSettings.from_config(cfg) if Arm.B in self.arms else None
        self.anticipators = (
            {h: RuleBasedAnticipator(self.rule_settings, clock=clock) for h in HANDS}
            if self.rule_settings is not None
            else {}
        )
        self.commit_settings = CommitSettings.from_config(cfg)
        self.policies: dict[Arm, dict[HandId, PerHandCommitPolicy]] = {
            arm: {
                h: PerHandCommitPolicy(
                    h,
                    self.commit_settings,
                    registry,
                    arm=arm,
                    shadow=(arm is not self.active_arm),
                    gain_fn=self.gain_fn,
                    session_id=session_id,
                    episode_fn=self.geometry.episode_id,
                )
                for h in HANDS
            }
            for arm in self.arms
        }
        self.timing = TimingCollector(
            hardware_id=hardware_id,
            config_hash=config_hash,
            audio_out_measured=(audio.latency.measured if audio is not None else False),
            keep=False,
        )
        self.frames = 0
        self.arm_switches: list[dict[str, Any]] = []
        for h in HANDS:
            self.trackers[h].reset(ResetReason.SESSION_START)
            for arm in self.arms:
                self.policies[arm][h].reset(ResetReason.SESSION_START)

    # -- runtime switch (Task 05.5) --------------------------------------------------------
    def set_active_arm(self, arm: Arm | str, t_now: float) -> None:
        arm = Arm(arm)
        if arm not in self.arms:
            raise ValueError(f"arm {arm} is not running (arms: {self.arms})")
        if arm is self.active_arm:
            return
        previous, self.active_arm = self.active_arm, arm
        self.shadow_arms = tuple(a for a in self.arms if a is not arm)
        for a in self.arms:
            for h in HANDS:
                self.policies[a][h].shadow = a is not arm
                self.policies[a][h].reset(ResetReason.ARM_SWITCH)  # IDLE; timers persist (reset matrix)
        self.arm_switches.append({"t": t_now, "from": str(previous), "to": str(arm)})

    # -- per-frame -------------------------------------------------------------------------
    def step(
        self, sample: FrameSample, observations: Observations, *, t_now: float | None = None
    ) -> FrameResult:
        self.frames += 1
        hands: dict[HandId, HandFrame] = {}
        # 1. tracking, both hands (fixed order)
        for h in HANDS:
            hand_obs, stick_obs = observations[h]
            track = self.trackers[h].update(hand_obs, stick_obs, sample.t_capture)
            hands[h] = HandFrame(track=track)
            if track.reset_reason is not None:
                for arm in self.arms:
                    self.policies[arm][h].reset(track.reset_reason)
                if h in self.anticipators:
                    self.anticipators[h].reset(track.reset_reason)
        t_tracking_done = self.clock()
        # 2. geometry on the observed trajectory (A) and rule extrapolation + geometry (B)
        t_inference_done: float | None = None
        for h in HANDS:
            hf = hands[h]
            track = hf.track
            if Arm.A in self.arms:
                hf.reactive = self.geometry.observe(
                    frame_id=track.frame_id,
                    t_capture=track.t_capture,
                    hand_id=h,
                    position=track.tip_filtered,
                    status=track.status,
                    t_candidate=self.clock(),
                )
            else:  # keep the episode bookkeeping consistent even when A is not logged
                self.geometry.observe(
                    frame_id=track.frame_id,
                    t_capture=track.t_capture,
                    hand_id=h,
                    position=track.tip_filtered,
                    status=track.status,
                    t_candidate=self.clock(),
                )
            if h in self.anticipators:
                pred = self.anticipators[h].predict(self.trackers[h].history)
                hf.prediction = pred
                if pred is not None:
                    t_inference_done = pred.t_inference_done
                    assert track.tip_filtered is not None
                    hf.rule = self.geometry.intersect_prediction(
                        pred, current_position=track.tip_filtered, source=CandidateSource.RULE
                    )
        # 3. commit per arm, per hand; audio for the active arm; timing
        t_now = float(self.clock() if t_now is None else t_now)
        timing: list[TimingRecord] = [
            self.timing.frame(
                sample,
                t_tracking_done=t_tracking_done,
                t_inference_done=t_inference_done,
                arm=Arm.B if t_inference_done is not None else None,
            )
        ]
        for h in HANDS:
            hf = hands[h]
            by_arm: dict[Arm, list[StrikeCandidate]] = {arm: [] for arm in self.arms}
            for c in hf.candidates:
                by_arm.setdefault(_arm_of(c.source), []).append(c)
            candidate_by_id = {c.candidate_id: c for c in hf.candidates}
            for arm in self.arms:
                commits = self.policies[arm][h].step(
                    by_arm.get(arm, []), hf.track, t_now, dropped_since_last=sample.dropped_since_last
                )
                for committed in commits:
                    hf.commits.append(committed)
                    event: AudioEvent | None = None
                    if not committed.shadow and self.audio is not None:
                        event = self.audio.play(committed)
                        hf.audio.append(event)
                    timing.append(
                        self.timing.strike(
                            committed,
                            candidate_by_id[committed.candidate_id],
                            sample,
                            t_tracking_done=t_tracking_done,
                            t_inference_done=(
                                hf.prediction.t_inference_done if hf.prediction is not None else None
                            ),
                            audio=event,
                        )
                    )
        return FrameResult(
            sample=sample,
            t_now=t_now,
            t_tracking_done=t_tracking_done,
            t_inference_done=t_inference_done,
            hands=hands,
            timing=timing,
        )

    # -- diagnostics -----------------------------------------------------------------------
    def counters(self) -> dict[str, Any]:
        return {
            "frames": self.frames,
            "active_arm": str(self.active_arm),
            "shadow_arms": [str(a) for a in self.shadow_arms],
            "arm_switches": list(self.arm_switches),
            "anticipator": {
                str(h): {
                    "predictions": a.predictions,
                    "declines": dict(a.declines),
                    "declared_history": a.declared_history(),
                }
                for h, a in self.anticipators.items()
            },
            "commit": {
                str(arm): {
                    str(h): {"commits": p.commits, "decisions": dict(p.decisions)}
                    for h, p in per_hand.items()
                }
                for arm, per_hand in self.policies.items()
            },
            "tracker_resets": {
                str(h): [{**r.to_dict(), "t": (None if r.t != r.t else r.t)} for r in t.resets]
                for h, t in self.trackers.items()
            },  # external resets carry t = NaN
            "timing_records": {"frame": self.timing.n_frame, "strike": self.timing.n_strike},
            "audio": self.audio.stats() if self.audio is not None else None,
        }


__all__ = ["HANDS", "SUPPORTED_ARMS", "DecisionPipeline", "FrameResult", "HandFrame"]
