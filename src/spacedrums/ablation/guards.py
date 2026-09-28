"""Fail-closed reference checks and a file allowlist. No approvals or locks are written here."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import ValidationError

from spacedrums.contracts.schema import errors as schema_errors
from spacedrums.live_eval.prereg import file_digest, lock_digest, verify_document, verify_lock

REQUIRED = (
    "dataset_manifest",
    "reviewed_labels",
    "cv_folds",
    "test_roster",
    "model_manifest",
    "model_export",
    "normalization",
    "configuration",
    "offline_lock",
    "processing_delay",
    "operating_rule",
    "phase18_prereg",
    "phase18_prereg_record",
    "phase18_gate",
    "phase18_gate_decision",
    "reference_results",
    "phase19_prereg",
    "phase19_prereg_record",
)
PREPARATION_ONLY = "Phase 19 experimental execution is disabled: PREPARATION ONLY; Phase 18 PENDING"


class DependencyError(ValueError):
    pass


class FrozenFiles:
    """Only declared relative files under one resolved reference root may be read.

    Re-hash on each access (including before a downstream loader), reject traversal, absolute
    paths and escaping symlinks. Participant/test content is never accepted via CLI overrides.
    """

    def __init__(self, root, files):
        self.root, self.files = Path(root).resolve(), dict(files)

    def path(self, relative):
        rel = Path(relative)
        if rel.is_absolute() or rel.drive or ".." in rel.parts or not relative:
            raise DependencyError("reference path must be relative and contained")
        if relative not in self.files:
            raise DependencyError(f"undeclared frozen input: {relative}")
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise DependencyError(f"missing or escaping frozen input: {relative}")
        if file_digest(path) != self.files[relative]:
            raise DependencyError(f"frozen input hash mismatch: {relative}")
        return path

    def json(self, relative):
        return json.loads(self.path(relative).read_text(encoding="utf-8"))

    def check_tree(self, relative):
        """A loader's whole session tree must be frozen, including every derived stream."""
        rel = Path(relative)
        directory = (self.root / rel).resolve()
        if rel.is_absolute() or rel.drive or ".." in rel.parts or not directory.is_relative_to(self.root):
            raise DependencyError("session directory escapes reference")
        if not directory.is_dir():
            raise DependencyError("missing frozen session directory")
        for path in directory.rglob("*"):
            if path.is_file():
                self.path(path.relative_to(self.root).as_posix())
        return directory

    def session(self, declaration):
        """Check identity before opening streams; use the existing Phase 07/08 review gates."""
        from spacedrums.data.feature_dataset import load_session

        metadata = (Path(declaration["directory"]) / "metadata.json").as_posix()
        meta = self.json(metadata)
        if (
            meta.get("session_kind") != "PARTICIPANT"
            or meta.get("participant_id") != declaration["participant_id"]
            or meta.get("session_id") != declaration["session_id"]
        ):
            raise DependencyError("CV session kind/identity mismatch; streams were not opened")
        loaded = load_session(
            self.check_tree(declaration["directory"]),
            self.check_tree(declaration["label_directory"]),
            selftest=False,
        )
        if (loaded.table.participant, loaded.table.session_id) != (
            declaration["participant_id"],
            declaration["session_id"],
        ):
            raise DependencyError("loaded session differs from declared frozen identity")
        return loaded


def session_scope(cv, declarations, *, fold, partition):
    """Select only explicitly frozen CV sessions; test access is categorically refused here."""
    if partition not in ("train", "val"):
        raise DependencyError("Phase 19 preparation uses CV only; test participant access refused")
    folds = [f for f in cv["folds"] if f["fold"] == fold]
    if len(folds) != 1:
        raise DependencyError("fold absent or duplicated in frozen CV reference")
    cell = folds[0]
    train, val, test = map(
        set, (cell["train_participants"], cell["val_participants"], cv["test_participants"])
    )
    if train & val or (train | val) & test or not train or not val:
        raise DependencyError("participant split leakage")
    roster = train if partition == "train" else val
    selected = [s for s in declarations if s["participant_id"] in roster]
    actual = [s["session_id"] for s in selected]
    if len(actual) != len(set(actual)) or set(actual) != set(cell[f"{partition}_sessions"]):
        raise DependencyError("sessions outside or missing from frozen fold")
    if any(s["participant_id"] in test for s in selected):
        raise DependencyError("test participant leakage")
    mapping = cv.get("sessions_by_participant", {})
    if any(s["session_id"] not in mapping.get(s["participant_id"], []) for s in selected):
        raise DependencyError("frozen participant/session identity mismatch")
    return sorted(selected, key=lambda s: (s["participant_id"], s["session_id"]))


def dependency_errors(reference, root):
    """Read-only preflight of a real, owner-supplied reference. Absence never means a default."""
    if not isinstance(reference, dict):
        return ["missing frozen Phase 18 reference", *[f"missing {k}" for k in REQUIRED]]
    errors = []
    if reference.get("evidence") != "PARTICIPANT" or reference.get("dataset_version") != "ds-v1.0":
        errors.append("requires real PARTICIPANT ds-v1.0; SYNTHETIC/DEV is not a frozen reference")
    artifacts = reference.get("artifacts", {})
    files = FrozenFiles(root, reference.get("files", {}))
    for role in REQUIRED:
        if role not in artifacts:
            errors.append(f"missing {role}")
        else:
            try:
                files.path(artifacts[role])
            except (OSError, ValueError, TypeError) as exc:
                errors.append(f"{role}: {exc}")
    if errors:
        return errors
    errors.extend(schema_errors("ablation-reference", reference))
    if errors:
        return errors
    try:

        def read(role):
            return files.json(artifacts[role])

        lock = read("offline_lock")
        if lock.get("evidence") != "PARTICIPANT" or lock.get("lock_kind") != "offline":
            errors.append("requires participant offline lock")
        for phase in (18, 19):
            doc_role, record_role = f"phase{phase}_prereg", f"phase{phase}_prereg_record"
            record = read(record_role)
            checked = verify_document(
                files.path(artifacts[doc_role]),
                files.path(artifacts[record_role]),
                document=record["document"],
            )
            if not checked["ok"] or not any(
                a.get("version") == checked.get("version") for a in record.get("approvals", [])
            ):
                errors.append(f"Phase {phase} preregistration must be archived, unchanged and approved")
        phase19_doc = files.path(artifacts["phase19_prereg"]).read_text(encoding="utf-8")
        if reference["plan_sha256"] not in phase19_doc:
            errors.append("approved Phase 19 preregistration must cite the exact plan digest")
        record = read("phase18_prereg_record")
        checked = verify_lock(
            lock,
            files.path(artifacts["phase18_prereg_record"]),
            document=record["document"],
            doc_path=files.path(artifacts["phase18_prereg"]),
            require_approval=True,
        )
        if not checked["ok"]:
            errors.append(checked["reason"])
        off = lock["offline"]
        if files.files[artifacts["configuration"]] != off["sources"].get("configs/prototype.candidate.yaml"):
            errors.append("configuration must equal the frozen Phase 18 base configuration")
        repo = Path(__file__).resolve().parents[3]
        for relative, digest in off["harness"]["source_sha256"].items():
            path = (repo / relative).resolve()
            if (
                not path.is_relative_to(repo / "src/spacedrums/eval")
                or not path.is_file()
                or file_digest(path) != digest
            ):
                errors.append("frozen harness changed or unavailable: " + relative)
        if off["dataset"]["version"] != "ds-v1.0":
            errors.append("offline lock requires ds-v1.0")
        for role, key in (("dataset_manifest", "manifest_sha256"), ("cv_folds", "split_sha256")):
            # The Phase 07 semantic hashes live INSIDE the manifests, not in the byte digests.
            obj = read(role)
            semantic = obj.get("manifest_hash" if role == "dataset_manifest" else "split_hash")
            if semantic != off["dataset"][key]:
                errors.append(f"{role} differs from offline lock")
        model = read("model_manifest")
        if model.get("source_kind") != "PARTICIPANT" or model.get("dataset_version") != "ds-v1.0":
            errors.append("frozen model must be trained on the participant reference")
        primary = next(a for a in off["arms"] if a["arm_id"] == off["c_primary"])
        for role, field in (
            ("model_manifest", "manifest_sha256"),
            ("model_export", "export_sha256"),
            ("normalization", "norm_stats_sha256"),
        ):
            if files.files[artifacts[role]] != primary["model"].get(field):
                errors.append(f"{role} differs from locked primary model")
        delay = read("processing_delay")
        if delay.get("status") != "MEASURED" or delay.get("accepted") is not True or not delay.get("run_id"):
            errors.append("processing delay requires accepted measured live evidence")
        if delay.get("primary_s") != off["delay"]["primary_s"]:
            errors.append("processing delay differs from lock")
        if delay.get("source_kind") not in ("LIVE_PARTICIPANT", "LIVE_DEVELOPER") or not delay.get(
            "evidence_files"
        ):
            errors.append("processing delay must reference measured live-stroke artifacts")
        for relative in delay.get("evidence_files", []):
            files.path(relative)
        rule = read("operating_rule")
        if rule.get("budgets") != off["budgets"] or not rule.get("rule"):
            errors.append("operating rule/budget differs from lock")
        if reference["w_s"] != off["matching"]["w_primary_s"]:
            errors.append("W differs from frozen Phase 18 reference")
        if reference["plan_sha256"] != rule.get("ablation_plan_sha256"):
            errors.append("approved operating rule must bind the exact Phase 19 plan")
        labels = read("reviewed_labels")
        if labels.get("status") != "REVIEWED" or labels.get("dataset_version") != "ds-v1.0":
            errors.append("reviewed label index required")
        decision = read("phase18_gate_decision")
        if (
            decision.get("phase") != 18
            or decision.get("verdict") not in ("PASS", "PASS-WITH-CONDITIONS")
            or not decision.get("reviewer")
            or not decision.get("reviewed_at")
            or decision.get("execution_blockers") != []
            or decision.get("gate_sha256") != files.files[artifacts["phase18_gate"]]
        ):
            errors.append("valid Phase 18 reviewer gate decision required")
        result = read("reference_results")
        if (
            result.get("evidence") != "PARTICIPANT"
            or result.get("lock", {}).get("sha256") != lock_digest(lock)
            or not result.get("arms", {}).get(off["c_primary"], {}).get("primary", {}).get("per_participant")
        ):
            errors.append("frozen participant reference results required")
        cv = read("cv_folds")
        test = read("test_roster")
        if (
            not cv.get("frozen")
            or not test.get("frozen")
            or cv.get("test_participants") != test.get("test_participants")
        ):
            errors.append("frozen CV/test roster agreement required")
        if any(s["participant_id"] in cv["test_participants"] for s in reference["sessions"]):
            errors.append("raw test sessions are forbidden in the Phase 19 CV reference")
        if errors:
            return errors
        selected = {}
        for fold in cv["folds"]:
            for partition in ("train", "val"):
                for session in session_scope(
                    cv, reference["sessions"], fold=fold["fold"], partition=partition
                ):
                    selected[session["session_id"]] = session
        if set(selected) != {s["session_id"] for s in reference["sessions"]}:
            raise DependencyError("undeclared/outside-CV session in reference")
        for session in selected.values():
            files.session(session)
    except (OSError, ValueError, KeyError, TypeError, StopIteration, ValidationError) as exc:
        errors.append(f"invalid frozen reference: {exc}")
    return errors


def refuse_experimental_execution(reference=None, root="."):
    errors = dependency_errors(reference, root)
    raise DependencyError("; ".join([PREPARATION_ONLY, *errors]))


def load_reference_cv(reference, root, *, fold, partition):
    """Read-only, guarded CV loader seam for a future authorized study.

    This returns existing Phase 08 FeatureSession objects. It neither trains nor writes
    experiment output, and the preparation CLI never calls it to execute a study.
    """
    errors = dependency_errors(reference, root)
    if errors:
        raise DependencyError("; ".join(errors))
    files = FrozenFiles(root, reference["files"])
    cv = files.json(reference["artifacts"]["cv_folds"])
    selected = session_scope(cv, reference["sessions"], fold=fold, partition=partition)
    return [files.session(s) for s in selected]
