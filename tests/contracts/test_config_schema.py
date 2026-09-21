"""TEST-SCHEMA-1 — configuration schema (Phase 01, Task 01.7; ADR-0010).

configs/example.candidate.yaml must validate; structural mistakes and
scope violations must be rejected at load time.
"""

from __future__ import annotations

import copy

import pytest
from conftest import is_valid

TOP_LEVEL_REQUIRED = [
    "meta",
    "camera_profile",
    "roi",
    "zones",
    "tracking",
    "anticipator",
    "commit",
    "audio",
    "debug",
]


def test_example_config_validates(validator, config_example):
    v = validator("config")
    errs = list(v.iter_errors(config_example))
    assert not errs, [f"{list(e.absolute_path)}: {e.message}" for e in errs]


@pytest.mark.parametrize("block", TOP_LEVEL_REQUIRED)
def test_top_level_blocks_required(validator, config_example, block):
    v = validator("config")
    cfg = copy.deepcopy(config_example)
    del cfg[block]
    assert not is_valid(v, cfg)


def test_unknown_top_level_key_rejected(validator, config_example):
    v = validator("config")
    cfg = copy.deepcopy(config_example)
    cfg["typo_block"] = {}
    assert not is_valid(v, cfg)


def test_example_is_marked_candidate(config_example):
    assert config_example["meta"]["status"] == "candidate"
    assert config_example["camera_profile"]["native_fps_measured"] is None


def test_native_fps_needs_run_id(validator, config_example):
    v = validator("config")
    cfg = copy.deepcopy(config_example)
    cfg["camera_profile"]["native_fps_measured"] = {"value_fps": 30.0}  # a number without provenance
    assert not is_valid(v, cfg)
    cfg["camera_profile"]["native_fps_measured"] = {
        "value_fps": 30.0,
        "run_id": "20260101-0000-example",
        "method": "placeholder",
    }
    assert is_valid(v, cfg)


def test_trigger_type_foot_is_reserved_not_allowed(validator, config_example):
    v = validator("config")
    cfg = copy.deepcopy(config_example)
    cfg["zones"][0]["trigger_type"] = "FOOT"  # OOS-REF:REQ-207
    assert not is_valid(v, cfg)


def test_allowed_hands_optional_and_restrictable_by_schema(validator, config_example):
    v = validator("config")
    cfg = copy.deepcopy(config_example)
    assert "allowed_hands" not in cfg["zones"][3], "example must show the hand-agnostic default"
    cfg["zones"][0]["allowed_hands"] = ["LEFT"]
    assert is_valid(v, cfg)  # expressible (reserved for Phase 18 experiments), not used in V1
    cfg["zones"][0]["allowed_hands"] = ["LEFT", "LEFT"]
    assert not is_valid(v, cfg)
    cfg["zones"][0]["allowed_hands"] = []
    assert not is_valid(v, cfg)


def test_zone_shape_and_surface_variants(validator, config_example):
    v = validator("config")
    cfg = copy.deepcopy(config_example)
    cfg["zones"][0]["shape"] = {"type": "CIRCLE", "center": [0.5, 0.5], "r": 0.1}
    assert not is_valid(v, cfg)
    cfg = copy.deepcopy(config_example)
    cfg["zones"][0]["impact_surface"] = {
        "type": "ARC",
        "center": [0.2, 0.3],
        "rx": 0.12,
        "ry": 0.06,
        "angle_rad": 0.0,
        "theta_start_rad": 3.3,
        "theta_end_rad": 6.1,
    }
    assert is_valid(v, cfg)


def test_zone_id_pattern(validator, config_example):
    v = validator("config")
    cfg = copy.deepcopy(config_example)
    cfg["zones"][0]["zone_id"] = "Hi-Hat"
    assert not is_valid(v, cfg)


def test_queue_drop_policy_fixed(validator, config_example):
    v = validator("config")
    cfg = copy.deepcopy(config_example)
    cfg["camera_profile"]["queue"]["drop_policy"] = "BLOCK"
    assert not is_valid(v, cfg)


def test_anticipator_type_consistency(validator, config_example):
    v = validator("config")
    cfg = copy.deepcopy(config_example)
    cfg["anticipator"].update(type="model")  # model block still null -> reject
    assert not is_valid(v, cfg)
    cfg["anticipator"]["model"] = {
        "path": "models/example.onnx",
        "hash": "sha256:" + "0" * 64,
        "runtime": "onnxruntime",
        "intra_op_threads": 1,
        "feature_schema_id": "example-fs",
    }
    cfg["anticipator"]["rule"] = None
    assert is_valid(v, cfg)
    cfg["anticipator"]["type"] = "lstm"
    assert not is_valid(v, cfg)


def test_commit_thresholds_ranges(validator, config_example):
    v = validator("config")
    cfg = copy.deepcopy(config_example)
    cfg["commit"]["p_commit"] = 1.5
    assert not is_valid(v, cfg)
    cfg = copy.deepcopy(config_example)
    cfg["commit"]["tti_commit_s"] = -0.01
    assert not is_valid(v, cfg)
    cfg = copy.deepcopy(config_example)
    cfg["commit"]["allow_degraded_commits"] = "yes"
    assert not is_valid(v, cfg)


def test_seconds_not_milliseconds_key_names(schemas):
    """Contract convention: durations are seconds with an _s suffix; no *_ms keys exist."""

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, val in node.items():
                assert not k.endswith("_ms"), f"millisecond key in config schema at {path}/{k}"
                walk(val, f"{path}/{k}")
        elif isinstance(node, list):
            for i, val in enumerate(node):
                walk(val, f"{path}[{i}]")

    walk(schemas["config"]["properties"])


def test_arms_block_optional_but_validated(validator, config_example):
    v = validator("config")
    cfg = copy.deepcopy(config_example)
    del cfg["arms"]
    assert is_valid(v, cfg)
    cfg["arms"] = {"active": "D", "shadow": []}
    assert not is_valid(v, cfg)


# ------------------------------------------------------------ hands block (schema 1.2, Phase 03, ADR-0014)


def test_example_declares_schema_1_2_with_hands_block(config_example):
    assert config_example["meta"]["schema_version"] == "1.2"
    assert config_example["hands"]["detector"] == "mediapipe-hand-landmarker"
    assert config_example["hands"]["swap_handedness"] is False


def test_hands_block_optional_for_older_documents(validator, config_example):
    v = validator("config")
    cfg = copy.deepcopy(config_example)
    del cfg["hands"]
    cfg["meta"]["schema_version"] = "1.1"
    assert is_valid(v, cfg)  # 1.0 / 1.1 documents stay valid (additive minor bump)
    cfg["meta"]["schema_version"] = "1.4"  # unknown version rejected (1.3 exists since Phase 05, ADR-0018)
    assert not is_valid(v, cfg)


def test_geometry_block_is_optional_and_validated(validator, config_example):
    """Schema 1.3 (Phase 05, ADR-0018): optional geometry block with v_min >= 0; unknown keys rejected."""
    v = validator("config")
    cfg = copy.deepcopy(config_example)
    assert "geometry" not in cfg and is_valid(v, cfg)  # 1.2 example has no geometry block and stays valid
    cfg["meta"]["schema_version"] = "1.3"
    cfg["geometry"] = {"v_min": 0.15}
    assert is_valid(v, cfg)
    cfg["geometry"] = {"v_min": -0.1}
    assert not is_valid(v, cfg)
    cfg["geometry"] = {"v_min": 0.15, "v_max": 1.0}
    assert not is_valid(v, cfg)
    cfg["geometry"] = {}
    assert not is_valid(v, cfg)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda h: h.update(detector="openpose"),
        lambda h: h.update(running_mode="LIVE_STREAM"),
        lambda h: h.update(num_hands=0),
        lambda h: h.update(min_hand_detection_confidence=1.5),
        lambda h: h.update(input="CROP"),
        lambda h: h.update(swap_handedness="no"),
        lambda h: h.update(model_complexity=1),   # legacy Solutions knob; absent from the Tasks API
        lambda h: h.pop("model_asset_id"),
    ],
)
def test_hands_block_rejects_invalid_values(validator, config_example, mutation):
    v = validator("config")
    cfg = copy.deepcopy(config_example)
    mutation(cfg["hands"])
    assert not is_valid(v, cfg)


def test_hands_identity_block_required_and_validated(validator, config_example):
    """Task 03.2 (ADR-0014 §10): the identity sub-block is part of the hands block."""
    v = validator("config")
    cfg = copy.deepcopy(config_example)
    assert cfg["hands"]["identity"]["mode"] == "TEMPORAL"
    del cfg["hands"]["identity"]
    assert not is_valid(v, cfg)
    cfg = copy.deepcopy(config_example)
    cfg["hands"]["identity"]["mode"] = "GUESS"
    assert not is_valid(v, cfg)
    cfg = copy.deepcopy(config_example)
    cfg["hands"]["identity"]["gate_distance"] = 0
    assert not is_valid(v, cfg)
    cfg = copy.deepcopy(config_example)
    cfg["hands"]["identity"]["ambiguous_score_cap"] = 1.5
    assert not is_valid(v, cfg)


# ------------------------------------------------------------ stick block (schema 1.2, Phase 03, ADR-0015)


def test_stick_block_present_optional_and_validated(validator, config_example):
    v = validator("config")
    assert config_example["stick"]["method_id"] == "GEOM"
    cfg = copy.deepcopy(config_example)
    del cfg["stick"]
    assert is_valid(v, cfg)  # optional at the schema level (older documents)
    for mutate in (
        lambda st: st.update(method_id="LASER"),
        lambda st: st["axis"].update(method="LSQ"),
        lambda st: st["geom"].update(l_prior=0),
        lambda st: st["marker"].update(hsv_low=[0, 0]),
        lambda st: st["search_region"].pop("length_factor"),
        lambda st: st.update(learned_segmentation=True),  # not a schema field (Open Question)
    ):
        cfg = copy.deepcopy(config_example)
        mutate(cfg["stick"])
        assert not is_valid(v, cfg)
    cfg = copy.deepcopy(config_example)
    cfg["stick"]["method_id"] = "MARKER"  # expressible (fallback / benchmark); labelled by the estimator
    assert is_valid(v, cfg)
