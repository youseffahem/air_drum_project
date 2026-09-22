"""Participant-level dataset splits (Phase 07, Task 07.8; ADR-0021).

README section 13 and Q49 require that **no participant appears in more than one part of a split**:
every session of a participant travels with that participant, the held-out test participants are
frozen once and reused by Phases 09-19, and feature-normalisation statistics are computed per fold
on that fold's *training* participants only. This module builds such a split deterministically,
checks the leakage properties by machine, and refuses to freeze anything it cannot prove.

The split *rule* is a function of the actual participant count ``P`` and is fixed here, before any
participant exists, so that the number of held-out participants cannot be chosen after seeing a
result (ADR-0021 table, rule id ``P07-SPLIT-1``):

| ``P``   | ``n_test`` | ``K``            | Note |
|---|---|---|---|
| 0       | 0 | 0 | nothing can be split; a participant split cannot be frozen |
| 1-3     | 0 | ``P`` (LOPO)     | too few to hold any participant out; leave-one-participant-out only, and every result is reported per participant |
| 4-7     | 1 | ``min(4, P-1)``  | one held-out participant; the test set is acknowledged as statistically weak |
| 8-11    | 2 | 5                | |
| 12-19   | 3 | 5                | |
| >= 20   | ``round(0.2 * P)`` | 5 | |

Determinism: participants are ordered by their pseudonym, optionally grouped into strata
(experience, handedness), and assigned by a seeded permutation. The same roster, strata and seed
always produce the same split, and ``split_hash`` covers exactly those inputs plus the rule id.

Kind gating, as everywhere in this project: a SYNTHETIC or DEV_CAPTURE roster may only produce a
``ds-v0.0-selftest*`` split and can never be frozen. This module therefore cannot be used to
manufacture a participant split out of developer material.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spacedrums import timing
from spacedrums.contracts import schema as contract_schema
from spacedrums.data.labels.schema import dataset_kind, sha256_obj
from spacedrums.data.metadata import SessionKind

SPLIT_SCHEMA_VERSION = "1.0"
SPLIT_RULE_ID = "P07-SPLIT-1"
SPLIT_DIRNAME = "splits"
TEST_FILENAME = "test_participants.json"
FOLDS_FILENAME = "cv_folds.json"

NORMALISATION_RULE = (
    "Feature-normalisation statistics (Phase 08) are computed per fold on the TRAIN participants of "
    "that fold only - never on the validation participants, never on the held-out test "
    "participants, never on the whole dataset."
)

SMALL_P_CAVEAT = (
    "With a small participant count a fixed held-out test set is statistically weak: Phase 18 "
    "reports per-participant results and confidence intervals, and nested cross-validation stays "
    "on the table (phase document, Risks)."
)


def plan_for(P: int) -> tuple[int, int, str]:
    """(n_test, K, note) for ``P`` participants under rule ``P07-SPLIT-1``."""
    if P < 0:
        raise ValueError("participant count must be non-negative")
    if P == 0:
        return 0, 0, "no participant exists: no split can be built or frozen"
    if P <= 3:
        return 0, P, ("too few participants to hold any out; leave-one-participant-out only, "
                      "results reported per participant")
    if P <= 7:
        return 1, min(4, P - 1), "one held-out participant; " + SMALL_P_CAVEAT
    if P <= 11:
        return 2, 5, SMALL_P_CAVEAT
    if P <= 19:
        return 3, 5, SMALL_P_CAVEAT
    return int(round(0.2 * P)), 5, "held-out fraction 20 %"


@dataclass(frozen=True)
class Roster:
    """Who is in the dataset and which sessions belong to each participant.

    ``strata`` optionally maps a participant to a stratum key (e.g. ``"EXPERIENCED|RIGHT"``); when
    the attribute was not collected the participant's stratum is ``"NOT_COLLECTED"`` and the split
    rationale says that stratification was not possible - it is never guessed.
    """

    dataset_version: str
    labels_version: str
    source_kind: SessionKind
    sessions_by_participant: Mapping[str, Sequence[str]]
    strata: Mapping[str, str] | None = None
    stratify_keys: Sequence[str] = ()

    @property
    def participants(self) -> list[str]:
        return sorted(self.sessions_by_participant)

    @property
    def P(self) -> int:
        return len(self.sessions_by_participant)

    def stratum(self, participant: str) -> str:
        return (self.strata or {}).get(participant, "NOT_COLLECTED")


def _permute(items: Sequence[str], seed: int, salt: str) -> list[str]:
    """Deterministic, platform-independent shuffle: sort by SHA-256 of (seed, salt, item).

    ``random.Random`` would also be deterministic, but its stream is an implementation detail of
    CPython; a hash order is reproducible from the recorded inputs alone by anyone.
    """
    return sorted(items, key=lambda x: hashlib.sha256(f"{seed}|{salt}|{x}".encode()).hexdigest())


def _stratified_pick(roster: Roster, n: int, seed: int) -> list[str]:
    """Pick ``n`` test participants, spreading them over the strata as evenly as the counts allow."""
    if n <= 0:
        return []
    buckets: dict[str, list[str]] = {}
    for p in roster.participants:
        buckets.setdefault(roster.stratum(p), []).append(p)
    ordered = {k: _permute(v, seed, f"stratum:{k}") for k, v in sorted(buckets.items())}
    picked: list[str] = []
    while len(picked) < n and any(ordered.values()):
        for key in sorted(ordered, key=lambda k: (-len(ordered[k]), k)):
            if ordered[key] and len(picked) < n:
                picked.append(ordered[key].pop(0))
    return sorted(picked)


def leakage_checks(
    test_participants: Sequence[str],
    folds: Sequence[dict[str, Any]],
    sessions_by_participant: Mapping[str, Sequence[str]],
) -> dict[str, bool]:
    """The machine-checked leakage properties written into every split file."""
    test = set(test_participants)
    all_sessions = {s for ss in sessions_by_participant.values() for s in ss}
    participants_disjoint = True
    sessions_disjoint = True
    no_session_in_two_folds = True
    test_not_in_any_fold = True
    assigned: set[str] = set()
    for fold in folds:
        tr, va = set(fold["train_participants"]), set(fold["val_participants"])
        if tr & va:
            participants_disjoint = False
        if (tr | va) & test:
            test_not_in_any_fold = False
        if set(fold["train_sessions"]) & set(fold["val_sessions"]):
            sessions_disjoint = False
        assigned |= set(fold["train_sessions"]) | set(fold["val_sessions"])
    seen_val: set[str] = set()
    for fold in folds:
        v = set(fold["val_sessions"])
        if v & seen_val:
            no_session_in_two_folds = False
        seen_val |= v
    test_sessions = {s for p in test for s in sessions_by_participant.get(p, ())}
    if test_sessions & assigned:
        sessions_disjoint = False
    every_session_assigned = (assigned | test_sessions) == all_sessions
    checks = {
        "participants_disjoint": participants_disjoint,
        "sessions_disjoint": sessions_disjoint,
        "no_session_in_two_folds": no_session_in_two_folds,
        "test_not_in_any_fold": test_not_in_any_fold,
        "every_session_assigned": every_session_assigned,
    }
    checks["all_passed"] = all(checks.values())
    return checks


def build_split(
    roster: Roster,
    *,
    seed: int = 0,
    freeze: bool = False,
    frozen_at: str | None = None,
    n_test: int | None = None,
    K: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build ``(test_participants.json, cv_folds.json)`` for a roster.

    ``n_test`` / ``K`` override the rule only when the owner records a deviation; by default they
    come from :func:`plan_for` so the numbers are a function of ``P`` and not of a result.
    ``freeze=True`` is refused unless the roster is participant or pilot material, ``P >= 1`` and
    every leakage check passes.
    """
    kind = dataset_kind(roster.dataset_version)
    if roster.source_kind in (SessionKind.SYNTHETIC, SessionKind.DEV_CAPTURE) and kind != "SELFTEST":
        raise ValueError(
            f"{roster.source_kind} roster cannot produce a {kind} split "
            f"({roster.dataset_version}): use a ds-v0.0-selftest* version"
        )
    if roster.source_kind in (SessionKind.PARTICIPANT, SessionKind.PILOT) and kind == "SELFTEST":
        raise ValueError("participant / pilot material never enters a self-test split")

    P = roster.P
    planned_test, planned_k, note = plan_for(P)
    n_test = planned_test if n_test is None else int(n_test)
    K = planned_k if K is None else int(K)
    if n_test > P:
        raise ValueError(f"cannot hold out {n_test} of {P} participants")

    test = _stratified_pick(roster, n_test, seed)
    dev = [p for p in roster.participants if p not in set(test)]
    folds: list[dict[str, Any]] = []
    if dev and K > 0:
        k = min(K, len(dev))
        order = _permute(dev, seed, "folds")
        buckets: list[list[str]] = [[] for _ in range(k)]
        for i, p in enumerate(order):
            buckets[i % k].append(p)
        for i, val in enumerate(buckets):
            train = [p for p in dev if p not in set(val)]
            folds.append(
                {
                    "fold": i,
                    "train_participants": sorted(train),
                    "val_participants": sorted(val),
                    "train_sessions": sorted(
                        s for p in train for s in roster.sessions_by_participant[p]
                    ),
                    "val_sessions": sorted(s for p in val for s in roster.sessions_by_participant[p]),
                }
            )
    checks = leakage_checks(test, folds, roster.sessions_by_participant)
    if freeze and (
        kind == "SELFTEST" or P < 1 or not checks["all_passed"]
    ):
        raise ValueError(
            "refusing to freeze a split: "
            + ("self-test material is never frozen" if kind == "SELFTEST"
               else "no participant exists" if P < 1
               else f"leakage checks failed: {checks}")
        )

    rationale = (
        f"Rule {SPLIT_RULE_ID} with P = {P}: n_test = {n_test}, K = {len(folds)}. {note} "
        + (
            "Stratified by " + ", ".join(roster.stratify_keys) + "."
            if roster.stratify_keys
            else "No stratification was possible: the participant attributes were not collected."
        )
    )
    label = (
        "TEST / DEVELOPMENT ONLY - SYNTHETIC or DEV CAPTURE roster; never a participant split"
        if kind == "SELFTEST"
        else ("FROZEN participant-level split" if freeze else "DRAFT participant-level split (not frozen)")
    )
    base = {
        "schema_version": SPLIT_SCHEMA_VERSION,
        "dataset_version": roster.dataset_version,
        "labels_version": roster.labels_version,
        "source_kind": str(roster.source_kind),
        "frozen": bool(freeze),
        "frozen_at": (frozen_at or timing.wall_clock_iso()) if freeze else None,
        "rule_id": SPLIT_RULE_ID,
        "P": P,
        "n_test": len(test),
        "K": len(folds),
        "seed": int(seed),
        "stratify_keys": list(roster.stratify_keys),
        "participants": roster.participants,
        "test_participants": test,
        "dev_participants": dev,
        "sessions_by_participant": {p: sorted(s) for p, s in
                                    sorted(roster.sessions_by_participant.items())},
        "leakage_checks": checks,
        "normalisation_rule": NORMALISATION_RULE,
        "rationale": rationale,
        "label": label,
    }
    test_doc = {**base, "split_kind": "TEST_HOLDOUT", "folds": []}
    folds_doc = {**base, "split_kind": "CV_FOLDS", "folds": folds}
    h = split_hash(base)
    test_doc["split_hash"] = h
    folds_doc["split_hash"] = h
    for doc in (test_doc, folds_doc):
        errs = validate_split(doc)
        if errs:
            raise ValueError(f"split file invalid: {errs[0]}")
    return test_doc, folds_doc


def split_hash(base: Mapping[str, Any]) -> str:
    """Hash over the split *inputs and outcome*, shared by both files of one split."""
    return sha256_obj(
        {
            "rule_id": base["rule_id"],
            "dataset_version": base["dataset_version"],
            "labels_version": base["labels_version"],
            "seed": base["seed"],
            "participants": list(base["participants"]),
            "test_participants": list(base["test_participants"]),
            "stratify_keys": list(base["stratify_keys"]),
            "sessions_by_participant": {k: list(v) for k, v in base["sessions_by_participant"].items()},
        }
    )


def validate_split(doc: Mapping[str, Any]) -> list[str]:
    errs = contract_schema.errors("split-file", doc)
    if errs:
        return errs
    base = {k: doc[k] for k in ("rule_id", "dataset_version", "labels_version", "seed",
                                "participants", "test_participants", "stratify_keys",
                                "sessions_by_participant")}
    if doc["split_hash"] != split_hash(base):
        errs.append("split_hash does not match the split inputs")
    if not doc["leakage_checks"]["all_passed"] and doc["frozen"]:
        errs.append("a frozen split must pass every leakage check")
    return errs


def write_split(
    test_doc: Mapping[str, Any], folds_doc: Mapping[str, Any], splits_root: str | Path
) -> tuple[Path, Path]:
    """Write both files to ``<splits_root>/<dataset_version>/``.

    A participant split with no participant is refused: ``data/splits/ds-v1.0/`` must not exist
    before the participants do (the labelled-dataset analogue of the Phase 06 empty-manifest
    refusal, integrity I-4).
    """
    if dataset_kind(test_doc["dataset_version"]) != "SELFTEST" and test_doc["P"] < 1:
        raise ValueError(
            f"refusing to write an empty participant split {test_doc['dataset_version']}: "
            "no participant exists (participant data is PENDING until recorded)"
        )
    out = Path(splits_root) / test_doc["dataset_version"]
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for doc, name in ((test_doc, TEST_FILENAME), (folds_doc, FOLDS_FILENAME)):
        errs = validate_split(doc)
        if errs:
            raise ValueError(f"{name} invalid: " + "; ".join(errs[:3]))
        p = out / name
        p.write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
        paths.append(p)
    return paths[0], paths[1]


def read_split(path: str | Path) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    errs = validate_split(doc)
    if errs:
        raise ValueError(f"{path}: " + "; ".join(errs[:3]))
    return doc


def roster_from_label_sets(
    label_sets: Sequence[Mapping[str, Any]], *, dataset_version: str, labels_version: str
) -> Roster:
    """Build a roster from the label sets of a dataset (one entry per session).

    Refuses to mix source kinds: a roster is the participant list of one dataset, and a dataset is
    of one kind (the manifest enforces the same rule).
    """
    kinds = {str(s["source_kind"]) for s in label_sets}
    if len(kinds) > 1:
        raise ValueError(f"refusing to build a roster from mixed source kinds {sorted(kinds)}")
    by_participant: dict[str, list[str]] = {}
    for s in label_sets:
        by_participant.setdefault(str(s["participant_id"]), []).append(str(s["session_id"]))
    return Roster(
        dataset_version=dataset_version,
        labels_version=labels_version,
        source_kind=SessionKind(next(iter(kinds))) if kinds else SessionKind.SYNTHETIC,
        sessions_by_participant={k: sorted(v) for k, v in by_participant.items()},
    )


__all__ = [
    "FOLDS_FILENAME",
    "NORMALISATION_RULE",
    "SMALL_P_CAVEAT",
    "SPLIT_DIRNAME",
    "SPLIT_RULE_ID",
    "SPLIT_SCHEMA_VERSION",
    "TEST_FILENAME",
    "Roster",
    "build_split",
    "leakage_checks",
    "plan_for",
    "read_split",
    "roster_from_label_sets",
    "split_hash",
    "validate_split",
    "write_split",
]
