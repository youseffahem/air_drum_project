"""TEST-SYS-MATRIX-1: the Phase 17 test matrix is complete and current (Task 17.1).

Every RTM requirement is mapped, every referenced test file exists, every requirement whose RTM
verification asks for a test has one or a written justification, and ``docs/testing/test-matrix.md``
equals what ``scripts/build_test_matrix.py`` generates from the map and the RTM.
"""

from __future__ import annotations

import importlib.util

from inv_helpers import ROOT


def _builder():
    spec = importlib.util.spec_from_file_location(
        "build_test_matrix", ROOT / "scripts" / "build_test_matrix.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_requirement_is_mapped_and_every_file_exists():
    builder = _builder()
    assert builder.problems() == []
    assert len(builder.rtm_rows()) == len(builder.MAP)


def test_matrix_document_is_current():
    builder = _builder()
    assert builder.OUT.read_text(encoding="utf-8") == builder.render()


def test_phase17_requirements_have_failure_injection_or_invariant_tests():
    builder = _builder()
    owned = ("REQ-012", "REQ-027", "REQ-028", "REQ-029", "REQ-034", "REQ-035", "REQ-305")
    for req in owned:
        levels = {builder.level(p) for p in builder.MAP[req]["tests"]}
        assert levels & {"failure_injection", "invariants"}, req
