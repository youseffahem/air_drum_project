"""Labelled-dataset manifest and dataset card (Phase 07, Task 07.10).

A ``ds-v*`` manifest is the labelled counterpart of Phase 06's ``ds-raw-v*`` manifest and follows
the same three rules, because they are what keep the dataset honest:

1. **Kind gating.** A participant dataset admits PARTICIPANT label sets only, a pilot dataset PILOT
   label sets, a self-test dataset SYNTHETIC / DEV CAPTURE label sets. A label set of the wrong
   kind is listed under ``refused`` with its reason - never re-labelled, never silently dropped.
2. **One machinery per dataset.** Every listed label set must carry the same ``labels_hash``; a set
   produced by different rules, thresholds, smoother or tracker is refused. This is the
   machine-checked half of the versioning rule: *any change to rules / tracker / smoother produces
   a new ``labels_version``; any change to the accepted sessions produces a new ``ds`` minor
   version.*
3. **No empty participant dataset.** ``write_manifest`` refuses to write ``ds-v1.0.json`` when no
   participant label set exists, exactly as Phase 06 refuses an empty ``ds-raw-v1.0``.

The dataset card is generated from the manifest, the label statistics and the split file, so every
count in it comes from an artefact rather than from prose. Fields that need participants - the
participant table, the label counts, the agreement - are rendered as explicit PENDING rows when
there is nothing to report, never as zeros presented as findings.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from spacedrums import timing
from spacedrums.contracts import schema as contract_schema
from spacedrums.data.labels.generate import read_label_set, read_labels
from spacedrums.data.labels.schema import (
    DATASET_LABELS,
    LABELS_FILENAME,
    LABEL_SET_FILENAME,
    LabelClass,
    admissible_source,
    dataset_kind,
    sha256_obj,
)
from spacedrums.data.labels.stats import aggregate, markdown_table

MANIFEST_SCHEMA_VERSION = "1.0"
GENERATOR = {"tool": "spacedrums.data.labels.dataset", "version": "0.7.0"}


def manifest_hash(doc: dict[str, Any]) -> str:
    return sha256_obj({k: v for k, v in doc.items() if k not in ("manifest_hash", "generated_at")})


def validate_manifest(doc: dict[str, Any]) -> list[str]:
    errs = contract_schema.errors("dataset-manifest", doc)
    if not errs and doc.get("manifest_hash") != manifest_hash(doc):
        errs.append("manifest_hash does not match the document")
    return errs


def build_manifest(
    labels_root: str | Path,
    dataset_version: str,
    *,
    raw_manifest: dict[str, Any] | None = None,
    raw_manifest_path: str | None = None,
    label_dirs: Sequence[str | Path] | None = None,
    splits: dict[str, Any] | None = None,
    dataset_card: str | None = None,
    git_sha: str = "0" * 40,
    git_dirty: bool | None = None,
    generated_at: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Build the ``ds-<version>`` manifest from the label sets under ``labels_root``."""
    root = Path(labels_root)
    kind = dataset_kind(dataset_version)
    dirs = (
        [Path(p) for p in label_dirs]
        if label_dirs is not None
        else sorted(p for p in root.glob("*") if p.is_dir() and (p / LABEL_SET_FILENAME).exists())
    )
    sets: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    machinery: dict[str, Any] | None = None
    labels_version = ""
    total_by_class: dict[str, int] = {}
    total_by_kind: dict[str, int] = {}
    n_labels = 0
    for d in dirs:
        meta_path = d / LABEL_SET_FILENAME
        if not meta_path.exists():
            refused.append({"path": d.as_posix(), "session_id": d.name, "reason": "no labels.meta.json"})
            continue
        try:
            doc = read_label_set(meta_path)
        except ValueError as exc:
            refused.append({"path": d.as_posix(), "session_id": d.name,
                            "reason": f"label set invalid: {exc}"})
            continue
        why = admissible_source(dataset_version, doc["source_kind"])
        if why:
            refused.append({"path": d.as_posix(), "session_id": doc["session_id"], "reason": why})
            continue
        if machinery is None:
            machinery = doc["provenance"]
            labels_version = doc["labels_version"]
        elif doc["provenance"]["labels_hash"] != machinery["labels_hash"]:
            refused.append(
                {
                    "path": d.as_posix(),
                    "session_id": doc["session_id"],
                    "reason": "labels_hash differs from the dataset's machinery: a change to rules, "
                    "thresholds, smoother or tracker needs a new labels_version",
                }
            )
            continue
        recs = read_labels(d / LABELS_FILENAME)
        by_class: dict[str, int] = {}
        for r in recs:
            by_class[r["label_class"]] = by_class.get(r["label_class"], 0) + 1
            total_by_class[r["label_class"]] = total_by_class.get(r["label_class"], 0) + 1
            total_by_kind[r["source_kind"]] = total_by_kind.get(r["source_kind"], 0) + 1
        n_labels += len(recs)
        sets.append(
            {
                "session_id": doc["session_id"],
                "participant_id": doc["participant_id"],
                "source_kind": doc["source_kind"],
                "path": d.relative_to(root).as_posix() if d.is_relative_to(root) else d.as_posix(),
                "set_hash": doc["set_hash"],
                "n_labels": len(recs),
                "by_class": dict(sorted(by_class.items())),
                "qc_pending": doc["qc"]["pending"],
                "files": doc["files"],
            }
        )
    sets.sort(key=lambda s: (s["participant_id"], s["session_id"]))
    participants = sorted({s["participant_id"] for s in sets})
    doc = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset_version": dataset_version,
        "kind": kind,
        "label": DATASET_LABELS[kind],
        "labels_version": labels_version or "labels-v1.0",
        "raw_manifest": {
            "dataset_version": (raw_manifest or {}).get("dataset_version", "PENDING"),
            "manifest_hash": (raw_manifest or {}).get("manifest_hash", "sha256:" + "0" * 64),
            "path": raw_manifest_path or "PENDING - no raw manifest exists yet",
        },
        "root": root.as_posix(),
        "generated_at": generated_at or timing.wall_clock_iso(),
        "generator": {**GENERATOR, "git_sha": git_sha, "git_dirty": git_dirty},
        "machinery": machinery or _placeholder_machinery(),
        "splits": splits or {"test_participants": None, "cv_folds": None, "split_hash": None,
                             "frozen": False},
        "dataset_card": dataset_card,
        "totals": {
            "n_label_sets": len(sets),
            "n_participants": len(participants),
            "n_sessions": len({s["session_id"] for s in sets}),
            "n_labels": n_labels,
            "by_class": dict(sorted(total_by_class.items())),
            "by_source_kind": dict(sorted(total_by_kind.items())),
            "n_files": sum(len(s["files"]) for s in sets),
            "total_bytes": sum(f["bytes"] for s in sets for f in s["files"]),
            "label": _totals_label(total_by_kind),
        },
        "participants": participants,
        "label_sets": sets,
        "refused": refused,
        "exclusions": list((raw_manifest or {}).get("exclusions", [])),
        "withdrawals": list((raw_manifest or {}).get("withdrawals", [])),
        "notes": notes,
        "manifest_hash": "sha256:" + "0" * 64,
    }
    doc["manifest_hash"] = manifest_hash(doc)
    return doc


def _totals_label(by_kind: dict[str, int]) -> str:
    """Evidence banner for the totals.

    A participant or pilot dataset holds exactly one source kind, so its total is a single claim. A
    self-test dataset may hold SYNTHETIC *and* DEV CAPTURE material; its ``n_labels`` is then a file
    inventory across both, and the banner says so rather than letting one number read as one
    evidence class (integrity I-4). ``totals.by_source_kind`` carries the split.
    """
    if not by_kind:
        return "none (no label set listed)"
    if len(by_kind) > 1:
        breakdown = ", ".join(f"{k} {n}" for k, n in sorted(by_kind.items()))
        return (f"INVENTORY across {len(by_kind)} source kinds ({breakdown}) - a file count, NOT one "
                "evidence class; see totals.by_source_kind and report the kinds separately")
    only = next(iter(by_kind))
    return f"MEASURED from the listed label sets; evidence class: {only}"


def _placeholder_machinery() -> dict[str, Any]:
    """Machinery block of an empty manifest: explicit placeholders, never invented values."""
    from spacedrums.data.labels.rules import Thresholds, rules_hash
    from spacedrums.data.labels.schema import GEOMETRY_VERSION, RULES_VERSION, Interpolation
    from spacedrums.data.labels.smooth import ReferenceSmoother

    sm = ReferenceSmoother()
    th = Thresholds()
    prov = {
        "rules_version": RULES_VERSION,
        "rules_hash": rules_hash(),
        "thresholds_hash": th.thresholds_hash,
        "smoother_id": sm.smoother_id,
        "smoother_hash": sm.smoother_hash,
        "tracker_id": "PENDING - no session labelled",
        "tracker_hash": "sha256:" + "0" * 64,
        "geometry_version": GEOMETRY_VERSION,
        "zone_layout_id": "PENDING",
        "v_min": 0.0,
        "interpolation": str(Interpolation.LINEAR),
    }
    return {
        **prov,
        "config_hash": "sha256:" + "0" * 64,
        "git_sha": "0" * 40,
        "generator": dict(GENERATOR),
        "reference_track_ref": "tracks_reference.jsonl",
        "causal_track_ref": "tracks_causal.jsonl",
        "session_metadata_sha256": "sha256:" + "0" * 64,
        "labels_hash": sha256_obj(prov),
    }


def write_manifest(
    doc: dict[str, Any], manifests_dir: str | Path, *, allow_empty: bool = False
) -> Path:
    """Write ``<dataset_version>.json``; refuses an empty participant or pilot dataset."""
    errs = validate_manifest(doc)
    if errs:
        raise ValueError("dataset manifest invalid: " + "; ".join(errs[:3]))
    if doc["kind"] in ("PARTICIPANT", "PILOT") and not doc["label_sets"] and not allow_empty:
        raise ValueError(
            f"refusing to write an empty {doc['kind']} dataset manifest {doc['dataset_version']}: "
            "no label set of that kind exists (participant data is PENDING until recorded and labelled)"
        )
    mdir = Path(manifests_dir)
    mdir.mkdir(parents=True, exist_ok=True)
    path = mdir / f"{doc['dataset_version']}.json"
    path.write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    return path


def read_manifest(path: str | Path) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    errs = validate_manifest(doc)
    if errs:
        raise ValueError(f"{path}: " + "; ".join(errs[:3]))
    return doc


def check_manifest_files(doc: dict[str, Any], labels_root: str | Path) -> list[str]:
    """Re-hash every listed file; empty result means the files match the manifest."""
    from spacedrums.data.labels.schema import sha256_file

    root = Path(labels_root)
    problems = []
    for s in doc["label_sets"]:
        base = root / s["path"]
        for f in s["files"]:
            p = base / f["path"]
            if not p.exists():
                problems.append(f"{s['session_id']}/{f['path']}: missing")
            elif p.stat().st_size != f["bytes"] or sha256_file(p) != f["sha256"]:
                problems.append(f"{s['session_id']}/{f['path']}: hash/size mismatch")
    return problems


# ----------------------------------------------------------------------------- dataset card

CARD_LIMITATIONS = [
    "Ground truth is **geometric**: `t_impact_est` is the crossing of a virtual impact surface by "
    "the estimated stick tip, not a physical impact. Where the pad + microphone condition exists, "
    "`t_impact_phys` gives the measured offset for those strikes only (ADR-0002).",
    "Single camera, no depth: the tip position is 2-D in ROI-normalized coordinates (ADR-0005); "
    "motion towards or away from the camera is not observed.",
    "Labels are **non-causal** by construction: they come from a trajectory smoothed over the whole "
    "recording. They are valid as evaluation references and as training targets, and must never be "
    "used as model inputs (docs/architecture/causality-tests.md section 1.1).",
    "Negative classes are threshold-based (`rules.Thresholds`); the thresholds are candidates until "
    "a review pass on real recordings refines them.",
    "The reference smoother may round off sharp reversals at impact; the error near impacts is "
    "quantified against manual tip annotations, which needs recordings.",
    "Zones, not articulations: rim / centre / edge are out of scope (REQ-015).",
]


def dataset_card(
    manifest: dict[str, Any],
    *,
    labels: Sequence[dict[str, Any]] = (),
    split: dict[str, Any] | None = None,
    agreement: dict[str, Any] | None = None,
    phys: dict[str, Any] | None = None,
    consent_scope: str = "PENDING - no consent record exists (Phase 06 C-06-4)",
    change_log: Sequence[str] = (),
) -> str:
    """Render the dataset card (Task 07.10). Missing evidence is printed as PENDING, never as 0."""
    kind = manifest["kind"]
    totals = manifest["totals"]
    lines: list[str] = []
    lines.append(f"# Dataset card — `{manifest['dataset_version']}`")
    lines.append("")
    lines.append(f"**Kind:** {kind} · **Label:** {manifest['label']}")
    lines.append("")
    if not totals["n_label_sets"]:
        lines.append(
            f"> ## THIS DATASET DOES NOT EXIST YET\n"
            f">\n"
            f"> `{manifest['dataset_version']}` contains **no label set**. No manifest has been "
            f"written for it and none can be: the builder refuses an empty participant or pilot "
            f"dataset. This card is the **template** the campaign will fill — every section below "
            f"that would carry a count says PENDING, and no number in it describes anything that "
            f"has been observed."
        )
        lines.append("")
    lines.append(f"**Labels version:** `{manifest['labels_version']}` · "
                 f"**Raw source:** `{manifest['raw_manifest']['dataset_version']}` · "
                 f"**Manifest hash:** "
                 + (f"`{manifest['manifest_hash']}` (of this empty document; no manifest file exists)"
                    if not totals["n_label_sets"] else f"`{manifest['manifest_hash']}`"))
    lines.append("")
    lines.append("## 1. Purpose and intended use")
    lines.append("")
    lines.append(
        "Training and evaluation data for causal temporal strike anticipation from a webcam "
        "(Space Drums, README section 1). Intended use: the Phase 08-19 feature, model and "
        "evaluation work of this project. **Not** intended as a general drumming or gesture "
        "benchmark, and not released (Phase 23 decides release; consent scope below)."
    )
    lines.append("")
    lines.append("## 2. Collection protocol")
    lines.append("")
    lines.append(
        "Recorded under the Phase 06 protocol (`docs/protocols/recording-protocol.md`): cued "
        "segments covering single hits, alternating and near-simultaneous strokes, tempo and rapid "
        "blocks, movement between zones, fake swings, stops before impact, occlusion, tracking "
        "interruption, and distance / lighting variation. Every session carries a "
        "`SessionMetadata` document with the camera, audio, config and git provenance, and a "
        "`verify.json` with the applied unusable-recording policy."
    )
    lines.append("")
    lines.append("## 3. Participants (aggregate, pseudonymised)")
    lines.append("")
    if totals["n_participants"] and kind in ("PARTICIPANT", "PILOT"):
        lines.append(f"| Participants | Sessions | Label sets |")
        lines.append("|---:|---:|---:|")
        lines.append(f"| {totals['n_participants']} | {totals['n_sessions']} | "
                     f"{totals['n_label_sets']} |")
        lines.append("")
        lines.append("Individual attributes (handedness, experience) are reported only in "
                     "aggregate and only where collected.")
    else:
        lines.append("**PENDING — no participant sessions exist.** No participant has been "
                     "recorded (Phase 06 conditions C-06-1…C-06-4), so this dataset version "
                     "contains no participant material and no participant count is reported.")
    lines.append("")
    lines.append("## 4. Label definitions")
    lines.append("")
    lines.append(
        "See `docs/dataset/labeling-rules-v1.0.md` for the normative rules. In short: a POSITIVE "
        "label is the first outside-to-inside crossing of a zone's impact surface by the "
        "**reference** (offline-smoothed) tip trajectory with inward speed above `v_min`, timed by "
        "sub-frame interpolation; `intensity_proxy_gt` is the inward-normal velocity component at "
        "that instant (a proxy, never a force). Negatives cover no-strike motion, fake swings, "
        "stops before impact, movement between zones, upward/exit crossings and tracking loss. "
        "AMBIGUOUS labels stay in the dataset and are excluded from every metric numerator and "
        "denominator; EXCLUDED labels lie in quarantined segments."
    )
    lines.append("")
    lines.append("## 5. Label counts")
    lines.append("")
    if labels:
        lines.append(markdown_table(aggregate(labels)))
    elif totals["by_class"]:
        lines.append("| Class | Count |")
        lines.append("|---|---:|")
        for cls, n in totals["by_class"].items():
            lines.append(f"| `{cls}` | {n} |")
        lines.append("")
        lines.append(f"_{totals['label']}_")
    else:
        lines.append("**PENDING — no labels in this dataset version.**")
    lines.append("")
    lines.append("## 6. Splits")
    lines.append("")
    if split:
        lines.append(f"Rule `{split['rule_id']}` · P = {split['P']} · n_test = {split['n_test']} · "
                     f"K = {split['K']} · seed {split['seed']} · frozen: **{split['frozen']}**")
        lines.append("")
        lines.append(f"> {split['rationale']}")
        lines.append("")
        lines.append(f"Leakage checks: `{split['leakage_checks']}`")
        lines.append("")
        lines.append(f"**Normalisation rule for Phase 08:** {split['normalisation_rule']}")
    else:
        lines.append("**PENDING — no split is frozen for this dataset version.** "
                     "The split rule (ADR-0021, `P07-SPLIT-1`) is fixed as a function of the "
                     "participant count `P` so the numbers cannot be chosen after seeing a result.")
    lines.append("")
    lines.append("## 7. Quality control and agreement")
    lines.append("")
    if agreement and agreement.get("n_pairs"):
        lines.append(f"Agreement kind: {agreement['kind']} · evidence: {agreement['evidence_label']} · "
                     f"pairs: {agreement['n_pairs']}")
        kappa = agreement.get("kappa")
        lines.append(f"Cohen's kappa (event presence): "
                     f"{'undefined (single category)' if kappa is None else f'{kappa:.3f}'}")
        lines.append(f"|Δt| over jointly accepted events: median "
                     f"{agreement.get('median_abs_dt_s')}, p95 {agreement.get('p95_abs_dt_s')}, "
                     f"max {agreement.get('max_abs_dt_s')} s")
    else:
        lines.append("**PENDING / NOT VALIDATED — no annotation pass has been performed.** "
                     "The QC protocol (`P07-QC-1`) and the review tool exist and are tested; no "
                     "human annotator has reviewed any label, and no inter-annotator agreement is "
                     "claimed.")
    lines.append("")
    lines.append("## 8. Physical ground truth (pad + microphone)")
    lines.append("")
    if phys and phys.get("available"):
        lines.append(f"Paired strikes: {phys['n_paired']} of {phys['n_pad_positives']} pad "
                     f"positives · bias {phys.get('bias_s')} s · IQR {phys.get('iqr_s')} s · "
                     f"microphone-path bound {phys.get('mic_latency_bound_s')} s")
        lines.append("")
        lines.append("The residual is a **measured offset between two differently defined "
                     "instants**, not a claim that the geometric crossing is the physical impact.")
    else:
        reason = (phys or {}).get("reason") or "no pad + microphone condition was recorded"
        lines.append(f"**PENDING — {reason}.** Ground truth in this dataset version is "
                     f"**geometric only** (ADR-0002 fallback).")
    lines.append("")
    lines.append("## 9. Known limitations")
    lines.append("")
    for item in CARD_LIMITATIONS:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 10. Licence, consent scope and reuse")
    lines.append("")
    lines.append(f"- **Consent scope:** {consent_scope}")
    lines.append("- **Licence:** proprietary graduation-project material; no release is made by "
                 "Phase 07 (`What Must NOT Be Done Yet`). A release decision belongs to Phase 23 "
                 "and is bounded by what each participant consented to.")
    lines.append("- **Reuse conditions (Q49):** reuse requires the consent scope to permit it, the "
                 "labelling rules document and this card to travel with the data, and any derived "
                 "result to state the labels version and the split file it used.")
    lines.append("")
    lines.append("## 11. Versioning and change log")
    lines.append("")
    lines.append("Versioning rule: **any** change to the rules, thresholds, tracker or smoother "
                 "produces a new `labels_version`; **any** change to the accepted sessions "
                 "produces a new `ds` minor version. The `labels_hash` in every label record makes "
                 "a stale version detectable rather than merely discouraged.")
    lines.append("")
    for entry in change_log or [f"{manifest['dataset_version']} — initial manifest "
                                f"({manifest['generated_at'][:10]})."]:
        lines.append(f"- {entry}")
    lines.append("")
    return "\n".join(lines)


def phys_summary(label_sets: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the per-session ``phys`` blocks; ``available`` only if some session had audio."""
    available = [s["phys"] for s in label_sets if s["phys"]["available"]]
    if not available:
        reasons = sorted({s["phys"]["reason"] for s in label_sets if s["phys"]["reason"]})
        return {
            "available": False,
            "reason": reasons[0] if reasons else "no session carries a microphone track",
            "n_pad_positives": sum(s["phys"]["n_pad_positives"] for s in label_sets),
            "n_paired": 0,
            "label": "PENDING - no acoustic ground truth",
        }
    return {
        "available": True,
        "reason": None,
        "n_pad_positives": sum(p["n_pad_positives"] for p in available),
        "n_paired": sum(p["n_paired"] for p in available),
        "label": "MEASURED from the paired acoustic onsets",
    }


def n_positive(labels: Sequence[dict[str, Any]]) -> int:
    return sum(1 for r in labels if r["label_class"] == str(LabelClass.POSITIVE))


__all__ = [
    "CARD_LIMITATIONS",
    "MANIFEST_SCHEMA_VERSION",
    "build_manifest",
    "check_manifest_files",
    "dataset_card",
    "manifest_hash",
    "n_positive",
    "phys_summary",
    "read_manifest",
    "validate_manifest",
    "write_manifest",
]
