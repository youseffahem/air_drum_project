"""Phase 17 Task 17.1: requirement -> test traceability matrix (``docs/testing/test-matrix.md``).

    python scripts/build_test_matrix.py            # regenerate the document
    python scripts/build_test_matrix.py --check    # fail if the document is stale or the map is incomplete

The map below is **curated** (a keyword search cannot tell which test verifies a requirement). The
script adds what is mechanical: the RTM row text/type/phases/status, the level of every referenced
test file (by directory), the number of test functions per file, and the checks that make the
matrix trustworthy: every RTM requirement is mapped; every referenced file exists; every
requirement whose RTM verification says ``test`` has at least one automated test or an explicit
justification. ``tests/system/test_system_matrix.py`` runs the same checks in CI.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RTM = ROOT / "docs" / "requirements" / "rtm.md"
OUT = ROOT / "docs" / "testing" / "test-matrix.md"

LEVELS = ("unit", "integration", "system", "failure_injection", "invariants")
LEVEL_OF_DIR = {
    "system": "system",
    "failure_injection": "failure_injection",
    "invariants": "invariants",
    "app": "integration",
    "parity": "integration",
    "scripts": "integration",
    "architecture": "integration",
}

# REQ -> (test files, non-automated evidence / justification). Test paths are relative to tests/.
T = {
    "app": "app/test_app_pipeline.py",
    "app_rec": "app/test_app_recorder_summary.py",
    "parity": "parity/test_live_model.py",
    "sys_app": "system/test_system_app.py",
    "sys_offline": "system/test_system_offline.py",
    "sys_matrix": "system/test_system_matrix.py",
    "fi_track": "failure_injection/test_fi_tracking.py",
    "fi_vision": "failure_injection/test_fi_vision.py",
    "fi_cap": "failure_injection/test_fi_capture.py",
    "fi_mdl": "failure_injection/test_fi_model_audio.py",
    "inv": "invariants/test_inv_monitor.py",
    "inv_replay": "invariants/test_inv_replay.py",
    "app_health": "app/test_app_health_errors.py",
    "geo_zones": "geometry/test_zones.py",
    "geo_int": "geometry/test_intersect.py",
    "geo_imp": "geometry/test_impact.py",
    "audio_bank": "audio/test_bank_gain.py",
    "audio_mix": "audio/test_device_mixer.py",
    "audio_sched": "audio/test_scheduler_integration.py",
    "cap_src": "capture/test_source.py",
    "cap_roi": "capture/test_roi.py",
    "cap_stats": "capture/test_stats_and_queue.py",
    "cap_ts": "capture/test_timestamps.py",
    "cap_replay": "capture/test_replay_source.py",
    "cap_hw": "capture/test_hardware_capture.py",
    "hands_id": "hands/test_identity.py",
    "hands_lm": "hands/test_landmarker.py",
    "hands_coords": "hands/test_coords.py",
    "hands_grip": "hands/test_grip.py",
    "stick_est": "stick/test_estimators.py",
    "stick_geo": "stick/test_geometry.py",
    "trk_sm": "tracking/test_state_machine.py",
    "trk": "tracking/test_tracker.py",
    "trk_causal": "tracking/test_causal.py",
    "trk_filt": "tracking/test_filters.py",
    "pred": "prediction/test_rule_based.py",
    "pred_causal": "prediction/test_causal_anticipator.py",
    "commit": "commit/test_commit_policy.py",
    "commit_sm": "commit/test_commit_state_machine.py",
    "commit_causal": "commit/test_causal_commit.py",
    "feat_causal": "features/test_causality.py",
    "feat_core": "features/test_core.py",
    "feat_io": "features/test_io.py",
    "eval": "eval/test_harness.py",
    "gbdt": "eval/test_gbdt_adapter.py",
    "tmp_models": "temporal/test_models.py",
    "tmp_adapter": "temporal/test_adapter.py",
    "tmp_proto": "temporal/test_temporal_protocol.py",
    "tmp_mt": "temporal/test_mt_heads_losses.py",
    "tmp_mt_inv": "temporal/test_mt_invariant.py",
    "tmp_ext": "temporal/test_ext_causal.py",
    "calib_wiz": "calib/test_calib_wizard_flow.py",
    "calib_fit": "calib/test_calib_fit.py",
    "calib_app": "calib/test_calib_app.py",
    "calib_reg": "calib/test_calib_regression.py",
    "calib_apply": "calib/test_calib_apply.py",
    "calib_steps": "calib/test_calib_steps.py",
    "ui_guide": "ui/test_guide.py",
    "ui_dash": "ui/test_phase15_dashboard.py",
    "cfg": "config/test_loader.py",
    "schemas": "contracts/test_record_schemas.py",
    "arch": "architecture/test_import_layers.py",
    "data_proto": "data/test_protocol.py",
    "data_meta": "data/test_metadata.py",
    "data_manifest": "data/test_manifest.py",
    "lab_rules": "labels/test_label_rules.py",
    "lab_split": "labels/test_dataset_splits.py",
    "lab_leak": "labels/test_label_leakage.py",
    "lab_gen": "labels/test_label_generator.py",
    "scripts16": "scripts/test_phase16.py",
    "timing": "timing/test_timing_records.py",
    "p18_stats": "live_eval/test_live_eval_stats.py",
    "p18_prereg": "live_eval/test_live_eval_prereg.py",
    "p18_methods": "live_eval/test_live_eval_methods.py",
    "p18_live": "live_eval/test_live_eval_protocol.py",
    "p18_offline": "live_eval/test_live_eval_offline.py",
    "p18_scripts": "scripts/test_phase18_scripts.py",
}


def t(*keys: str) -> list[str]:
    return [T[k] for k in keys]


REVIEW = "review / measurement evidence (not an automated test)"
MAP: dict[str, dict] = {
    "REQ-001": {
        "tests": t("app", "parity", "sys_app", "inv_replay"),
        "other": "architecture review (Phase 01)",
    },
    "REQ-002": {
        "tests": t("p18_methods", "p18_live", "p18_stats"),
        "other": "external timing machinery (M1/M2/M3, live protocol) on SYNTHETIC recordings; live "
        "measurement with people PENDING (18)",
    },
    "REQ-003": {"tests": [], "other": "review: protocol difficulty (06), demo framing (22)"},
    "REQ-004": {
        "tests": t("app", "calib_app", "ui_guide", "sys_app"),
        "other": "live system test with a person PENDING (C-05-1)",
    },
    "REQ-005": {
        "tests": t("eval", "p18_offline", "p18_stats"),
        "other": "harness (09) + Phase 18 confirmatory layer; participant measurement PENDING",
    },
    "REQ-006": {"tests": t("sys_app"), "other": "review + usability demonstration PENDING (C-05-1)"},
    "REQ-007": {"tests": t("stick_est"), "other": "system test with real sticks PENDING (person)"},
    "REQ-008": {"tests": t("arch"), "other": "review (out-of-scope register)"},
    "REQ-009": {"tests": t("stick_est"), "other": "benchmark (03); Phase 18: no marker condition used"},
    "REQ-010": {"tests": t("hands_lm", "stick_est", "trk"), "other": "tracking latency measured (03)"},
    "REQ-011": {"tests": t("geo_zones", "app"), "other": "revisit PENDING participant evidence (18)"},
    "REQ-012": {
        "tests": t("app", "fi_track", "inv"),
        "other": "live protocol with a person PENDING; fast-hit limit machinery SYNTHETIC",
    },
    "REQ-013": {
        "tests": t("fi_track"),
        "other": "max hit rate: developer-played measurement PENDING (Phase 17 Open Question)",
    },
    "REQ-014": {"tests": t("audio_bank", "tmp_mt"), "other": "agreement measurement (11) PENDING"},
    "REQ-015": {"tests": t("geo_zones"), "other": "review"},
    "REQ-016": {"tests": t("geo_zones", "calib_fit"), "other": "ADR-0003 layout review"},
    "REQ-017": {"tests": t("geo_zones", "audio_bank"), "other": "review"},
    "REQ-018": {"tests": t("geo_zones", "calib_reg"), "other": ""},
    "REQ-019": {"tests": t("ui_guide", "calib_steps"), "other": ""},
    "REQ-020": {"tests": t("ui_dash"), "other": "review (architecture untouched by UI work)"},
    "REQ-021": {"tests": t("schemas"), "other": "review (coordinate convention)"},
    "REQ-022": {"tests": t("cap_hw"), "other": "review (camera profile); hardware test opt-in"},
    "REQ-023": {
        "tests": t("cap_src", "cap_stats"),
        "other": "native FPS measured (02); 60 FPS attempt (16) PENDING camera",
    },
    "REQ-024": {"tests": [], "other": "review (placement recorded per session)"},
    "REQ-025": {"tests": [], "other": "distance benchmark PENDING (person)"},
    "REQ-026": {"tests": t("cap_roi"), "other": "review (ROI definition)"},
    "REQ-027": {
        "tests": t("fi_vision", "p18_offline"),
        "other": "lighting replay perturbation (17, development); multi-lighting sessions (06/18) PENDING",
    },
    "REQ-028": {
        "tests": t("fi_track", "fi_vision", "p18_offline"),
        "other": "occlusion / background injection (17); dataset variation (06/18) PENDING",
    },
    "REQ-029": {
        "tests": t("hands_id", "fi_track", "fi_vision"),
        "other": "live second-person test PENDING (two people)",
    },
    "REQ-030": {"tests": [], "other": "stick-colour benchmark (03) PENDING"},
    "REQ-031": {"tests": t("stick_est", "stick_geo"), "other": "tip-method benchmark (03)"},
    "REQ-032": {"tests": t("hands_grip"), "other": "protocol records grip variation (06)"},
    "REQ-033": {"tests": t("hands_id", "trk", "app"), "other": "contracts review (01)"},
    "REQ-034": {"tests": t("trk_sm", "trk_causal", "fi_track", "fi_cap", "inv"), "other": ""},
    "REQ-035": {
        "tests": t("trk_sm", "app", "fi_track", "inv", "inv_replay"),
        "other": "live induced-loss test PENDING (person)",
    },
    "REQ-036": {"tests": t("geo_int"), "other": ""},
    "REQ-037": {"tests": t("geo_int"), "other": ""},
    "REQ-038": {"tests": t("geo_int", "lab_gen"), "other": ""},
    "REQ-039": {"tests": t("geo_imp"), "other": ""},
    "REQ-040": {
        "tests": t("eval", "p18_offline", "p18_scripts"),
        "other": "sweeps (09/10) + Phase 18 declared curve sweep; participant data PENDING",
    },
    "REQ-041": {"tests": t("tmp_mt"), "other": "per-task participant metrics PENDING"},
    "REQ-042": {"tests": t("tmp_adapter", "geo_int", "parity"), "other": ""},
    "REQ-043": {"tests": t("pred", "gbdt"), "other": "review (baselines exist)"},
    "REQ-044": {
        "tests": t("tmp_models", "tmp_ext", "gbdt"),
        "other": "selection measurement PENDING participant data",
    },
    "REQ-045": {
        "tests": t("eval", "p18_offline", "p18_scripts"),
        "other": "README 10 metrics + Spearman, causal-target ADE/FDE, strata; participant data PENDING",
    },
    "REQ-046": {"tests": [], "other": "review: recording manifest (0 participants, PENDING)"},
    "REQ-047": {"tests": t("data_proto"), "other": "review"},
    "REQ-048": {"tests": t("data_proto", "lab_rules"), "other": "QC coverage on participant data PENDING"},
    "REQ-049": {"tests": t("lab_split", "data_manifest"), "other": "release decision (23)"},
    "REQ-050a": {
        "tests": t("sys_app", "inv_replay"),
        "other": "soak (17, development); demo rehearsal (22) PENDING",
    },
    "REQ-050b": {
        "tests": t("p18_stats", "p18_offline"),
        "other": "declared H1a/H2/H3 rules tested; participant measurement (18) PENDING",
    },
    "REQ-050c": {
        "tests": t("p18_stats", "p18_methods", "p18_prereg"),
        "other": "pre-registered rules + external methods; measurement and claims audit (18/21) PENDING",
    },
    "REQ-051": {"tests": t("hands_id"), "other": "review (single LEFT/RIGHT identity)"},
    "REQ-052": {"tests": t("sys_offline"), "other": "packaged bundle offline check (23)"},
    "REQ-053": {"tests": t("audio_bank"), "other": ""},
    "REQ-054": {"tests": [], "other": "review (out-of-scope register)"},
    "REQ-055": {"tests": t("cfg", "geo_zones"), "other": "review (registry extensibility)"},
    "REQ-056": {"tests": t("calib_apply"), "other": "review"},
    "REQ-057": {"tests": t("calib_wiz", "calib_app"), "other": "live developer calibrations PENDING"},
    "REQ-058": {"tests": t("ui_dash"), "other": "review (all ten items present)"},
    "REQ-059": {"tests": [], "other": "review (22)"},
    "REQ-060a": {"tests": [], "other": "integrity checklist at every gate"},
    "REQ-060b": {
        "tests": t(
            "trk_causal",
            "pred_causal",
            "commit_causal",
            "feat_causal",
            "tmp_ext",
            "parity",
            "inv",
            "inv_replay",
        ),
        "other": "system-level TEST-CAUSAL-1 re-run (17, development)",
    },
    "REQ-060c": {
        "tests": t("p18_methods"),
        "other": "sound-before-impact only from external measurement (none yet); claims audit (18/21)",
    },
    "REQ-060d": {"tests": [], "other": "review (00 policy, 21)"},
    "REQ-101": {"tests": t("cap_src", "cap_hw", "fi_cap"), "other": ""},
    "REQ-102": {"tests": t("cap_roi"), "other": ""},
    "REQ-103": {"tests": t("hands_lm", "hands_coords"), "other": ""},
    "REQ-104": {"tests": t("stick_geo"), "other": "benchmark (03)"},
    "REQ-105": {"tests": t("stick_geo"), "other": "benchmark (03)"},
    "REQ-106": {"tests": t("stick_est"), "other": "benchmark (03)"},
    "REQ-107": {"tests": t("trk", "trk_causal", "trk_filt"), "other": ""},
    "REQ-108": {
        "tests": t("feat_core", "feat_causal", "feat_io", "parity"),
        "other": "participant-fold parity PENDING",
    },
    "REQ-109": {"tests": t("tmp_models", "tmp_proto"), "other": "ADE/FDE on participants PENDING"},
    "REQ-110": {"tests": t("geo_zones", "geo_int"), "other": ""},
    "REQ-111": {"tests": t("geo_int"), "other": ""},
    "REQ-112": {"tests": t("pred", "tmp_adapter"), "other": "measurement PENDING"},
    "REQ-113": {"tests": t("pred", "tmp_mt"), "other": "measurement PENDING"},
    "REQ-114": {"tests": t("commit", "commit_sm", "commit_causal", "inv", "fi_mdl"), "other": ""},
    "REQ-115": {"tests": t("audio_bank", "audio_mix"), "other": ""},
    "REQ-116": {
        "tests": t("audio_sched", "audio_mix", "fi_mdl"),
        "other": "output-latency measurement PENDING (04)",
    },
    "REQ-117": {"tests": t("p18_stats", "p18_offline"), "other": "research measurement (10/18) PENDING"},
    "REQ-201": {"tests": [], "other": "review (out-of-scope register)"},
    "REQ-202": {"tests": [], "other": "review (out-of-scope register)"},
    "REQ-203": {"tests": [], "other": "review (out-of-scope register)"},
    "REQ-204": {"tests": t("hands_id"), "other": "review; single-user identity rule (17)"},
    "REQ-205": {"tests": [], "other": "review (out-of-scope register)"},
    "REQ-206": {"tests": t("schemas"), "other": "review (two-component points)"},
    "REQ-207": {"tests": t("cfg", "geo_zones"), "other": "review (reserved, not built)"},
    "REQ-208": {"tests": [], "other": "review (out-of-scope register)"},
    "REQ-209": {"tests": t("sys_offline"), "other": "review + offline test"},
    "REQ-210": {"tests": t("stick_est"), "other": "review (markerless primary)"},
    "REQ-211": {"tests": t("stick_est"), "other": "review (marker results labelled); none in Phase 18"},
    "REQ-301": {"tests": [], "other": "integrity checklist / claims audit"},
    "REQ-302": {
        "tests": t(
            "trk_causal", "pred_causal", "commit_causal", "feat_causal", "tmp_ext", "inv", "inv_replay"
        ),
        "other": "",
    },
    "REQ-303": {"tests": t("eval"), "other": "measurement (09/18)"},
    "REQ-304": {"tests": t("parity", "scripts16"), "other": "latency budgets measured (13/16); live PENDING"},
    "REQ-305": {
        "tests": t("fi_track", "fi_vision", "fi_cap", "fi_mdl", "inv"),
        "other": "physical injection with a person PENDING",
    },
    "REQ-306": {
        "tests": ["ablation/test_ablation.py", "ablation/test_retrack.py"],
        "other": "SYNTHETIC/DEV preparation only; participant ablation measurement PENDING Phase 18 (19)",
    },
    "REQ-307": {
        "tests": t("p18_prereg", "p18_scripts", "p18_stats"),
        "other": "pre-registered comparison: machinery + SYNTHETIC rehearsal; participant run PENDING",
    },
    "REQ-308": {"tests": t("schemas", "scripts16"), "other": "reproducibility policy review"},
    "REQ-309": {"tests": [], "other": "review (21); Phase 17 failure catalogue feeds it"},
    "REQ-310": {"tests": [], "other": "review (15/22)"},
}


def rtm_rows() -> dict[str, dict[str, str]]:
    rows = {}
    for line in RTM.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        req = next((c for c in cells if re.fullmatch(r"REQ-\d{3}[a-d]?", c)), None)
        if req is None or line.startswith("| Q#") or line.startswith("| REQ |"):
            continue
        i = cells.index(req)
        rest = cells[i + 1 :]
        if len(rest) < 5:
            continue
        text, typ, phases, verification, status = rest[0], rest[1], rest[2], rest[3], rest[-1]
        rows[req] = {
            "text": re.sub(r"\s+", " ", text),
            "type": typ,
            "phases": phases,
            "verification": verification,
            "status": status,
        }
    return rows


def level(path: str) -> str:
    return LEVEL_OF_DIR.get(path.split("/", 1)[0], "unit")


def test_count(path: str) -> int:
    p = ROOT / "tests" / path
    if not p.exists():
        return -1
    return len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), flags=re.M))


def problems() -> list[str]:
    rows = rtm_rows()
    out = []
    for req in rows:
        if req not in MAP:
            out.append(f"{req} is in the RTM but not in the test matrix")
    for req, entry in MAP.items():
        if req not in rows:
            out.append(f"{req} is mapped but not in the RTM")
        for path in entry["tests"]:
            if not (ROOT / "tests" / path).exists():
                out.append(f"{req}: referenced test file tests/{path} does not exist")
        verification = rows.get(req, {}).get("verification", "")
        if "test" in verification and not entry["tests"] and not entry["other"]:
            out.append(f"{req}: RTM verification needs a test; none mapped and no justification")
    return out


def status_of(req: str, entry: dict, row: dict) -> str:
    verification = row["verification"]
    needs_test = "test" in verification.lower()
    if entry["tests"]:
        return (
            "COVERED"
            if not entry["other"] or "PENDING" not in entry["other"]
            else "COVERED + PENDING evidence"
        )
    if needs_test:
        return "GAP"
    return "JUSTIFIED (non-test verification)"


def render() -> str:
    rows = rtm_rows()
    lines = [
        "# Test matrix: requirements -> tests (Phase 17, Task 17.1)",
        "",
        "Generated by `scripts/build_test_matrix.py` from the curated map in that script and",
        "[`../requirements/rtm.md`](../requirements/rtm.md); `tests/system/test_system_matrix.py` fails",
        "if this file is stale, a requirement is unmapped, or a referenced test file is missing.",
        "",
        "**Levels.** *unit* = the per-subpackage suites (`tests/<subpackage>/`); *integration* =",
        "`tests/app/`, `tests/parity/`, `tests/scripts/`, `tests/architecture/` (several modules,",
        "the live loop, scripts); *system* = `tests/system/` (the application entry point end to",
        "end); *failure_injection* = `tests/failure_injection/`; *invariants* = `tests/invariants/`.",
        "Existing per-subpackage directories were kept (no churn); the level is a property of the",
        "directory (deviation recorded in the gate record).",
        "",
        "**Status column.** COVERED = at least one automated test verifies the requirement's",
        "testable part; COVERED + PENDING evidence = automated tests exist, a measurement or a",
        "person-dependent check the RTM also asks for is still PENDING; JUSTIFIED = the RTM verifies",
        "the requirement by review or measurement only (reason given); GAP = the RTM asks for a test",
        "and none exists. RTM statuses are **not** advanced here (only a signed gate may do that).",
        "",
        "Test counts are `def test_` functions per file (parametrised cases are counted by pytest",
        "separately).",
        "",
    ]
    counts = {"COVERED": 0, "COVERED + PENDING evidence": 0, "JUSTIFIED (non-test verification)": 0, "GAP": 0}
    body = [
        "| REQ | Type | Owner(s) | RTM verification | Unit | Integration | System | Failure injection | Invariants | Other evidence / justification | Matrix status |",  # noqa: E501 - one Markdown table row
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for req, row in rows.items():
        entry = MAP[req]
        by_level: dict[str, list[str]] = {lv: [] for lv in LEVELS}
        for path in entry["tests"]:
            by_level[level(path)].append(f"`{path}` ({test_count(path)})")
        status = status_of(req, entry, row)
        counts[status] += 1
        body.append(
            f"| {req} | {row['type']} | {row['phases']} | {row['verification']} | "
            + " | ".join("<br>".join(by_level[lv]) or "-" for lv in LEVELS)
            + f" | {entry['other'] or '-'} | {status} |"
        )
    lines += [
        f"**Summary:** {len(rows)} requirements; " + "; ".join(f"{k}: {v}" for k, v in counts.items()) + ".",
        "",
        "## Gap list",
        "",
        "Gaps found when the matrix was first built (2026-09-26) and how Phase 17 closed them:",
        "",
        "| Requirement | Gap | Closure |",
        "|---|---|---|",
        "| REQ-052, REQ-209 | no automated check that the application runs offline / makes no network call | `tests/system/test_system_offline.py`: static import scan of `src/spacedrums` + a session with socket creation blocked |",  # noqa: E501 - one Markdown table row
        "| REQ-012, REQ-034, REQ-035, REQ-305 | no failure-injection coverage of the hit types / loss durations beyond the Phase 05 synthetic induced-loss test | `tests/failure_injection/test_fi_tracking.py` (occlusion 100-1000 ms at approach / impact / idle, swaps, background hand, low confidence) + the `inject_faults.py` campaign |",  # noqa: E501 - one Markdown table row
        "| REQ-027, REQ-028, REQ-029 | lighting / occlusion / background robustness untested | `tests/failure_injection/test_fi_vision.py` (developer capture: occlusion masks, lighting gain/gamma, distractor; skips without the capture) + identity rule tests |",  # noqa: E501 - one Markdown table row
        "| REQ-001, REQ-004, REQ-006, REQ-050a | no system-level test of the application entry point with the safety monitors on | `tests/system/test_system_app.py` |",  # noqa: E501 - one Markdown table row
        "| REQ-060b, REQ-302 | causality verified per component, not on the hardened live loop as a whole | `tests/invariants/` (I2 monitor) + `scripts/invariant_replay.py` system-level TEST-CAUSAL-1 |",  # noqa: E501 - one Markdown table row
        "| REQ-013 | no machinery for the maximum separable hit rate | SYNTHETIC fast-hit sweep in `inject_faults.py --suite fasthit`; developer-played measurement stays PENDING |",  # noqa: E501 - one Markdown table row
        "",
        "Remaining justified non-test rows are research measurements (Phases 18/19), person- or",
        "participant-dependent checks, and review-only scope rules; each names its evidence above.",
        "",
        "## Matrix",
        "",
    ]
    lines += body
    lines += [""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    issues = problems()
    for issue in issues:
        print("MATRIX:", issue)
    text = render()
    if args.check:
        stale = not OUT.exists() or OUT.read_text(encoding="utf-8") != text
        if stale:
            print("MATRIX: docs/testing/test-matrix.md is stale; run scripts/build_test_matrix.py")
        return 1 if issues or stale else 0
    if issues:
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
