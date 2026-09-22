"""Fold-bound, train-only normalization with explicit evidence provenance."""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class FeatureTable:
    participant: str
    session_id: str
    source_kind: str
    records: list
    eligible: list[bool]


def check_partition(fold, test_participants, tables):
    tr, va, te = (set(fold["train_participants"]), set(fold["val_participants"]), set(test_participants))
    if tr & va or tr & te or va & te:
        raise ValueError("participant leakage")
    if not tr or not va:
        raise ValueError("a fold needs nonempty training and validation participants")
    ids = [t.session_id for t in tables]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate session")
    if {t.participant for t in tables} != tr | va | te:
        raise ValueError("missing or unassigned participant")
    for part, participants in (("train", tr), ("val", va)):
        actual = {t.session_id for t in tables if t.participant in participants}
        if actual != set(fold[f"{part}_sessions"]):
            raise ValueError("session assignment mismatch")


@dataclass
class NormStats:
    data: dict

    def apply(self, values, mask, schema):
        d = self.data
        if (
            d["feature_schema_id"] != schema.feature_schema_id
            or d["feature_schema_hash"] != schema.fingerprint
        ):
            raise ValueError("normalization schema/layout mismatch")
        x, m = np.asarray(values, dtype=float), np.asarray(mask, dtype=bool).copy()
        if x.shape != m.shape or x.shape[-1] != schema.dimension or not np.isfinite(x).all():
            raise ValueError("invalid feature tensor")
        center, scale = np.asarray(d["center"]), np.asarray(d["scale"])
        if center.shape != (schema.dimension,) or scale.shape != center.shape or np.any(scale <= 0):
            raise ValueError("invalid normalization statistics")
        if not np.isfinite(center).all() or not np.isfinite(scale).all():
            raise ValueError("non-finite normalization statistics")
        m &= np.asarray(d["usable"], dtype=bool)
        return np.where(m, (x - center) / scale, 0.0), m

    def write(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.data, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path, *, fold, dataset_version, split_hash, dataset_hash, schema):
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        expected = {
            "fold": fold,
            "dataset_version": dataset_version,
            "split_hash": split_hash,
            "dataset_hash": dataset_hash,
            "feature_schema_hash": schema.fingerprint,
        }
        if any(d.get(k) != v for k, v in expected.items()):
            raise ValueError("normalization provenance mismatch")
        result = cls(d)
        result.apply(np.zeros((1, schema.dimension)), np.ones((1, schema.dimension), bool), schema)
        return result


def fit_norm(tables, schema, fold, test_participants, *, dataset_version, dataset_hash, split_hash):
    check_partition(fold, test_participants, tables)
    kinds = {t.source_kind for t in tables}
    if len(kinds) != 1:
        raise ValueError("mixed evidence kinds")
    kind = next(iter(kinds))
    if kind in ("SYNTHETIC", "DEV_CAPTURE") and not dataset_version.startswith("ds-v0.0-selftest"):
        raise ValueError("non-participant statistics require a self-test dataset version")
    if kind not in ("SYNTHETIC", "DEV_CAPTURE", "PARTICIPANT", "PILOT"):
        raise ValueError("unknown evidence kind")
    train = [t for t in tables if t.participant in set(fold["train_participants"])]
    rows = []
    for t in train:
        if len(t.records) != len(t.eligible):
            raise ValueError("eligibility length mismatch")
        rows.extend(r for r, ok in zip(t.records, t.eligible, strict=True) if ok)
    if not rows:
        raise ValueError("no eligible training frames")
    if any(
        r.feature_schema_id != schema.feature_schema_id or len(r.values) != schema.dimension for r in rows
    ):
        raise ValueError("feature schema mismatch")
    x, m = np.asarray([r.values for r in rows]), np.asarray([r.mask for r in rows])
    center, scale, counts, usable = [], [], [], []
    for j, field in enumerate(schema.fields):
        v = x[m[:, j], j]
        method = field["normalization"]
        counts.append(len(v))
        usable.append(bool(len(v)) or method == "identity")
        if method == "identity" or not len(v):
            a, b = 0.0, 1.0
        elif method == "robust":
            a, b = float(np.median(v)), float(np.percentile(v, 75) - np.percentile(v, 25))
        else:
            a, b = float(np.mean(v)), float(np.std(v))
        center.append(a)
        scale.append(b if b > schema.epsilon else 1.0)
    return NormStats(
        {
            "schema_version": "1.0",
            "feature_schema_id": schema.feature_schema_id,
            "feature_schema_hash": schema.fingerprint,
            "dataset_version": dataset_version,
            "dataset_hash": dataset_hash,
            "split_hash": split_hash,
            "fold": fold["fold"],
            "source_kind": kind,
            "train_participants": sorted(fold["train_participants"]),
            "train_sessions": sorted(t.session_id for t in train),
            "methods": [f["normalization"] for f in schema.fields],
            "names": list(schema.names),
            "center": center,
            "scale": scale,
            "counts": counts,
            "usable": usable,
        }
    )
