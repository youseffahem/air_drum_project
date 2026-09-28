"""Runtime safety-invariant monitor for the live loop (Phase 17, Task 17.2).

``InvariantMonitor.observe(result, pipeline)`` audits one ``FrameResult`` of ``DecisionPipeline``:

    I1  no CommittedStrike while TrackState.status is outside the allowed set    (CommitAuditor)
    I2  no record consumed or emitted with t_capture later than the current frame; delivered frames
        strictly increase; a reactive crossing time never lies after the current frame; no commit is
        decided before its frame was captured; tracker and model histories hold only delivered frames
    I3  refractory per hand x zone and per hand, per arm stream and audible stream  (CommitAuditor)
    I4  at most one commit per observed entry episode, per arm and audible stream   (CommitAuditor)
    I5  no commit in the frame of an arm switch or model fallback (the transition window); no commit
        from the model arm once it is disabled; ``shadow`` is true exactly for non-active arms
    I6  every AudioEvent belongs to a non-shadow CommittedStrike of the same frame, every audible
        commit is scheduled exactly once, and the audio engine never scheduled anything else

Modes: ``raise`` (test builds: the first violation raises ``InvariantViolation``), ``log`` (release:
``logging.error`` and continue), ``collect`` (campaign counting: silent, counted). Violations are
counted per invariant in every mode; ``checks`` counts what was examined so a zero is not vacuous.

The monitor is an auditor: it reads the result and the pipeline's public state after the step and
never changes either; the decision path does not depend on it.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from spacedrums.commit.invariants import INVARIANTS, CommitAuditor, InvariantViolation, Violation
from spacedrums.contracts import HandId

log = logging.getLogger(__name__)
EPS = 1e-9
MODES = ("raise", "log", "collect")


class InvariantMonitor:
    def __init__(
        self,
        *,
        commit_settings,
        registry,
        mode: str = "raise",
        audio_expected: bool = False,
        keep: int = 200,
        settings_by_arm=None,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.mode = mode
        self.audio_expected = bool(audio_expected)
        self.auditor = CommitAuditor(commit_settings, registry, settings_by_arm=settings_by_arm)
        self.keep = int(keep)
        self.counts: Counter[str] = Counter({k: 0 for k in INVARIANTS})
        self.checks: Counter[str] = Counter()
        self.violations: list[Violation] = []
        self.frames = 0
        self._previous = None
        self._previous_seq = 0
        self._audible_total = 0

    @classmethod
    def for_pipeline(cls, pipeline, *, mode: str = "raise", keep: int = 200) -> InvariantMonitor:
        return cls(
            commit_settings=pipeline.commit_settings,
            settings_by_arm=pipeline.commit_settings_by_arm,
            registry=pipeline.registry,
            mode=mode,
            audio_expected=pipeline.audio is not None,
            keep=keep,
        )

    # -- main entry --------------------------------------------------------------------------
    def observe(self, result, pipeline=None) -> list[Violation]:
        self.frames += 1
        sample = result.sample
        found: list[Violation] = []
        found += self._frame_order(sample)
        found += self._records(result, pipeline)
        found += self._transitions(result, pipeline)
        found += self._audio(result, pipeline)
        found += self.auditor.audit_frame(
            frame_id=sample.frame_id,
            t_capture=sample.t_capture,
            t_now=result.t_now,
            tracks={h: hf.track for h, hf in result.hands.items()},
            commits=result.commits,
        )
        self._handle(found)
        return found

    def finish(self) -> dict[str, Any]:
        self.auditor.finish()
        return self.summary()

    def summary(self) -> dict[str, Any]:
        checks = Counter(self.checks)
        checks.update(self.auditor.checks)
        return {
            "mode": self.mode,
            "frames": self.frames,
            "violations": dict(sorted(self.counts.items())),
            "violations_total": sum(self.counts.values()),
            "checks": dict(sorted(checks.items())),
            "auditor": self.auditor.summary(),
            "first_violations": [v.to_dict() for v in self.violations[:20]],
            "definitions": INVARIANTS,
        }

    # -- I2 --------------------------------------------------------------------------------
    def _frame_order(self, sample) -> list[Violation]:
        out: list[Violation] = []
        previous, self._previous = self._previous, sample
        self.checks["I2"] += 1
        if previous is not None and not (
            sample.frame_id > previous.frame_id and sample.t_capture > previous.t_capture
        ):
            out.append(
                Violation(
                    "I2",
                    sample.frame_id,
                    sample.t_capture,
                    "delivered frames do not strictly increase",
                    {"previous_frame_id": previous.frame_id, "previous_t_capture": previous.t_capture},
                )
            )
        return out

    def _records(self, result, pipeline) -> list[Violation]:
        sample = result.sample
        t = sample.t_capture
        out: list[Violation] = []

        def later(kind: str, t_record: float | None, hand: HandId, **extra: Any) -> None:
            self.checks["I2"] += 1
            if t_record is None or t_record > t + EPS:
                out.append(
                    Violation(
                        "I2",
                        sample.frame_id,
                        t,
                        f"{kind} with t_capture {t_record!r} after the current frame",
                        {"hand_id": str(hand), "record": kind, **extra},
                    )
                )

        for h, hf in result.hands.items():
            track = hf.track
            self.checks["I2"] += 1
            if track.frame_id != sample.frame_id or track.t_capture != t:
                out.append(
                    Violation(
                        "I2",
                        sample.frame_id,
                        t,
                        "TrackState is not the current frame's",
                        {"hand_id": str(h), "track_frame_id": track.frame_id},
                    )
                )
            for kind, pred in (("rule prediction", hf.prediction), ("model prediction", hf.model_prediction)):
                if pred is not None:
                    later(kind, pred.t_capture, h)
            for c in hf.candidates:
                later("candidate", c.t_capture, h, candidate_id=c.candidate_id)
                if c.t_impact_est is not None:
                    later("reactive crossing time", c.t_impact_est, h, candidate_id=c.candidate_id)
            if hf.features is not None:
                later("features", hf.features.t_capture, h)
            for c in hf.commits:
                later("commit", c.t_capture, h, strike_id=c.strike_id)
                self.checks["I2"] += 1
                if c.t_commit + EPS < c.t_capture:
                    out.append(
                        Violation(
                            "I2",
                            sample.frame_id,
                            t,
                            "commit decided before its frame was captured",
                            {"strike_id": c.strike_id, "t_commit": c.t_commit},
                        )
                    )
        if pipeline is not None:
            for h, tracker in pipeline.trackers.items():
                for state in tracker.history:
                    later("tracker history", state.t_capture, h)
            model = getattr(pipeline, "model_arm", None)
            if model is not None:
                for h, states in model.histories.items():
                    for state in states:
                        later("model input history", state.t_capture, h)
        return out

    # -- I5 --------------------------------------------------------------------------------
    def _transitions(self, result, pipeline) -> list[Violation]:
        sample = result.sample
        out: list[Violation] = []
        seq = result.transition_seq
        changed, self._previous_seq = seq != self._previous_seq, seq
        commits = result.commits
        if changed:
            self.checks["I5"] += 1
            if commits:
                out.append(
                    Violation(
                        "I5",
                        sample.frame_id,
                        sample.t_capture,
                        f"{len(commits)} commit(s) in an arm-switch / fallback frame",
                        {"strike_ids": [c.strike_id for c in commits]},
                    )
                )
        model_label = getattr(pipeline, "model_label", None) if pipeline is not None else None
        for c in commits:
            self.checks["I5"] += 1
            if result.active_arm is not None and c.shadow != (c.arm != result.active_arm):
                out.append(
                    Violation(
                        "I5",
                        sample.frame_id,
                        sample.t_capture,
                        f"shadow={c.shadow} for arm {c.arm} while {result.active_arm} is active",
                        {"strike_id": c.strike_id},
                    )
                )
            if result.model_disabled and model_label is not None and c.arm == model_label:
                out.append(
                    Violation(
                        "I5",
                        sample.frame_id,
                        sample.t_capture,
                        f"commit from disabled model arm {c.arm}",
                        {"strike_id": c.strike_id},
                    )
                )
        return out

    # -- I6 --------------------------------------------------------------------------------
    def _audio(self, result, pipeline) -> list[Violation]:
        sample = result.sample
        out: list[Violation] = []
        audible = {c.strike_id: c for c in result.commits if not c.shadow}
        scheduled = Counter(e.strike_id for e in result.audio)
        for e in result.audio:
            self.checks["I6"] += 1
            c = audible.get(e.strike_id)
            if c is None:
                out.append(
                    Violation(
                        "I6",
                        sample.frame_id,
                        sample.t_capture,
                        "audio event without a non-shadow commit of this frame",
                        {"strike_id": e.strike_id},
                    )
                )
            elif abs(e.gain - c.gain) > EPS:
                out.append(
                    Violation(
                        "I6",
                        sample.frame_id,
                        sample.t_capture,
                        "audio gain differs from the commit's gain",
                        {"strike_id": e.strike_id},
                    )
                )
        if self.audio_expected:
            for strike_id in audible:
                self.checks["I6"] += 1
                if scheduled[strike_id] != 1:
                    out.append(
                        Violation(
                            "I6",
                            sample.frame_id,
                            sample.t_capture,
                            f"audible commit scheduled {scheduled[strike_id]} times",
                            {"strike_id": strike_id},
                        )
                    )
        self._audible_total += len(audible)
        audio = getattr(pipeline, "audio", None) if pipeline is not None else None
        if audio is not None:
            self.checks["I6"] += 1
            if audio.events != self._audible_total:
                out.append(
                    Violation(
                        "I6",
                        sample.frame_id,
                        sample.t_capture,
                        f"audio events {audio.events} != audible commits {self._audible_total}",
                        {},
                    )
                )
                self._audible_total = audio.events  # report a divergence once
        return out

    # -- handling --------------------------------------------------------------------------
    def _handle(self, found: list[Violation]) -> None:
        for v in found:
            self.counts[v.invariant] += 1
            if len(self.violations) < self.keep:
                self.violations.append(v)
            if self.mode == "raise":
                raise InvariantViolation(v)
            if self.mode == "log":
                log.error("safety invariant %s violated at frame %d: %s", v.invariant, v.frame_id, v.message)


__all__ = ["MODES", "InvariantMonitor"]
