"""Phase 08 offline composition: verified causal inputs, target-only labels, frozen folds.

This module is deliberately above features in the dependency layers. The feature package
never imports label machinery. Only the two allowlisted label-set files needed here are read.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from spacedrums.config import load_config
from spacedrums.contracts import FrameSample, HandObservation, StickObservation
from spacedrums.contracts import schema as contracts
from spacedrums.data.labels.dataset import read_manifest
from spacedrums.data.labels.generate import read_label_set, read_labels, read_quarantine
from spacedrums.data.labels.review import SamplingPlan, review_queue
from spacedrums.data.labels.schema import sha256_file
from spacedrums.data.metadata import SessionMetadata
from spacedrums.data.splits import leakage_checks, read_split
from spacedrums.features.batch import build_features, load_causal_tracks
from spacedrums.features.normalize import FeatureTable, check_partition, fit_norm
from spacedrums.features.schema import FeatureSchema
from spacedrums.features.streaming import StreamingFeatures
from spacedrums.features.windows import build_windows, segment_for, write_samples
from spacedrums.timing.logger import read_record_stream


@dataclass
class FeatureSession:
    table: FeatureTable
    tracks: list
    labels: list
    segments: list
    schema: FeatureSchema
    parity: dict
    input_hashes: dict


def _observations(path, record_type, cls, meta, hashes):
    if not path.exists():
        return {}
    header, rows = read_record_stream(path)
    contracts.validate("record-stream-header", header)
    if header["record_type"] != record_type or header["session_id"] != meta.session_id:
        raise ValueError("observation stream provenance mismatch")
    if header["config_hash"] != meta.data["config_hash"]:
        raise ValueError("observation configuration mismatch")
    hashes[str(path)] = sha256_file(path)
    result = {}
    for row in rows:
        contracts.validate(
            "hand-observation" if record_type == "HandObservation" else "stick-observation", row
        )
        obj = cls.from_dict(row)
        key = (obj.frame_id, str(obj.hand_id))
        if key in result:
            raise ValueError("duplicate observation")
        result[key] = obj
    return result


def load_session(session_dir, label_dir, *, selftest=False, groups=None):
    session_dir, label_dir = Path(session_dir), Path(label_dir)
    meta = SessionMetadata.read(session_dir)
    label_set = read_label_set(label_dir / "labels.meta.json")
    kind = str(meta.kind)
    if selftest != (kind in ("SYNTHETIC", "DEV_CAPTURE")):
        raise ValueError("selftest flag must match the actual evidence kind")
    if (
        label_set["session_id"] != meta.session_id
        or label_set["participant_id"] != meta.data["participant_id"]
    ):
        raise ValueError("label/session identity mismatch")
    if label_set["source_kind"] != kind:
        raise ValueError("evidence kind mismatch")
    if sha256_file(session_dir / "metadata.json") != label_set["provenance"]["session_metadata_sha256"]:
        raise ValueError("session metadata hash mismatch")
    config = load_config(session_dir / "config.snapshot.yaml")
    if config.config_hash != meta.data["config_hash"]:
        raise ValueError("session configuration hash mismatch")
    schema = FeatureSchema(config["zones"], **({"groups": groups} if groups else {}))
    files = {f["path"]: f for f in label_set["files"]}
    hashes = {
        str(session_dir / "metadata.json"): sha256_file(session_dir / "metadata.json"),
        str(session_dir / "config.snapshot.yaml"): sha256_file(session_dir / "config.snapshot.yaml"),
        str(label_dir / "labels.meta.json"): sha256_file(label_dir / "labels.meta.json"),
    }
    for name in ("tracks_causal.jsonl", "labels.jsonl"):
        if name not in files or sha256_file(label_dir / name) != files[name]["sha256"]:
            raise ValueError("label-set input hash mismatch")
        hashes[str(label_dir / name)] = files[name]["sha256"]
    tracks = load_causal_tracks(label_dir / "tracks_causal.jsonl", session_id=meta.session_id)
    labels = read_labels(label_dir / "labels.jsonl")
    if not selftest:
        rates = label_set["qc"]["sampling"]
        if rates["positives_rate"] != 1 or rates["ambiguous_rate"] != 1 or rates["negatives_rate"] <= 0:
            raise ValueError("participant labels require recorded Phase 07 QC coverage")
        if any(not r["review"]["reviewed"] for r in review_queue(labels, SamplingPlan(**rates))):
            raise ValueError("participant labels require the Phase 07 review gate")
    track_header, _ = read_record_stream(label_dir / "tracks_causal.jsonl")
    if track_header["config_hash"] != meta.data["config_hash"]:
        raise ValueError("track configuration mismatch")
    if any(
        r["session_id"] != meta.session_id
        or r["source_kind"] != kind
        or r["participant_id"] != meta.data["participant_id"]
        for r in labels
    ):
        raise ValueError("target label identity mismatch")
    hands = _observations(
        session_dir / "records/HandObservation.jsonl", "HandObservation", HandObservation, meta, hashes
    )
    sticks = _observations(
        session_dir / "records/StickObservation.jsonl", "StickObservation", StickObservation, meta, hashes
    )
    frame_path = session_dir / "frames.jsonl"
    hashes[str(frame_path)] = sha256_file(frame_path)
    frames = {}
    for line in frame_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        contracts.validate("frame-sample", row)
        f = FrameSample.from_dict(row)
        if f.frame_id in frames:
            raise ValueError("duplicate raw frame")
        frames[f.frame_id] = f
    if any(t.frame_id not in frames or frames[t.frame_id].t_capture != t.t_capture for t in tracks):
        raise ValueError("track does not align with raw frames")
    excluded, session_exclusion = read_quarantine(session_dir)
    verify = session_dir / "verify.json"
    if not verify.exists():
        raise ValueError("verified session required")
    verification = json.loads(verify.read_text(encoding="utf-8"))
    contracts.validate("session-verification", verification)
    if verification["session_id"] != meta.session_id:
        raise ValueError("verification session mismatch")
    if verification["verdict"] == "QUARANTINE":
        session_exclusion = "session verification QUARANTINE"
    hashes[str(verify)] = sha256_file(verify)
    segments = [
        {
            **s,
            "eligible": not session_exclusion
            and (s["segment_id"], s["take"]) not in excluded
            and s["status"] == "RECORDED",
        }
        for s in meta.data["segments"]
    ]
    records = build_features(tracks, schema, hands=hands, sticks=sticks, frames=frames)
    stream = StreamingFeatures(schema)
    online = [
        stream.update(
            t,
            hand=hands.get((t.frame_id, str(t.hand_id))),
            stick=sticks.get((t.frame_id, str(t.hand_id))),
            frame=frames.get(t.frame_id),
        )
        for t in tracks
    ]
    if records != online:
        raise ValueError("batch/streaming parity failure")
    eligible = [bool((s := segment_for(t.t_capture, segments)) and s["eligible"]) for t in tracks]
    table = FeatureTable(meta.data["participant_id"], meta.session_id, kind, records, eligible)
    return FeatureSession(
        table,
        tracks,
        labels,
        segments,
        schema,
        {"records_compared": len(records), "bit_identical": True},
        hashes,
    )


def load_dataset(manifest_path, splits_dir, *, selftest=False, groups=None):
    manifest_path, splits_dir = Path(manifest_path), Path(splits_dir)
    manifest = read_manifest(manifest_path)
    test = read_split(splits_dir / "test_participants.json")
    cv = read_split(splits_dir / "cv_folds.json")
    if not manifest["label_sets"] or not cv["folds"]:
        raise ValueError("dataset and folds must be nonempty")
    if any(d["dataset_version"] != manifest["dataset_version"] for d in (test, cv)):
        raise ValueError("dataset/split version mismatch")
    if test["split_hash"] != cv["split_hash"] or manifest["splits"]["split_hash"] != cv["split_hash"]:
        raise ValueError("manifest/split hash mismatch")
    if test["split_kind"] != "TEST_HOLDOUT" or cv["split_kind"] != "CV_FOLDS":
        raise ValueError("wrong split file kind")
    if selftest:
        if manifest["kind"] != "SELFTEST" or test["frozen"] or cv["frozen"]:
            raise ValueError("selftest cannot claim a frozen participant split")
    elif manifest["kind"] != "PARTICIPANT" or not (test["frozen"] and cv["frozen"]):
        raise ValueError("participant features require frozen participant splits")
    if not leakage_checks(test["test_participants"], cv["folds"], cv["sessions_by_participant"])[
        "all_passed"
    ]:
        raise ValueError("split leakage detected")
    sessions = []
    root = Path(manifest["root"])
    for item in manifest["label_sets"]:
        label_dir = root / item["path"]
        ls = read_label_set(label_dir / "labels.meta.json")
        if ls["set_hash"] != item["set_hash"]:
            raise ValueError("manifest label-set hash mismatch")
        if any(ls[key] != item[key] for key in ("participant_id", "session_id", "source_kind")):
            raise ValueError("manifest label-set identity mismatch")
        if (
            ls["labels_version"] != manifest["labels_version"]
            or ls["dataset_version"] != manifest["dataset_version"]
        ):
            raise ValueError("manifest label-set version mismatch")
        sessions.append(
            load_session(ls["inputs"]["session_dir"], label_dir, selftest=selftest, groups=groups)
        )
    if {s.table.source_kind for s in sessions} != {cv["source_kind"]}:
        raise ValueError("mixed evidence kinds or split source mismatch")
    if len({s.schema.fingerprint for s in sessions}) != 1:
        raise ValueError("mixed feature schemas/layouts")
    for fold in cv["folds"]:
        check_partition(fold, test["test_participants"], [s.table for s in sessions])
    return manifest, cv, sessions


def descriptive_stats(sessions, samples, schema):
    """Caller supplies TRAIN sessions and TRAIN samples only; raw units, no fitted values."""
    fields = [n for n in schema.names if n in ("speed", "dt") or n.startswith(("inward_", "distance_"))]
    distributions = {}
    for name in fields:
        j = schema.index[name]
        values = [
            r.values[j]
            for s in sessions
            for r, ok in zip(s.table.records, s.table.eligible, strict=True)
            if ok and r.mask[j]
        ]
        distributions[name] = {
            "n": len(values),
            "quantiles": dict(
                zip(
                    ("min", "p25", "p50", "p75", "p95", "max"),
                    np.percentile(values, [0, 25, 50, 75, 95, 100]).tolist(),
                    strict=True,
                )
            )
            if values
            else None,
        }
    lookup = {(s.table.session_id, r.frame_id, r.hand_id): r for s in sessions for r in s.table.records}
    correlations = {}
    for name in (n for n in schema.names if n.startswith("tts_")):
        j, pairs = schema.index[name], []
        for sample in samples:
            a, meta = sample["aux"], sample["meta"]
            if not sample["anticipation_eligible"] or not a["tti_mask"] or a["zone_id"] != name[4:]:
                continue
            r = lookup[(meta["session_id"], meta["frame_id"], meta["hand_id"])]
            if r.mask[j]:
                pairs.append((r.values[j], a["tti"]))
        values = np.asarray(pairs)
        defined = len(pairs) >= 3 and np.all(np.std(values, axis=0) > schema.epsilon)
        correlations[name] = {
            "n": len(pairs),
            "pearson_r": float(np.corrcoef(values.T)[0, 1]) if defined else None,
            "reason": None if defined else "insufficient pairs or zero variance",
        }
    return {"distributions": distributions, "tts_vs_gt_tti": correlations}


def export_folds(manifest, cv, sessions, output, params, *, stats_only=False):
    schema = sessions[0].schema
    reports = []
    for fold in cv["folds"]:
        tables = [s.table for s in sessions]
        stats = fit_norm(
            tables,
            schema,
            fold,
            cv["test_participants"],
            dataset_version=manifest["dataset_version"],
            dataset_hash=manifest["manifest_hash"],
            split_hash=cv["split_hash"],
        )
        out = Path(output) / f"fold-{fold['fold']}"
        out.mkdir(parents=True, exist_ok=True)
        stats.write(out / "norm_stats.json")
        report = {"fold": fold["fold"], "source_kind": cv["source_kind"], "parts": {}}
        for part, participants in (
            ("train", fold["train_participants"]),
            ("val", fold["val_participants"]),
            ("test", cv["test_participants"]),
        ):
            selected = [s for s in sessions if s.table.participant in participants]
            samples, counts = [], []
            for session in selected:
                ss, count = build_windows(
                    session.tracks,
                    session.table.records,
                    session.labels,
                    session.segments,
                    schema,
                    params,
                    participant=session.table.participant,
                    session_id=session.table.session_id,
                    source_kind=session.table.source_kind,
                    fold=fold["fold"],
                    stats=stats,
                )
                if any(s["meta"]["participant"] not in participants for s in ss):
                    raise ValueError("sample-level participant leakage")
                samples.extend(ss)
                counts.append({"session_id": session.table.session_id, **count})
            report["parts"][part] = {
                "participants": participants,
                "sessions": counts,
                "label_class_counts": dict(Counter(r["label_class"] for s in selected for r in s.labels)),
            }
            if not stats_only:
                write_samples(
                    out / f"samples.{part}.npz",
                    [s for s in samples if s["anticipation_eligible"]],
                    schema,
                    params,
                )
                write_samples(
                    out / f"safety.{part}.npz",
                    [s for s in samples if not s["anticipation_eligible"]],
                    schema,
                    params,
                )
            if part == "train":
                report["train_descriptive_stats"] = descriptive_stats(selected, samples, schema)
        (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        reports.append(report)
    return reports
