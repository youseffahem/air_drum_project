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
(tests); the application driver adds perception and passes its start stamp for the total budget.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from spacedrums.app.arms import MODEL_ARMS, ArmSwitch, build_model_arm, check_zone_features
from spacedrums.app.audio_out import AudioOutput
from spacedrums.commit import CommitSettings, PerHandCommitPolicy
from spacedrums.config import config_hash as _hash
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
from spacedrums.prediction.budget_monitor import BudgetMonitor, CadenceMonitor
from spacedrums.prediction.fallback import FallbackEvent, fallback_target
from spacedrums.timing import now
from spacedrums.timing.records import TimingCollector
from spacedrums.tracking import CausalTracker, TrackerSettings

HANDS = (HandId.LEFT, HandId.RIGHT)
SUPPORTED_ARMS = (Arm.A, Arm.B, *MODEL_ARMS)
Observations = Mapping[HandId, tuple[HandObservation, StickObservation]]


@dataclass
class HandFrame:
    track: TrackState
    prediction: TrajectoryPrediction | None = None
    reactive: tuple[StrikeCandidate, ...] = ()
    rule: StrikeCandidate | None = None
    commits: list[CommittedStrike] = field(default_factory=list)
    audio: list[AudioEvent] = field(default_factory=list)
    model_prediction: TrajectoryPrediction | None = None
    model_candidate: StrikeCandidate | None = None
    features: Any = None
    t_features_done: float | None = None
    decision_traces: list[dict[str, Any]] = field(default_factory=list)

    @property
    def candidates(self) -> tuple[StrikeCandidate, ...]:
        return (
            self.reactive
            + ((self.rule,) if self.rule is not None else ())
            + ((self.model_candidate,) if self.model_candidate is not None else ())
        )


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
    """Tracking -> reactive/rule/model geometry -> commit per arm -> audio -> timing and fallback."""

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
        model_factory=build_model_arm,
    ) -> None:
        self.cfg = cfg
        self.registry = registry
        self.calibration = cfg.get("calibration")
        if self.calibration is not None:
            # Phase 14 (ADR-0037): geometry, features and commits share the applied calibration's zones.
            if _hash(cfg["zones"]) != self.calibration["zones_hash"] or tuple(registry) != tuple(
                ZoneRegistry.from_config(cfg["zones"])
            ):
                raise AssertionError("the geometry registry must use the applied calibration's zones")
        self.feature_layout = None
        self.session_id = session_id
        self.clock = clock
        self.active_arm = Arm(active_arm)
        self.shadow_arms = tuple(Arm(a) for a in shadow_arms if Arm(a) is not self.active_arm)
        for arm in (self.active_arm, *self.shadow_arms):
            if arm not in SUPPORTED_ARMS:
                raise ValueError(f"supported arms are A, B, C-GRU and C-TCN, got {arm}")
        self.arms: tuple[Arm, ...] = tuple(dict.fromkeys((self.active_arm, *self.shadow_arms)))
        requested_models = [a for a in self.arms if a in MODEL_ARMS]
        if len(requested_models) > 1:
            raise ValueError("one configured model arm per session")
        self.model_arm = None
        self.model_label = requested_models[0] if requested_models else None
        self.model_error = None
        self.fallback_events = []
        self._skip_commits = False
        self._previous_sample = None
        self.fallback = cfg["anticipator"].get("fallback") or {"enabled": False}
        self.inference_budget = self.processing_budget = self.cadence = None
        load_error = None
        if requested_models:
            if cfg["anticipator"]["type"] != "model":
                raise ValueError("arms A and B require no model; C requires anticipator.type = model")
            # Baselines are kept warm for safe, immediate fallback.
            self.arms = tuple(
                dict.fromkeys((*self.arms, Arm.A, *([Arm.B] if cfg["anticipator"].get("rule") else [])))
            )
            if not cfg["anticipator"].get("rule"):
                self.arms = tuple(a for a in self.arms if a is not Arm.B)
            try:
                self.model_arm = model_factory(cfg, clock=clock)
                if self.model_label.value != "C-" + self.model_arm.manifest["family"].upper():
                    raise ValueError("requested model arm differs from verified family")
                m = cfg["anticipator"]["model"]
                self.cadence = CadenceMonitor(
                    self.model_arm.manifest["dt_step"], m["cadence_window_frames"], m["cadence_tolerance"]
                )
            except (OSError, ValueError, KeyError, RuntimeError, ImportError) as exc:
                if not self.fallback["enabled"]:
                    raise
                load_error = f"load failure: {type(exc).__name__}: {exc}"
                self.model_arm = None
            if self.fallback["enabled"]:
                self.inference_budget = BudgetMonitor(
                    self.fallback["budget_s"], self.fallback["window_frames"]
                )
                self.processing_budget = BudgetMonitor(
                    self.fallback["processing_budget_s"], self.fallback["window_frames"]
                )
        if self.model_arm is not None:
            self.feature_layout = check_zone_features(self.model_arm, cfg)  # Task 14.7 runtime assertion
        self.shadow_arms = tuple(a for a in self.arms if a is not self.active_arm)
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
        rule_cfg = {**cfg, "anticipator": {**cfg["anticipator"], "type": "rule"}}
        self.rule_settings = RuleSettings.from_config(rule_cfg) if Arm.B in self.arms else None
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
        self.switch = ArmSwitch(self.arms, self.active_arm)
        self.arm_switches = self.switch.events
        for h in HANDS:
            self.trackers[h].reset(ResetReason.SESSION_START)
            for arm in self.arms:
                self.policies[arm][h].reset(ResetReason.SESSION_START)
        if load_error:
            self._fallback(load_error, clock())

    # -- runtime switch (Task 05.5) --------------------------------------------------------
    def set_active_arm(self, arm: Arm | str, t_now: float) -> None:
        arm = Arm(arm)
        if arm in MODEL_ARMS and (self.model_arm is None or self.model_error):
            raise ValueError("model unavailable; restart after correcting the recorded fault")
        if not self.switch.select(arm, t_now):
            return
        self.active_arm = arm
        self.shadow_arms = tuple(a for a in self.arms if a is not arm)
        for a in self.arms:
            for h in HANDS:
                self.policies[a][h].shadow = a is not arm
                self.policies[a][h].reset(ResetReason.ARM_SWITCH)  # IDLE; timers persist (reset matrix)
        self._skip_commits = True

    def _fallback(self, reason, t):
        if self.model_error is not None:
            return
        if not self.fallback["enabled"]:
            raise RuntimeError(reason)
        target = fallback_target(self.fallback["to"], self.arms)
        self.model_error = reason
        if self.model_arm is not None:
            self.model_arm.reset()
        # A faulty shadow model is disabled without changing the sounding baseline.
        if self.active_arm in MODEL_ARMS:
            self.set_active_arm(target, t)
        self.fallback_events.append(
            FallbackEvent(t, str(self.model_label), str(self.active_arm), reason).to_dict()
        )
        self._skip_commits = True

    # -- per-frame -------------------------------------------------------------------------
    def step(
        self,
        sample: FrameSample,
        observations: Observations,
        *,
        t_now: float | None = None,
        processing_started: float | None = None,
        replay_measured: bool = False,
    ) -> FrameResult:
        start = self.clock() if processing_started is None else processing_started
        old = self._previous_sample
        if old is not None and (sample.frame_id <= old.frame_id or sample.t_capture <= old.t_capture):
            raise ValueError("delivered frames must strictly increase")
        for h in HANDS:
            for obs in observations[h]:
                if (obs.frame_id, obs.t_capture, obs.hand_id) != (sample.frame_id, sample.t_capture, h):
                    raise AssertionError("only observations from the current delivered frame are allowed")
        self._previous_sample = sample
        self.frames += 1
        if self.cadence and not self.model_error:
            try:
                self.cadence.observe(sample)
            except ValueError as exc:
                self._fallback(str(exc), self.clock() if t_now is None else t_now)
        hands: dict[HandId, HandFrame] = {}
        # 1. tracking, both hands (fixed order)
        for h in HANDS:
            hand_obs, stick_obs = observations[h]
            track = self.trackers[h].update(hand_obs, stick_obs, sample.t_capture)
            hands[h] = HandFrame(track=track)
            if track.reset_reason is not None:
                self.geometry.reset_hand(h)
                for arm in self.arms:
                    self.policies[arm][h].reset(track.reset_reason)
                if h in self.anticipators:
                    self.anticipators[h].reset(track.reset_reason)
        t_tracking_done = self.clock()
        # 2. geometry on the observed trajectory (A) and rule extrapolation + geometry (B)
        t_inference_done: float | None = None
        model_inference_s = 0.0
        model_ran = False
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
            if self.model_arm is not None and not self.model_error:
                try:
                    pred = self.model_arm.step(
                        track,
                        delivered_t=sample.t_capture,
                        hand=observations[h][0],
                        stick=observations[h][1],
                        frame=sample,
                    )
                    hf.features = self.model_arm.features[h]
                    stamps = self.model_arm.stamps[h]
                    hf.t_features_done = stamps["t_features_done"]
                    t_inference_done = stamps["t_inference_done"]
                    model_inference_s += stamps["inference_s"]
                    model_ran = True
                    hf.model_prediction = pred
                    if pred is not None:
                        t_inference_done = pred.t_inference_done
                        candidate = self.geometry.intersect_prediction(
                            pred, current_position=track.tip_filtered, source=CandidateSource.MODEL
                        )
                        if candidate is not None:
                            # Phase 10 temporal_candidate semantics, shared geometry owns the strike.
                            normal = self.registry[candidate.zone_id].inward_normal
                            speed = sum(
                                v * n for v, n in zip(candidate.crossing_velocity, normal, strict=True)
                            )
                            hf.model_candidate = replace(candidate, intensity_proxy=max(0.0, speed))
                except (OSError, ValueError, RuntimeError) as exc:
                    self._fallback(
                        f"inference failure: {type(exc).__name__}: {exc}",
                        self.clock() if t_now is None else t_now,
                    )
        if model_ran and self.inference_budget and self.inference_budget.observe(model_inference_s):
            self._fallback(
                "inference p95 exceeds configured budget", self.clock() if t_now is None else t_now
            )
        # 3. commit per arm, per hand; audio for the active arm; timing
        if replay_measured:
            if t_now is not None:
                raise ValueError("choose explicit replay time or measured replay time")
            t_now = sample.t_frame_available + max(0.0, self.clock() - start)
        t_now = float(self.clock() if t_now is None else t_now)
        timing: list[TimingRecord] = [
            self.timing.frame(
                sample,
                t_tracking_done=t_tracking_done,
                t_inference_done=t_inference_done,
                t_features_done=max(
                    (h.t_features_done for h in hands.values() if h.t_features_done is not None), default=None
                ),
                arm=self.model_label if model_ran else (Arm.B if t_inference_done is not None else None),
            )
        ]
        for h in HANDS:
            hf = hands[h]
            by_arm: dict[Arm, list[StrikeCandidate]] = {arm: [] for arm in self.arms}
            for c in hf.candidates:
                label = self.model_label if c.source is CandidateSource.MODEL else _arm_of(c.source)
                by_arm.setdefault(label, []).append(c)
            candidate_by_id = {c.candidate_id: c for c in hf.candidates}
            for arm in self.arms:
                if self._skip_commits or (arm in MODEL_ARMS and self.model_error):
                    continue
                commits = self.policies[arm][h].step(
                    by_arm.get(arm, []), hf.track, t_now, dropped_since_last=sample.dropped_since_last
                )
                hf.decision_traces.extend(
                    {"arm": str(arm), "hand_id": str(h), **trace.to_dict()}
                    for trace in self.policies[arm][h].trace
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
                                hf.model_prediction.t_inference_done
                                if arm in MODEL_ARMS and hf.model_prediction
                                else hf.prediction.t_inference_done
                                if arm is Arm.B and hf.prediction
                                else None
                            ),
                            t_features_done=hf.t_features_done if arm in MODEL_ARMS else None,
                            audio=event,
                        )
                    )
        self._skip_commits = False
        if (
            model_ran
            and self.processing_budget
            and self.processing_budget.observe(max(0, self.clock() - start))
        ):
            self._fallback("total processing p95 exceeds configured budget", t_now)
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
            "fallback_events": list(self.fallback_events),
            "model": {
                "model_id": self.model_arm.model_id if self.model_arm else None,
                "requested": self.cfg["anticipator"].get("model"),
                "error": self.model_error,
                "recovery": "disabled; restart required",
                "inference_p95_s": self.inference_budget.p95 if self.inference_budget else None,
                "processing_p95_s": self.processing_budget.p95 if self.processing_budget else None,
                "feature_layout": self.feature_layout,
            },
            "calibration": (
                None
                if self.calibration is None
                else {
                    k: self.calibration[k]
                    for k in (
                        "calibration_id",
                        "calibration_hash",
                        "provenance_kind",
                        "template_layout_id",
                        "fit",
                        "validation_passed",
                    )
                }
            ),
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
