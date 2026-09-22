"""TEST-ARCH-1: the allowed-dependency layers (architecture.md section 2.2) hold.

Two checks: (1) import-linter with the committed `.importlinter` contract (the mechanical rule
of section 2.4; skipped with a visible reason if the tool is absent); (2) an independent AST
scan of every `spacedrums` module against the layer table, so the rule is verified even where
import-linter cannot express it (optional layers, packages that do not exist yet).
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "spacedrums"

# layer index per package: a module may import packages with index <= its own, except that
# peers in the same layer may not import each other unless listed in SAME_LAYER_ALLOWED.
LAYERS: dict[str, int] = {
    "contracts": 0,
    "timing": 1,
    "config": 1,
    "capture": 2,
    "hands": 3,
    "stick": 4,
    "tracking": 5,
    "features": 6,
    "geometry": 6,
    "prediction": 7,
    "models": 7,
    "commit": 8,
    "audio": 8,
    "ui": 9,
    "eval": 9,
    "data": 9,
    "calib": 9,
    "app": 10,
}
SAME_LAYER_ALLOWED = {("features", "geometry")}  # read-only zone access (section 2.2)
FORBIDDEN = {
    ("prediction", "geometry"),
    ("models", "geometry"),
    ("commit", "hands"),
    ("commit", "stick"),
    ("commit", "prediction"),
    ("commit", "features"),
    ("audio", "capture"),
}


def _package_of(module_path: Path) -> str:
    rel = module_path.relative_to(SRC)
    return rel.parts[0] if len(rel.parts) > 1 else "__root__"


def _imported_packages(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pkgs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("spacedrums."):
                    pkgs.add(alias.name.split(".")[1])
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("spacedrums"):
            parts = node.module.split(".")
            if len(parts) > 1:
                pkgs.add(parts[1])
            else:  # `from spacedrums import timing`
                for alias in node.names:
                    pkgs.add(alias.name)
    return pkgs


def test_layer_table_by_ast():
    violations = []
    for path in SRC.rglob("*.py"):
        pkg = _package_of(path)
        if pkg == "__root__" or pkg not in LAYERS:
            continue
        for target in _imported_packages(path):
            if target == pkg or target not in LAYERS:
                continue
            if (pkg, target) in FORBIDDEN:
                violations.append(f"{path.relative_to(ROOT)}: {pkg} -> {target} (forbidden)")
            elif LAYERS[target] > LAYERS[pkg]:
                violations.append(f"{path.relative_to(ROOT)}: {pkg} -> {target} (upward)")
            elif LAYERS[target] == LAYERS[pkg] and (pkg, target) not in SAME_LAYER_ALLOWED:
                violations.append(f"{path.relative_to(ROOT)}: {pkg} -> {target} (sideways)")
    assert not violations, "\n".join(violations)


def test_contracts_is_a_leaf():
    for path in (SRC / "contracts").rglob("*.py"):
        assert _imported_packages(path) <= {"contracts"}, path


def test_import_linter_contract():
    exe = shutil.which("lint-imports", path=str(Path(sys.executable).parent))
    if exe is None:
        pytest.skip("import-linter not installed in this environment (requirements.lock has it)")
    # utf-8 decode: with PYTHONIOENCODING=utf-8 in the environment, import-linter (rich) prints a
    # UTF-8 banner that the Windows console codepage (cp1252) cannot decode (Phase 03 finding).
    res = subprocess.run(
        [exe, "--config", str(ROOT / ".importlinter")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "0 broken" in res.stdout
