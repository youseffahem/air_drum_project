"""TEST-CONFIG-1: schema-validated loading, fragment merge, cross-field checks, config_hash."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from spacedrums.config import (
    ConfigError,
    canonical_json,
    config_hash,
    deep_merge,
    load_config,
    resolve,
    validate,
    validate_blocks,
    write_resolved,
)

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "configs" / "example.candidate.yaml"
CAMERA = ROOT / "configs" / "camera" / "hw01-integrated-webcam.candidate.yaml"


def test_example_loads_and_hashes():
    cfg = load_config(BASE)
    assert cfg.config_hash.startswith("sha256:") and len(cfg.config_hash) == 71
    assert cfg["meta"]["status"] == "candidate"


def test_camera_fragment_merges_onto_base():
    cfg = load_config(BASE, CAMERA)
    assert cfg["camera_profile"]["profile_id"] == "hw01-integrated-webcam-v0"
    assert cfg["meta"]["phase"] == "02"  # later file wins key by key
    assert cfg["zones"]  # untouched base block survives
    assert cfg["camera_profile"]["native_fps_measured"] is None
    assert cfg["camera_profile"]["grab_return_bias_s"] is None


def test_camera_fragment_validates_on_its_own():
    frag = yaml.safe_load(CAMERA.read_text(encoding="utf-8"))
    validate_blocks(frag, ["meta", "camera_profile", "roi"])
    with pytest.raises(ConfigError):
        validate_blocks({"camera_profile": {"profile_id": "x"}}, ["camera_profile"])
    with pytest.raises(ConfigError):
        validate_blocks(frag, ["nonexistent"])


def test_overrides_and_hash_change():
    a = load_config(BASE, CAMERA)
    b = load_config(BASE, CAMERA, overrides={"camera_profile": {"requested_fps": 60}})
    assert b["camera_profile"]["requested_fps"] == 60
    assert a.config_hash != b.config_hash
    assert b["camera_profile"]["queue"]["max_frames"] == a["camera_profile"]["queue"]["max_frames"]


def test_hash_is_key_order_independent_and_type_sensitive():
    d1 = {"b": 1, "a": {"y": 2.5, "x": [1, 2]}}
    d2 = {"a": {"x": [1, 2], "y": 2.5}, "b": 1}
    assert config_hash(d1) == config_hash(d2)
    assert canonical_json(d1) == b'{"a":{"x":[1,2],"y":2.5},"b":1}'
    assert config_hash({"v": 30}) != config_hash({"v": 30.0})  # different documents on purpose


def test_nan_forbidden():
    with pytest.raises(ConfigError):
        config_hash({"v": float("nan")})


def test_schema_violation_is_reported():
    cfg = resolve(BASE, CAMERA)
    cfg["camera_profile"]["native_fps_measured"] = {"value_fps": 30.0}  # no run_id (I-5)
    with pytest.raises(ConfigError, match="schema"):
        validate(cfg)
    cfg = resolve(BASE, CAMERA)
    cfg["camera_profile"]["grab_return_bias_s"] = {"value_s": 0.01}  # no run_id
    with pytest.raises(ConfigError, match="schema"):
        validate(cfg)


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda c: c["tracking"].update(c_min=0.9, c_valid=0.5), "c_min"),
        (lambda c: c["roi"].update(px=[600, 0, 100, 100]), "roi.px"),
        (lambda c: c["camera_profile"]["exposure"].update(mode="MANUAL", value=None), "exposure.value"),
        (lambda c: c["camera_profile"]["exposure"].update(mode="AUTO", value=-6), "exposure.value"),
    ],
)
def test_cross_field_checks(mutate, needle):
    cfg = resolve(BASE, CAMERA)
    mutate(cfg)
    with pytest.raises(ConfigError, match=needle):
        validate(cfg)


def test_schema_1_0_documents_remain_valid():
    # The example became a 1.2 document in Phase 03 (hands block, ADR-0014); a 1.0 document is the
    # same file without that block and without the 1.1 keys.
    cfg = resolve(BASE)
    del cfg["hands"]
    del cfg["stick"]
    cfg["meta"]["schema_version"] = "1.0"
    assert "pixel_format" not in cfg["camera_profile"]
    validate(cfg)


def test_pixel_format_pattern():
    cfg = resolve(BASE, CAMERA)
    cfg["camera_profile"]["pixel_format"] = "MJPG"
    validate(cfg)
    cfg["camera_profile"]["pixel_format"] = "MJPEG"
    with pytest.raises(ConfigError):
        validate(cfg)


def test_write_resolved_round_trips(tmp_path):
    cfg = load_config(BASE, CAMERA)
    out = write_resolved(cfg, tmp_path / "config.resolved.yaml")
    back = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert back == cfg.data
    assert config_hash(back) == cfg.config_hash
    assert cfg.config_hash in out.read_text(encoding="utf-8")


def test_deep_merge_does_not_mutate_inputs():
    base = {"a": {"b": 1}, "l": [1, 2]}
    snap = copy.deepcopy(base)
    merged = deep_merge(base, {"a": {"c": 2}, "l": [3]})
    assert base == snap
    assert merged == {"a": {"b": 1, "c": 2}, "l": [3]}


def test_load_config_needs_input():
    with pytest.raises(ConfigError):
        load_config()


def test_resolved_config_is_json_serialisable():
    cfg = load_config(BASE, CAMERA)
    json.dumps(cfg.data)


def test_hands_block_requires_schema_1_2():
    """ADR-0014 cross-field rule: a 1.0/1.1 document may not carry the hands block."""
    doc = resolve(BASE)
    doc["meta"]["schema_version"] = "1.1"
    with pytest.raises(ConfigError, match="hands block requires meta.schema_version >= 1.2"):
        validate(doc)
    doc["meta"]["schema_version"] = "1.2"
    validate(doc)
    del doc["hands"]
    doc["meta"]["schema_version"] = "1.1"
    with pytest.raises(ConfigError, match="stick block requires"):
        validate(doc)  # the stick block is a 1.2 block too
    del doc["stick"]
    validate(doc)  # older documents without the blocks stay loadable


def test_camera_fragment_merge_keeps_hands_block_and_declares_1_2():
    cfg = load_config(BASE, CAMERA)
    assert cfg["meta"]["schema_version"] == "1.2"
    assert cfg["hands"]["running_mode"] in ("VIDEO", "IMAGE")


@pytest.mark.parametrize("cap, ok", [(0.3, True), (0.5, True), (0.6, False), (0.2, False), (0.9, False)])
def test_ambiguous_score_cap_must_map_to_degraded(cap, ok):
    """Task 03.2 rule: c_min (0.3 in the example) <= cap < c_valid (0.6) so ambiguity is never VALID."""
    doc = resolve(BASE)
    doc["hands"]["identity"]["ambiguous_score_cap"] = cap
    if ok:
        validate(doc)
    else:
        with pytest.raises(ConfigError, match="ambiguous_score_cap"):
            validate(doc)
