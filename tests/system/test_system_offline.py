"""TEST-SYS-OFFLINE-1/2: the application runs fully offline (REQ-052, REQ-209; Phase 17 gap closure).

1. Static: no module of ``src/spacedrums`` imports a networking library (the model/asset fetch
   helpers live in ``scripts/`` and are one-off developer tools, never imported by the package).
2. Runtime: a complete application session (SYNTHETIC source, decision pipeline, invariant and
   health monitors, event log) runs with socket creation and DNS resolution blocked.
"""

from __future__ import annotations

import ast
import socket

import pytest
from inv_helpers import ROOT, RULE_CONFIG

from spacedrums.app import main as app_main

NETWORK_MODULES = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "urllib3",
    "requests",
    "httpx",
    "aiohttp",
    "ftplib",
    "smtplib",
    "websocket",
    "websockets",
    "grpc",
    "paramiko",
}


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module.split(".")[0]


def test_package_imports_no_network_library():
    offenders = {
        str(p.relative_to(ROOT)): sorted(set(_imports(p)) & NETWORK_MODULES)
        for p in (ROOT / "src" / "spacedrums").rglob("*.py")
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert offenders == {}


def test_session_runs_with_network_blocked(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("network access attempted during an application session")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    args = app_main.build_parser().parse_args(
        [
            "--config",
            str(RULE_CONFIG),
            "--no-window",
            "--no-audio",
            "--synthetic",
            "repeated",
            "--invariants",
            "raise",
        ]
    )
    summary = app_main.run(args)
    assert summary["frames"] > 0 and summary["counters"]["invariants"]["violations_total"] == 0


@pytest.mark.parametrize(
    "module", ["spacedrums.app.main", "spacedrums.app.arms", "spacedrums.hands.landmarker"]
)
def test_runtime_modules_resolve_assets_locally(module):
    """Model and asset paths are local files (hash-pinned); nothing is downloaded at runtime."""
    import importlib

    source = importlib.util.find_spec(module).origin
    text = open(source, encoding="utf-8").read()
    assert "http://" not in text and "https://" not in text
