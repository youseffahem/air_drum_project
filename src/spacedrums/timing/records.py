"""``TimingRecord`` collection (Phase 05, Task 05.4; contracts.md section 3.10).

One ``FRAME`` record per processed frame (both hands' tracking done; the anticipator's
``t_inference_done`` when the rule arm ran) and one ``STRIKE`` record per ``CommittedStrike``
(shadow included). Every stamp is a ``t_mono`` instant produced by the stage that owns it
(architecture.md section 5.4); this collector only copies them into the record.

Estimated vs measured audio-out (contracts.md section 3.10 rule): ``t_audio_out_est`` is copied
from the ``AudioEvent`` **only when the audio profile's output latency is MEASURED**
(``audio_out_measured=True``). Without an accepted measurement (Phase 04 criterion 6 is PENDING on
HW-01) the field stays null so that no ``L_sys_est`` can be derived from a placeholder.
``t_audio_out`` / ``t_acoustic_onset`` / ``t_impact_phys`` are never written here (external
measurement / Phase 07 labels only). ``t_impact_est`` of an anticipatory strike is null at commit
time (the crossing has not been observed yet); the offline comparison (Task 05.10) fills the lead
time by matching against the reactive arm's observed crossing.
"""

from __future__ import annotations

from spacedrums.contracts import (
    Arm,
    AudioEvent,
    CommittedStrike,
    FrameSample,
    StrikeCandidate,
    TimingRecord,
)
from spacedrums.timing import CLOCK_ID


class TimingCollector:
    def __init__(
        self,
        *,
        hardware_id: str,
        config_hash: str,
        clock_id: str = CLOCK_ID,
        audio_out_measured: bool = False,
        keep: bool = True,
    ) -> None:
        self.hardware_id = hardware_id
        self.config_hash = config_hash
        self.clock_id = clock_id
        self.audio_out_measured = bool(audio_out_measured)
        self.keep = keep
        self.records: list[TimingRecord] = []
        self.n_frame = 0
        self.n_strike = 0

    def _emit(self, rec: TimingRecord) -> TimingRecord:
        if self.keep:
            self.records.append(rec)
        return rec

    def frame(
        self,
        sample: FrameSample,
        *,
        t_tracking_done: float | None,
        t_inference_done: float | None = None,
        t_features_done: float | None = None,
        arm: Arm | str | None = None,
    ) -> TimingRecord:
        self.n_frame += 1
        return self._emit(
            TimingRecord(
                kind="FRAME",
                frame_id=sample.frame_id,
                strike_id=None,
                hand_id=None,
                arm=Arm(arm) if arm is not None else None,
                t_capture=sample.t_capture,
                t_frame_available=sample.t_frame_available,
                t_tracking_done=t_tracking_done,
                t_features_done=t_features_done,
                t_inference_done=t_inference_done,
                t_candidate=None,
                t_commit=None,
                t_audio_scheduled=None,
                t_audio_out_est=None,
                t_audio_out=None,
                t_acoustic_onset=None,
                t_impact_est=None,
                t_impact_pred=None,
                t_impact_phys=None,
                hardware_id=self.hardware_id,
                config_hash=self.config_hash,
                clock_id=self.clock_id,
            )
        )

    def strike(
        self,
        committed: CommittedStrike,
        candidate: StrikeCandidate,
        sample: FrameSample,
        *,
        t_tracking_done: float | None,
        t_inference_done: float | None,
        audio: AudioEvent | None,
    ) -> TimingRecord:
        if audio is not None and committed.shadow:
            raise ValueError("a shadow commit has no audio event")
        self.n_strike += 1
        return self._emit(
            TimingRecord(
                kind="STRIKE",
                frame_id=committed.frame_id,
                strike_id=committed.strike_id,
                hand_id=committed.hand_id,
                arm=committed.arm,
                t_capture=sample.t_capture,
                t_frame_available=sample.t_frame_available,
                t_tracking_done=t_tracking_done,
                t_features_done=None,
                t_inference_done=t_inference_done,
                t_candidate=candidate.t_candidate,
                t_commit=committed.t_commit,
                t_audio_scheduled=audio.t_audio_scheduled if audio is not None else None,
                t_audio_out_est=(
                    audio.t_audio_out_est if (audio is not None and self.audio_out_measured) else None
                ),
                t_audio_out=None,
                t_acoustic_onset=None,
                t_impact_est=candidate.t_impact_est,
                t_impact_pred=candidate.t_impact_pred,
                t_impact_phys=None,
                hardware_id=self.hardware_id,
                config_hash=self.config_hash,
                clock_id=self.clock_id,
            )
        )


__all__ = ["TimingCollector"]
