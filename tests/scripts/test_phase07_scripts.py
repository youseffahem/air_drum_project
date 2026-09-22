"""TEST-SCRIPTS-4 — the Phase 07 scripts and the review tool in their self-test modes.

Every Phase 07 entry point has a mode that needs neither a person nor a recording, and that mode is
what runs here. The tests assert both that the happy path works and that the refusals fire: a
SYNTHETIC session can never be labelled into a participant dataset, an empty participant manifest
or split is never written, and the acoustic and interpolation results are reported with their
evidence class rather than as measurements.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tools"))

import acoustic_onset  # noqa: E402
import build_dataset_manifest  # noqa: E402
import build_labels  # noqa: E402
import build_splits  # noqa: E402
import label_stats  # noqa: E402
import reference_smoother_check  # noqa: E402
import review_labels  # noqa: E402
import subframe_interpolation  # noqa: E402
import validate_labels  # noqa: E402

# ----------------------------------------------------------------------------- build_labels


def test_build_labels_selftest_generates_validates_and_is_deterministic(capsys):
    assert build_labels.main(["--synthetic", "--check-determinism", "--validate"]) == 0
    out = capsys.readouterr().out
    assert "determinism: IDENTICAL" in out
    assert "validator: CLEAN" in out
    assert "RESULT: PASS" in out


def test_build_labels_reports_the_track_separation(capsys):
    build_labels.main(["--synthetic"])
    out = capsys.readouterr().out
    assert "causal=TrackState" in out
    assert "reference_is_record_stream=False" in out


def test_build_labels_refuses_an_unknown_dataset_version(capsys):
    assert build_labels.main(["--synthetic", "--dataset-version", "v1"]) == 2
    assert "[refused]" in capsys.readouterr().out


def test_build_labels_refuses_to_label_a_synthetic_session_into_a_participant_dataset(capsys):
    rc = build_labels.main(["--synthetic", "--dataset-version", "ds-v1.0"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "cannot enter a participant dataset" in out


def test_build_labels_with_no_session_says_pending(capsys, tmp_path):
    assert build_labels.main(["--session", str(tmp_path / "missing"), "--out", str(tmp_path)]) == 1


# ----------------------------------------------------------------------------- validate_labels


def test_validate_labels_selftest_catches_every_injected_failure(capsys):
    assert validate_labels.main(["--selftest"]) == 0
    out = capsys.readouterr().out
    assert "validator on the clean set: CLEAN" in out
    assert "MISSED" not in out and "SKIPPED" not in out
    for case in ("invalid timestamp", "invalid frame reference", "impossible zone id",
                 "duplicate / conflicting positive", "malformed annotation", "provenance mismatch",
                 "version mismatch", "runtime candidate time copied into ground truth",
                 "SYNTHETIC set relabelled PARTICIPANT"):
        assert f"CAUGHT  {case}" in out


def test_validate_labels_with_no_label_set_is_pending_not_a_failure(capsys, tmp_path):
    assert validate_labels.main(["--all", "--labels-root", str(tmp_path)]) == 0
    assert "nothing to validate" in capsys.readouterr().out


# ----------------------------------------------------------------------------- label_stats


def test_label_stats_selftest_reports_per_source_kind(capsys):
    assert label_stats.main(["--selftest"]) == 0
    out = capsys.readouterr().out
    assert "SYNTHETIC" in out
    assert "### SYNTHETIC" in out
    assert "intensity_proxy_gt" in out


def test_label_stats_without_labels_reports_pending(capsys, tmp_path):
    assert label_stats.main(["--all", "--labels-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "PENDING" in out
    assert "no labels exist" in out


def test_label_stats_writes_its_report(tmp_path):
    out = tmp_path / "stats.md"
    assert label_stats.main(["--selftest", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Phase 07 label statistics")


# ----------------------------------------------------------------------------- build_splits


def test_build_splits_plan_prints_the_rule_table(capsys):
    assert build_splits.main(["--plan"]) == 0
    out = capsys.readouterr().out
    assert "P07-SPLIT-1" in out
    assert "TRAIN participants" in out


def test_build_splits_selftest_passes_the_leakage_checks_and_the_refusals(capsys):
    assert build_splits.main(["--selftest"]) == 0
    out = capsys.readouterr().out
    assert "'all_passed': True" in out
    assert "determinism: IDENTICAL" in out
    assert out.count("REFUSED") == 3
    assert "NOT REFUSED" not in out


def test_build_splits_without_labels_reports_pending(capsys, tmp_path):
    rc = build_splits.main(["--dataset-version", "ds-v1.0", "--labels-root", str(tmp_path),
                            "--splits-root", str(tmp_path / "splits")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "RESULT: PENDING (participant data required)" in out
    assert not (tmp_path / "splits").exists()


# ----------------------------------------------------------------------------- dataset manifest


def test_build_dataset_manifest_selftest(capsys):
    assert build_dataset_manifest.main(["selftest"]) == 0
    out = capsys.readouterr().out
    assert "file re-hash: MATCH" in out
    assert "determinism: IDENTICAL" in out
    assert "REFUSED     writing an empty participant manifest" in out
    assert "NOT REFUSED" not in out


def test_build_dataset_manifest_refuses_an_empty_participant_dataset(capsys, tmp_path):
    rc = build_dataset_manifest.main(
        ["--labels-root", str(tmp_path), "--manifests-dir", str(tmp_path / "m"), "build", "ds-v1.0"]
    )
    assert rc == 2
    assert "refusing to write an empty PARTICIPANT" in capsys.readouterr().out
    assert not (tmp_path / "m" / "ds-v1.0.json").exists()


def test_build_dataset_manifest_card_needs_a_manifest(capsys, tmp_path):
    rc = build_dataset_manifest.main(
        ["--manifests-dir", str(tmp_path), "card", "ds-v1.0", "--out", str(tmp_path / "card.md")]
    )
    assert rc == 2
    assert "build it first" in capsys.readouterr().out


# ----------------------------------------------------------------------------- acoustic


def test_acoustic_onset_selftest_recovers_the_injected_offset(capsys):
    assert acoustic_onset.main(["--selftest"]) == 0
    out = capsys.readouterr().out
    assert "RESULT: PASS" in out
    assert "is not a measurement of any physical latency" in out


def test_acoustic_onset_without_a_labelled_session_is_pending(capsys, tmp_path):
    assert acoustic_onset.main(["--all", "--labels-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "PENDING" in out


# ----------------------------------------------------------------------------- interpolation


def test_subframe_interpolation_reports_two_tables_with_a_declared_rule(capsys, tmp_path):
    out_path = tmp_path / "interp.md"
    assert subframe_interpolation.main(["--n", "8", "--out", str(out_path)]) == 0
    text = out_path.read_text(encoding="utf-8")
    assert "Table 1" in text and "Table 2" in text
    assert "Declared before the run" in text
    assert "SYNTHETIC" in text
    assert "PENDING / NOT VALIDATED" in text


def test_subframe_interpolation_against_a_physical_reference_is_pending(capsys):
    assert subframe_interpolation.main(["--session", "x", "--labels", "y"]) == 0
    assert "PENDING / NOT VALIDATED" in capsys.readouterr().out


def test_synthetic_events_produce_paired_errors_for_both_estimators():
    lin, quad, n = subframe_interpolation.synthetic_events(n=6)
    assert n == len(lin) == len(quad) > 0


# ----------------------------------------------------------------------------- smoother check


def test_reference_smoother_check_shows_the_over_smoothing_risk(capsys, tmp_path):
    out_path = tmp_path / "smoother.md"
    assert reference_smoother_check.main(["--n", "8", "--noise", "0.0", "--out", str(out_path)]) == 0
    text = out_path.read_text(encoding="utf-8")
    assert "Entries survived" in text
    assert "PENDING / NOT VALIDATED" in text
    assert "Evidence class: SYNTHETIC" in text


def test_the_default_smoother_keeps_every_synthetic_entry():
    row = reference_smoother_check.evaluate("rts-kalman-cv-v1", {"q": 200.0}, noise=0.0, n=8)
    assert row["entries_survived"] == row["n"]


def test_the_phase03_process_noise_loses_entries_as_documented():
    """The reason `smooth.DEFAULT_KALMAN_PARAMS` differs from the tracker's: this must keep failing
    if someone 'harmonises' the two."""
    row = reference_smoother_check.evaluate("rts-kalman-cv-v1", {"q": 5.0}, noise=0.0, n=24)
    assert row["entries_survived"] < row["n"]


# ----------------------------------------------------------------------------- review tool


def test_review_tool_selftest_round_trips_and_computes_agreement(capsys):
    assert review_labels.selftest() == 0
    out = capsys.readouterr().out
    assert "original kept = True" in out
    assert "append-only" in out
    assert "NOT inter-annotator agreement and no such agreement is claimed" in out


def test_review_tool_agreement_without_a_log_is_pending(capsys, tmp_path):
    assert review_labels.main(["--agreement", "--labels", str(tmp_path)]) == 0
    assert "PENDING / NOT VALIDATED" in capsys.readouterr().out


def test_review_tool_requires_its_arguments_for_an_interactive_run():
    with pytest.raises(SystemExit):
        review_labels.main(["--labels", "x"])


def test_scripted_decisions_are_deterministic():
    labels = [
        {"label_id": f"id-{k}", "t_impact_est": 100.0 + k, "t_event": 100.0 + k,
         "zone_id": "snare", "label_class": "POSITIVE"}
        for k in range(10)
    ]
    a = review_labels.scripted_decisions(labels, pass_no=1)
    b = review_labels.scripted_decisions(labels, pass_no=1)
    assert a == b
    assert review_labels.scripted_decisions(labels, pass_no=2) != a


# ----------------------------------------------------------------------------- examples


def test_the_schema_examples_are_regenerable_and_match_what_is_committed(tmp_path):
    """The committed examples must be what the producers actually write; a drift here means a
    contract change that was not carried into the examples."""
    import json

    import _p07_examples

    committed = {
        stem: json.loads((ROOT / "schemas" / "examples" / f"{stem}.valid.example.json")
                         .read_text(encoding="utf-8"))
        for stem in ("label-record", "reference-track", "label-set", "label-review", "split-file",
                     "dataset-manifest")
    }
    assert _p07_examples.main() == 0
    for stem, before in committed.items():
        after = json.loads((ROOT / "schemas" / "examples" / f"{stem}.valid.example.json")
                           .read_text(encoding="utf-8"))
        assert after == before, f"{stem} example drifted from its producer"
