"""TEST-FI-ID-1..4: the Phase 17 single-user identity rule (Task 17.6, ADR-0040). SYNTHETIC candidates.

A second person's hand in the background is farther from the camera, hence smaller. With
``user_min_relative_area`` > 0 such a detection is never assigned to the user's LEFT/RIGHT (it is
counted and logged as ``BACKGROUND_REJECTED``); with the default 0 the assigner is unchanged.
"""

from __future__ import annotations

import pytest
from inv_helpers import RULE_CONFIG

from spacedrums.config import load_config, validate
from spacedrums.contracts import HandId
from spacedrums.hands.identity import IdentityAssigner, IdentityCandidate, IdentityEventKind, IdentitySettings

L, R = HandId.LEFT, HandId.RIGHT


def _cand(i, x, y, label, area, score=0.9):
    return IdentityCandidate(index=i, wrist=(x, y), raw_hand_id=label, raw_score=score, area=area)


def _frames(assigner, frames):
    return [assigner.assign(c, i, 100 + i / 30) for i, c in enumerate(frames)]


def test_default_is_off_and_ids_unchanged():
    s = IdentitySettings()
    assert s.user_min_relative_area == 0.0 and "-ua" not in s.id_fragment()
    assert "-ua0.35" in IdentitySettings(user_min_relative_area=0.35).id_fragment()
    with pytest.raises(ValueError):
        IdentitySettings(user_min_relative_area=1.0)


def test_background_hand_is_not_adopted_when_a_user_hand_disappears():
    user = [_cand(0, 0.3, 0.8, L, 0.02), _cand(1, 0.7, 0.8, R, 0.02)]
    frames = [user] * 10 + [[_cand(0, 0.3, 0.8, L, 0.02), _cand(1, 0.75, 0.2, R, 0.004)]] * 10
    off = _frames(IdentityAssigner(IdentitySettings()), frames)
    on_assigner = IdentityAssigner(IdentitySettings(user_min_relative_area=0.35))
    on = _frames(on_assigner, frames)
    assert R in off[15].assignments  # without the rule the small far hand becomes RIGHT
    assert R not in on[15].assignments and L in on[15].assignments
    assert on_assigner.counters.background_rejected == 10
    assert any(e.kind is IdentityEventKind.BACKGROUND_REJECTED for e in on[15].events)


def test_rule_keeps_both_user_hands_of_similar_size():
    frames = [
        [_cand(0, 0.3, 0.8, L, 0.02 * (1 + 0.3 * (i % 3))), _cand(1, 0.7, 0.8, R, 0.02)] for i in range(30)
    ]
    a = IdentityAssigner(IdentitySettings(user_min_relative_area=0.35))
    results = _frames(a, frames)
    assert all(set(r.assignments) == {L, R} for r in results) and a.counters.background_rejected == 0


def test_config_schema_1_8_accepts_the_rule_and_rejects_bad_values():
    cfg = load_config(RULE_CONFIG).data
    cfg["meta"]["schema_version"] = "1.8"
    cfg["hands"]["identity"]["user_min_relative_area"] = 0.35
    validate(cfg)
    assert IdentitySettings.from_config(cfg["hands"]).user_min_relative_area == 0.35
    cfg["hands"]["identity"]["user_min_relative_area"] = 1.5
    with pytest.raises(Exception):  # noqa: B017 - ConfigError / ValidationError, both acceptable
        validate(cfg)
