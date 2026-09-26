"""Phase 14 executable checks used by scripts/verify_phase14.py (each prints ASCII and exits 0 on success).

    python scripts/_p14.py regression   --out <dir>                      # recording layout -> zero drift
    python scripts/_p14.py model-compat --calibration <file> --out <dir> # pinned Phase 10 GRU, moved layout
    python scripts/_p14.py session      --calibration <file> --session <dir>
    python scripts/_p14.py metadata     --calibration <file> --root <dir>

SYNTHETIC inputs only (scripted actor / analytic sequences); every result is machinery evidence, never a
measurement of a person. The pinned Phase 10 package is SYNTHETIC-trained and not a shipped model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "configs/prototype.candidate.yaml"
LIVE = ROOT / "configs/live.arm-C.candidate.yaml"
MVP4 = ROOT / "configs/zones/mvp4.candidate.yaml"
PINNED = ROOT / "experiments/phase-10/20260924-1926-synthetic-horizon/models/cell-000/manifest.json"


def write(out: Path, name: str, data: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


def regression(args: argparse.Namespace) -> int:
    """FIXED fit of the recording layout (MVP-4): zones, resolved config and feature fingerprint unchanged."""
    from spacedrums.app import calibrate
    from spacedrums.calib import load_calibrated_config, load_calibration
    from spacedrums.config import canonical_json, load_config
    from spacedrums.features.schema import FeatureSchema

    path = args.out / "recording-layout-fixed.calib.yaml"
    code = calibrate.main(
        [
            "--synthetic",
            "--fit-mode",
            "FIXED",
            "--scope",
            "SETUP",
            "--setup-tag",
            "recording-layout",
            "--output",
            str(path),
            "--seed",
            "5",
            "--synthetic-noise",
            "0.002",
        ]
    )
    calib = load_calibration(path)
    phase04 = yaml.safe_load(MVP4.read_text(encoding="utf-8"))["zones"]
    cfg = load_calibrated_config(PROTOTYPE, calibration=path).config.data
    options = {
        "groups": ["POS", "VEL", "ACC", "AXIS", "HAND", "ZONE", "CONF", "TIME"],
        "epsilon": 1e-6,
        "tts_clip_s": 2.0,
    }
    fingerprint = FeatureSchema(cfg["zones"], **options).fingerprint
    pinned = (
        json.loads(PINNED.read_text(encoding="utf-8"))["feature_schema_hash"] if PINNED.is_file() else None
    )
    result = {
        "wizard_exit": code,
        "calibration_hash": calib.hash,
        "fit": {k: calib.doc["layout"]["fit"][k] for k in ("mode", "scale", "translate")},
        "zones_equal_phase04": calib.doc["layout"]["zones"] == phase04,
        "canonical_bytes_equal": canonical_json(calib.doc["layout"]["zones"]) == canonical_json(phase04),
        "resolved_config_zones_equal_prototype": cfg["zones"] == load_config(PROTOTYPE).data["zones"],
        "feature_fingerprint": fingerprint,
        "feature_fingerprint_equals_phase04": fingerprint == FeatureSchema(phase04, **options).fingerprint,
        "pinned_manifest_feature_schema_hash": pinned,
        "feature_fingerprint_equals_pinned_model": None if pinned is None else fingerprint == pinned,
        "label": "SYNTHETIC actor; geometry regression (exact equality)",
    }
    write(args.out, "regression.json", result)
    ok = code == 0 and all(
        result[k]
        for k in (
            "zones_equal_phase04",
            "canonical_bytes_equal",
            "resolved_config_zones_equal_prototype",
            "feature_fingerprint_equals_phase04",
        )
    )
    ok = ok and result["feature_fingerprint_equals_pinned_model"] is not False
    print(
        f"[p14] regression {'PASS' if ok else 'FAIL'}: zones_equal={result['zones_equal_phase04']} "
        f"pinned_fingerprint_equal={result['feature_fingerprint_equals_pinned_model']}"
    )
    return 0 if ok else 1


def model_compat(args: argparse.Namespace) -> int:
    """The pinned SYNTHETIC-trained Phase 10 GRU verifies against the template and reads calibrated zones."""
    if not PINNED.is_file():
        print("[p14] model-compat SKIPPED: pinned Phase 10 package absent (experiments/ is not committed)")
        write(args.out, "model-compat.json", {"status": "SKIPPED", "reason": "pinned package absent"})
        return 0
    from spacedrums.app.pipeline import DecisionPipeline
    from spacedrums.app.synthetic import scenario
    from spacedrums.calib import load_calibrated_config
    from spacedrums.geometry import ZoneRegistry

    cc = load_calibrated_config(LIVE, calibration=args.calibration)
    cfg = cc.config.data
    registry = ZoneRegistry.from_config(cfg["zones"])
    pipe = DecisionPipeline(
        cfg,
        registry=registry,
        session_id="p14-model-compat",
        active_arm="C-GRU",
        shadow_arms=("A", "B"),
        hardware_id="HW-01",
        config_hash=cc.config.config_hash,
        audio=None,
        gain_fn=lambda _z, _v: 1.0,
    )
    commits = []
    for sample, obs in scenario("repeated", registry):
        commits += pipe.step(sample, obs, t_now=sample.t_frame_available).commits
    stream_zones = pipe.model_arm.stream.schema.zones_config if pipe.model_arm else None
    result = {
        "calibration_hash": cfg["calibration"]["calibration_hash"],
        "model_id": pipe.model_arm.model_id if pipe.model_arm else None,
        "model_error": pipe.model_error,
        "feature_layout": pipe.feature_layout,
        "stream_zones_equal_calibrated": stream_zones == cfg["zones"],
        "predictions": pipe.model_arm.predictions if pipe.model_arm else 0,
        "commits_by_arm": {a: sum(1 for c in commits if str(c.arm) == a) for a in ("A", "B", "C-GRU")},
        "label": "SYNTHETIC-trained development package on a SYNTHETIC calibration; machinery check only",
    }
    write(args.out, "model-compat.json", result)
    ok = (
        result["model_error"] is None
        and result["stream_zones_equal_calibrated"]
        and bool(result["feature_layout"])
        and result["predictions"] > 0
    )
    adapted = (result["feature_layout"] or {}).get("layout_adapted")
    verdict = "PASS" if ok else "FAIL"
    print(f"[p14] model-compat {verdict}: adapted={adapted} predictions={result['predictions']}")
    return 0 if ok else 1


def session(args: argparse.Namespace) -> int:
    from spacedrums.calib import load_calibration

    calib = load_calibration(args.calibration)
    sessions = [p for p in args.session.iterdir() if (p / "session.json").is_file()]
    meta = json.loads((sessions[0] / "session.json").read_text(encoding="utf-8"))
    snap_text = (sessions[0] / "config.snapshot.yaml").read_text(encoding="utf-8")
    snap = yaml.safe_load(snap_text)
    result = {
        "session": str(sessions[0]),
        "calibration": meta.get("calibration"),
        "copied_file_identical": (sessions[0] / "calibration.calib.yaml").read_bytes()
        == Path(args.calibration).read_bytes(),
        "snapshot_zones_equal_calibration": snap["zones"] == calib.doc["layout"]["zones"],
        "snapshot_calibration_hash": snap["calibration"]["calibration_hash"],
    }
    write(args.session.parent, "session-check.json", result)
    ok = (
        result["calibration"]["calibration_hash"] == calib.hash
        and result["copied_file_identical"]
        and result["snapshot_zones_equal_calibration"]
        and result["snapshot_calibration_hash"] == calib.hash
    )
    print(f"[p14] session {'PASS' if ok else 'FAIL'}: {result['calibration']['calibration_status']}")
    return 0 if ok else 1


def metadata(args: argparse.Namespace) -> int:
    from spacedrums.calib import load_calibration
    from spacedrums.data.metadata import validate_metadata

    calib = load_calibration(args.calibration)
    files = sorted(Path(args.root).rglob("metadata.json"))
    meta = json.loads(files[0].read_text(encoding="utf-8"))
    errors = validate_metadata(meta)
    result = {
        "metadata": str(files[0]),
        "errors": errors,
        **{k: meta.get(k) for k in ("calibration_status", "calibration_hash", "calibration_id")},
    }
    write(Path(args.root), "metadata-check.json", result)
    ok = (
        not errors
        and meta.get("calibration_hash") == calib.hash
        and meta.get("calibration_status") == "CALIBRATED"
    )
    print(f"[p14] metadata {'PASS' if ok else 'FAIL'}: calibration_hash recorded={ok}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("check", choices=("regression", "model-compat", "session", "metadata"))
    ap.add_argument("--out", type=Path)
    ap.add_argument("--calibration", type=Path)
    ap.add_argument("--session", type=Path)
    ap.add_argument("--root", type=Path)
    args = ap.parse_args(argv)
    return {"regression": regression, "model-compat": model_compat, "session": session, "metadata": metadata}[
        args.check
    ](args)


if __name__ == "__main__":
    sys.exit(main())
