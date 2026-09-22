"""TEST-FEATURE-4: actual serialized input guards and batch/streaming session parity."""

import ast
import json
import shutil
import sys
from copy import deepcopy
from pathlib import Path

import jsonschema
import numpy as np
import pytest
from data_helpers import make_session

from spacedrums.contracts import schema as contracts
from spacedrums.data.feature_dataset import load_session
from spacedrums.data.labels.generate import generate_labels
from spacedrums.data.validation import verify_session
from spacedrums.features.batch import load_causal_tracks
from spacedrums.timing.logger import stream_header

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def synthetic_disk_session(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic-features")
    raw, _, _ = make_session(root / "raw", session_id="synthetic-feature-io")
    verify_session(raw)
    labels = generate_labels(raw, root / "labels", dataset_version="ds-v0.0-selftest-features")
    return raw, labels.label_dir


def test_serialized_session_joins_same_frame_observations_and_parity(synthetic_disk_session):
    raw, labels = synthetic_disk_session
    session = load_session(raw, labels, selftest=True)
    assert session.parity["bit_identical"]
    assert session.parity["records_compared"] > 0
    assert session.table.source_kind == "SYNTHETIC"
    for row in session.table.records:
        contracts.validate("kinematic-features", row.to_dict())
    assert session.input_hashes
    assert not any("tracks_reference" in p for p in session.input_hashes)
    assert any(r.mask[session.schema.index["dropped_since_last"]] for r in session.table.records)


def test_no_synthetic_to_participant_coercion(synthetic_disk_session):
    with pytest.raises(ValueError, match="selftest"):
        load_session(*synthetic_disk_session)


def test_corrupted_input_hash_refused(synthetic_disk_session, tmp_path):
    raw, labels = synthetic_disk_session
    dest = tmp_path / "labels"
    shutil.copytree(labels, dest)
    with (dest / "tracks_causal.jsonl").open("a", encoding="utf-8") as f:
        f.write("\n")
    with pytest.raises(ValueError, match="hash"):
        load_session(raw, dest, selftest=True)


@pytest.mark.parametrize("name", ["tracks_reference.jsonl", "tracks_reference-extra.jsonl", "input.jsonl"])
def test_reference_name_guard_before_file_access(tmp_path, name):
    with pytest.raises(ValueError, match="explicitly named causal"):
        load_causal_tracks(tmp_path / name)


def test_renamed_reference_rejected_by_header_and_rows(tmp_path, track_factory):
    p = tmp_path / "tracks_causal.jsonl"
    p.write_text(json.dumps({"schema_version": "1.0", "kind": "ReferenceTrack", "causal": False}) + "\n")
    with pytest.raises(ValueError):
        load_causal_tracks(p)
    header = stream_header(
        record_type="TrackState",
        record_schema_version="1.0",
        session_id="synthetic",
        config_hash="sha256:" + "0" * 64,
        git_sha="0" * 40,
        clock_id="perf_counter",
        producer="REGENERATED",
        derived=True,
    )
    row = track_factory(0).to_dict()
    row["causal"] = False
    p.write_text(json.dumps(header) + "\n" + json.dumps(row) + "\n")
    with pytest.raises(jsonschema.ValidationError):
        load_causal_tracks(p)
    row.pop("causal")
    p.write_text(json.dumps(header) + "\n" + (json.dumps(row) + "\n") * 2)
    with pytest.raises(ValueError, match="monotone"):
        load_causal_tracks(p)


def test_reference_exclusion_static_features_models_and_loader():
    packages = [ROOT / "src/spacedrums" / p for p in ("features", "models")]
    files = [p for pkg in packages for p in pkg.rglob("*.py")]
    files += [ROOT / "src/spacedrums/data/feature_dataset.py"]
    for p in files:
        source = p.read_text(encoding="utf-8")
        # Deliberately stricter than detecting one API: no reference filename in any loading code.
        assert "tracks_reference" not in source, p
        ast.parse(source)


def test_synthetic_fold_export_and_safe_npz_train_stats(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    from _p08_fixture import synthetic_fixture

    from spacedrums.config import load_config
    from spacedrums.data.feature_dataset import export_folds
    from spacedrums.features.windows import WindowParams

    manifest, cv, sessions = synthetic_fixture(load_config(ROOT / "configs/prototype.candidate.yaml"))
    reports = export_folds(manifest, cv, sessions, tmp_path, WindowParams(8, 4, 0.1, 0.3, 2, 1))
    assert len(reports) == 3
    for fold in cv["folds"]:
        out = tmp_path / f"fold-{fold['fold']}"
        stats = json.loads((out / "norm_stats.json").read_text())
        assert set(stats["train_participants"]) == set(fold["train_participants"])
        seen = {}
        for part in ("train", "val", "test"):
            with np.load(out / f"samples.{part}.npz", allow_pickle=False) as f:
                seen[part] = {json.loads(m)["participant"] for m in f["meta"]}
                assert f["anticipation_eligible"].all()
                assert f["M"].shape == f["X"].shape
            assert (out / f"safety.{part}.npz").exists()
        assert not (seen["train"] & seen["val"] or seen["train"] & seen["test"] or seen["val"] & seen["test"])
    altered = deepcopy(cv)
    altered["folds"][0]["train_participants"] += altered["test_participants"]
    with pytest.raises(ValueError, match="leakage"):
        export_folds(manifest, altered, sessions, tmp_path / "bad", WindowParams(8, 4, 0.1, 0.3))


@pytest.mark.parametrize("fault", [None, "split_hash", "participant_overlap", "session", "version", "kind"])
def test_dataset_composition_rechecks_verified_inputs(monkeypatch, fault):
    # UNIT TEST stubs exercise composition; no participant artefact is written.
    sys.path.insert(0, str(ROOT / "scripts"))
    from _p08_fixture import synthetic_fixture

    from spacedrums.config import load_config
    from spacedrums.data import feature_dataset as dataset

    manifest, cv, sessions = synthetic_fixture(load_config(ROOT / "configs/prototype.candidate.yaml"))
    manifest.update(
        {
            "root": "synthetic-unit-only",
            "labels_version": "labels-v1.0",
            "splits": {"split_hash": cv["split_hash"]},
            "label_sets": [],
        }
    )
    by_name, sets = {}, {}
    for s in sessions:
        name = s.table.session_id
        by_name[name] = s
        item = {
            "session_id": name,
            "participant_id": s.table.participant,
            "source_kind": "SYNTHETIC",
            "path": name,
            "set_hash": "sha256:" + "8" * 64,
        }
        manifest["label_sets"].append(item)
        sets[name] = {
            **item,
            "inputs": {"session_dir": name},
            "labels_version": "labels-v1.0",
            "dataset_version": manifest["dataset_version"],
        }
    test = {**deepcopy(cv), "split_kind": "TEST_HOLDOUT", "folds": []}
    if fault == "split_hash":
        manifest["splits"]["split_hash"] = "wrong"
    elif fault == "participant_overlap":
        cv["folds"][0]["train_participants"] += cv["folds"][0]["val_participants"]
    elif fault == "session":
        cv["folds"][0]["train_sessions"] = []
    elif fault == "version":
        cv["dataset_version"] = "ds-v0.0-selftest-wrong"
    elif fault == "kind":
        cv["source_kind"] = "DEV_CAPTURE"
    monkeypatch.setattr(dataset, "read_manifest", lambda path: manifest)
    monkeypatch.setattr(dataset, "read_split", lambda path: test if path.name.startswith("test_") else cv)
    monkeypatch.setattr(dataset, "read_label_set", lambda path: sets[path.parent.name])
    monkeypatch.setattr(dataset, "load_session", lambda raw, labels, **kw: by_name[raw])
    if fault:
        with pytest.raises(ValueError):
            dataset.load_dataset("synthetic-manifest", "synthetic-splits", selftest=True)
    else:
        assert len(dataset.load_dataset("synthetic-manifest", "synthetic-splits", selftest=True)[2]) == 4
