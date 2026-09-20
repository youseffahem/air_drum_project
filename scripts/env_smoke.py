"""Phase 00 environment smoke check (Task 00.3 / Tests section).

This is an ENVIRONMENT CHECK, not project implementation. It:
  1. imports every pinned candidate library and prints its version;
  2. validates schemas/experiment-log.schema.json against the valid example
     and confirms that a record missing `dataset_version` is rejected.

Exit code 0 = all checks passed. Any failure is printed and exits non-zero.
It performs no camera capture, tracking, audio playback, or ML.
"""
from __future__ import annotations

import copy
import importlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (import name, distribution name shown in requirements.in)
LIBRARIES = [
    ("numpy", "numpy"),
    ("scipy", "scipy"),
    ("cv2", "opencv-python"),
    ("mediapipe", "mediapipe"),
    ("torch", "torch (CPU)"),
    ("onnxruntime", "onnxruntime"),
    ("lightgbm", "lightgbm"),
    ("sounddevice", "sounddevice"),
    ("soundfile", "soundfile"),
    ("pydantic", "pydantic"),
    ("yaml", "PyYAML"),
    ("jsonschema", "jsonschema"),
    ("pytest", "pytest"),
]


def check_imports() -> bool:
    ok = True
    print(f"python      {platform.python_version()}  ({sys.executable})")
    print(f"platform    {platform.platform()}")
    for module, dist in LIBRARIES:
        try:
            importlib.import_module(module)
            version = importlib.metadata.version(dist.split(" ")[0])
            print(f"OK   {dist:<16} {version}")
        except Exception as exc:  # noqa: BLE001 - report every failure
            ok = False
            print(f"FAIL {dist:<16} {type(exc).__name__}: {exc}")
    # Extra facts that matter for a CPU-first project; informational only.
    try:
        import torch

        print(f"     torch.cuda.is_available() = {torch.cuda.is_available()} (expected False: CPU build)")
        print(f"     torch threads = {torch.get_num_threads()}")
    except Exception:  # noqa: BLE001
        pass
    try:
        import onnxruntime as ort

        print(f"     onnxruntime providers = {ort.get_available_providers()}")
    except Exception:  # noqa: BLE001
        pass
    return ok


def check_schema() -> bool:
    import jsonschema

    schema_path = ROOT / "schemas" / "experiment-log.schema.json"
    example_path = ROOT / "schemas" / "examples" / "experiment-log.valid.example.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    example = json.loads(example_path.read_text(encoding="utf-8"))
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema, format_checker=jsonschema.FormatChecker())

    ok = True
    errors = list(validator.iter_errors(example))
    if errors:
        ok = False
        print("FAIL schema: valid example was rejected:")
        for e in errors:
            print(f"     - {list(e.absolute_path)}: {e.message}")
    else:
        print("OK   schema: valid example accepted")

    broken = copy.deepcopy(example)
    del broken["dataset_version"]
    errors = list(validator.iter_errors(broken))
    if errors and any("dataset_version" in e.message for e in errors):
        print("OK   schema: record missing dataset_version rejected")
    else:
        ok = False
        print("FAIL schema: record missing dataset_version was NOT rejected")
    return ok


def main() -> int:
    imports_ok = check_imports()
    schema_ok = check_schema()
    print()
    print("RESULT:", "PASS" if (imports_ok and schema_ok) else "FAIL")
    return 0 if (imports_ok and schema_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
