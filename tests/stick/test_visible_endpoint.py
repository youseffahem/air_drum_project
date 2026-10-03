"""Visible synthetic pixels exercise foreshortening and refusal of length fallbacks."""

import pytest
from test_estimators import ROI, _obs, _view

from spacedrums.contracts import HandId
from spacedrums.stick import StickSettings
from spacedrums.stick.visible import VisibleEndpointEstimator


@pytest.mark.parametrize("length", [50.0, 80.0, 120.0, 240.0, 300.0])
def test_visible_endpoint_follows_actual_pixel_length(length):
    estimator = VisibleEndpointEstimator(StickSettings())
    rec = estimator.estimate(_view(stick_len=length), _obs())
    assert rec.present, estimator.evidence
    assert rec.tip[1] * ROI.h == pytest.approx(350 - length, abs=8.0)
    assert estimator.evidence[HandId.RIGHT].kind == "MEASURED"


def test_blank_image_never_emits_guessed_tip():
    estimator = VisibleEndpointEstimator(StickSettings())
    rec = estimator.estimate(_view(stick=False), _obs())
    assert not rec.present
    assert estimator.evidence[HandId.RIGHT].kind != "MEASURED"


def test_image_clipped_stick_is_not_a_measured_endpoint():
    estimator = VisibleEndpointEstimator(StickSettings())
    rec = estimator.estimate(_view(stick_len=390), _obs())
    assert not rec.present
    assert estimator.evidence[HandId.RIGHT].reason == "CLIPPED_ENDPOINT"


def test_absence_cannot_reuse_old_endpoint():
    estimator = VisibleEndpointEstimator(StickSettings())
    assert estimator.estimate(_view(), _obs()).present
    assert not estimator.estimate(_view(1, 1.033, stick=False), _obs(1, 1.033)).present


def test_endpoint_is_causal_and_per_hand_independent():
    a, b = (VisibleEndpointEstimator(StickSettings()) for _ in range(2))
    left = a.estimate(_view(), _obs(hand=HandId.LEFT))
    right = a.estimate(_view(), _obs(hand=HandId.RIGHT))
    assert right == b.estimate(_view(), _obs(hand=HandId.RIGHT))
    assert left == b.estimate(_view(), _obs(hand=HandId.LEFT))
    first = left.to_dict()
    a.estimate(_view(1, 1.033, stick_len=60.0), _obs(1, 1.033, HandId.LEFT))
    assert first == left.to_dict()
