from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from spacedrums.audio import AudioScheduler, CallbackMixer
from spacedrums.contracts import schema as contract_schema
from spacedrums.geometry import GeometryEngine, TrajectoryPoint


def test_scheduler_future_target_contract(committed):
    scheduler = AudioScheduler(
        audio_profile_id="p",
        output_latency_measured_s=0.012,
        zone_samples={"snare": "sample"},
        clock=lambda: 1.02,
    )
    event = scheduler.schedule(committed)
    assert event.t_audio_scheduled == 1.02 and event.t_target_play == 1.1
    assert event.t_audio_out_est == 1.1 and event.audio_late_s == 0
    assert scheduler.timing_record_fields(event) == {
        "t_audio_scheduled": 1.02, "t_audio_out_est": 1.1}
    assert contract_schema.is_valid("audio-event", event.to_dict())


def test_scheduler_past_target_earliest_and_estimate(committed):
    late = dataclasses.replace(committed, t_impact_target=0.9)
    event = AudioScheduler(
        audio_profile_id="p",
        output_latency_measured_s=0.012,
        zone_samples={"snare": "sample"},
        clock=lambda: 1.02,
    ).schedule(late)
    assert event.audio_late_s == pytest.approx(0.12)
    assert event.t_audio_out_est == pytest.approx(1.032)


def test_shadow_commit_is_not_scheduled(committed):
    scheduler = AudioScheduler(
        audio_profile_id="p",
        output_latency_measured_s=0.01,
        zone_samples={"snare": "sample"},
        clock=lambda: 1.0,
    )
    with pytest.raises(ValueError, match="shadow"):
        scheduler.schedule(dataclasses.replace(committed, shadow=True))


def test_synthetic_trajectory_to_candidate_to_schedule_to_sample_offset(registry, committed):
    geometry = GeometryEngine(registry, v_min=0.1)
    candidate = geometry.intersect(
        (TrajectoryPoint(1.0, (0.5, 0.2)), TrajectoryPoint(1.1, (0.5, 0.4))),
        source="RULE",
        frame_id=3,
        hand_id="RIGHT",
        t_capture=1.0,
        anticipator_id="rule",
        t_candidate=1.01,
    )
    assert candidate is not None
    strike = dataclasses.replace(
        committed, candidate_id=candidate.candidate_id, t_impact_target=candidate.t_impact_pred
    )
    event = AudioScheduler(
        audio_profile_id="synthetic-profile",
        output_latency_measured_s=0.01,
        zone_samples={"snare": "click"},
        clock=lambda: 1.01,
    ).schedule(strike)
    mixer = CallbackMixer(sample_rate_hz=1000, channels=1)
    mixer.enqueue(event, np.ones(2, np.float32))
    output = mixer.mix(100, 1.0)[:, 0]
    assert np.flatnonzero(output)[0] == 50
    assert candidate.t_impact_pred == pytest.approx(1.05)
