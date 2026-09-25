"""Phase 11 Task 11.5 and the aux contract bump: agreement flags, gates, config 1.5, schema 1.1."""

import copy
from dataclasses import replace

import jsonschema
import pytest

from spacedrums.config import load_config
from spacedrums.config.loader import ConfigError
from spacedrums.config.loader import validate as validate_config
from spacedrums.contracts import StrikeCandidate, TrajectoryAux, TrajectoryPrediction
from spacedrums.contracts.schema import validate
from spacedrums.models.temporal.consistency import AuxGate, AuxHeadSettings, consistency_flags

ZONES = ("hihat", "snare", "tom1", "crash_ride")


def candidate(**changes):
    base = StrikeCandidate(
        "geometry-c1", 3, 10.0, "LEFT", "snare", "MODEL", "GEOMETRY", "temporal-mt-gru-v1",
        10.05, None, 0.05, (0.40, 0.58), (0.0, 2.0), None, 2.0, 10.0,
    )  # fmt: skip
    return replace(base, **changes)


def prediction(**aux):
    heads = dict(
        strike_prob_within_H=0.9,
        tti=0.06,
        zone_logits=(0.0, 3.0, 0.0, 0.0),
        zone_ids=ZONES,
        impact_pos=(0.41, 0.58),
        intensity_proxy=1.8,
    )
    heads.update(aux)
    return TrajectoryPrediction(
        3, 10.0, "LEFT", "temporal-mt-gru-v1", None, 2, 0.05, None, ((0.4, 0.55), (0.4, 0.62)),
        None, None, None, TrajectoryAux(**heads), 10.0,
    )  # fmt: skip


def test_flags_compare_heads_with_geometry_and_are_null_without_candidate_or_head():
    s = AuxHeadSettings(tti_tolerance_s=0.02, position_tolerance=0.02, intensity_tolerance=0.3)
    assert consistency_flags(prediction().aux, candidate(), s) == {
        "zone": True,
        "tti": True,
        "position": True,
        "intensity": True,
    }
    flags = consistency_flags(
        prediction(zone_logits=(5.0, 0, 0, 0), tti=0.2, intensity_proxy=0.5).aux, candidate(), s
    )
    assert flags == {"zone": False, "tti": False, "position": True, "intensity": False}
    assert consistency_flags(prediction().aux, None, s) is None
    bare = TrajectoryAux()
    assert consistency_flags(bare, candidate(), s) is None
    partial = consistency_flags(TrajectoryAux(tti=0.05), candidate(), s)
    assert partial == {"zone": None, "tti": True, "position": None, "intensity": None}


def test_default_gate_passes_geometry_candidate_strips_probability_and_annotates():
    gate = AuxGate(AuxHeadSettings(), ("trajectory",))
    flagged, out = gate(prediction(), candidate(strike_probability=0.2))
    assert out == candidate(strike_probability=None)  # commit.p_commit never sees head output
    assert dict(flagged.aux.consistency_flags)["zone"] is True
    validate("trajectory-prediction", flagged.to_dict())
    assert gate(prediction(), None) == (prediction(), None)
    assert gate.decisions["PASS"] == 1


def test_probability_and_agreement_gates_and_head_intensity():
    heads = ("trajectory", "strike", "tti", "zone", "position", "intensity")
    p_gate = AuxGate(AuxHeadSettings(use_p_aux=True, p_aux=0.95), heads)
    assert p_gate(prediction(), candidate())[1] is None and p_gate.decisions["REJECT_P_AUX"] == 1
    assert AuxGate(AuxHeadSettings(use_p_aux=True, p_aux=0.5), heads)(prediction(), candidate())[1]
    agree = AuxGate(AuxHeadSettings(use_agreement=True, agreement_checks=("zone", "tti")), heads)
    assert agree(prediction(), candidate())[1] is not None
    assert agree(prediction(tti=0.3), candidate())[1] is None
    zone_only = AuxGate(AuxHeadSettings(use_agreement=True, agreement_checks=("zone",)), heads)
    assert zone_only(prediction(zone_logits=None, zone_ids=None), candidate())[1] is None  # null fails
    swap = AuxGate(AuxHeadSettings(intensity_source="head"), heads)
    assert swap(prediction(intensity_proxy=1.25), candidate())[1].intensity_proxy == 1.25
    with pytest.raises(ValueError, match="absent heads"):
        AuxGate(AuxHeadSettings(use_p_aux=True, intensity_source="head"), ("trajectory", "zone"))
    with pytest.raises(ValueError, match="geometry-derived"):
        AuxGate(AuxHeadSettings(), heads)(prediction(), candidate(derivation="DIRECT_HEAD"))


def test_aux_heads_config_block_is_optional_validated_and_off_by_default():
    cfg = load_config("configs/prototype.candidate.yaml")
    assert "aux_heads" not in cfg["commit"] and AuxHeadSettings.from_config(cfg) == AuxHeadSettings()
    off = AuxHeadSettings()
    assert not off.use_p_aux and not off.use_agreement and off.intensity_source == "geometry"
    block = {**AuxHeadSettings(use_agreement=True).to_dict(), "p_aux": 0.6}
    data = copy.deepcopy(cfg.data)
    data["meta"]["schema_version"] = "1.5"
    data["commit"]["aux_heads"] = block
    validate_config(data)
    assert AuxHeadSettings.from_config(data) == AuxHeadSettings(use_agreement=True, p_aux=0.6)
    older = copy.deepcopy(data)
    older["meta"]["schema_version"] = "1.4"
    with pytest.raises(ConfigError, match="1.5"):
        validate_config(older)  # the block exists only from config 1.5 (ADR-0028)
    for key, value in (("p_aux", 1.5), ("intensity_source", "force"), ("agreement_checks", []), ("extra", 1)):
        broken = copy.deepcopy(data)
        broken["commit"]["aux_heads"][key] = value
        with pytest.raises(jsonschema.ValidationError):
            validate("config", broken)
    for bad in (
        dict(p_aux=-0.1),
        dict(agreement_checks=("zone", "zone")),
        dict(tti_tolerance_s=float("nan")),
    ):
        with pytest.raises(ValueError):
            AuxHeadSettings(**bad)


def test_trajectory_prediction_1_1_roundtrip_and_1_0_migration():
    flagged = replace(
        prediction(),
        aux=replace(
            prediction().aux,
            consistency_flags={"zone": True, "tti": None, "position": False, "intensity": None},
        ),
    )
    doc = flagged.to_dict()
    assert doc["schema_version"] == "1.1" and doc["aux"]["consistency_flags"]["position"] is False
    validate("trajectory-prediction", doc)
    assert TrajectoryPrediction.from_dict(doc) == flagged
    old = copy.deepcopy(doc)
    old["schema_version"] = "1.0"
    del old["aux"]["consistency_flags"]
    validate("trajectory-prediction", old)  # 1.0 records stay valid (additive minor bump)
    assert TrajectoryPrediction.from_dict(old).aux.consistency_flags is None
    missing = copy.deepcopy(doc)
    del missing["aux"]["consistency_flags"]
    with pytest.raises(jsonschema.ValidationError):
        validate("trajectory-prediction", missing)  # 1.1 requires the (nullable) field
    for bad in ({"zone": True}, {"zone": 1, "tti": None, "position": None, "intensity": None}):
        with pytest.raises(ValueError):
            TrajectoryAux(consistency_flags=bad)
