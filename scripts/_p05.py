"""Shared helpers for the Phase 05 scripts (playability protocol, induced-loss test, summaries, sweep).

Runs the prototype's decision pipeline through ``spacedrums.app.main.run`` (the same code path as the
live application) and packages the results into experiment runs (``_runlog.RunLog``). Everything
produced from ``--synthetic`` modes is labelled SYNTHETIC; nothing here creates a recording.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _runlog import ROOT  # noqa: E402

from spacedrums.app.main import build_parser, run  # noqa: E402

DEFAULT_CONFIG = ROOT / "configs" / "prototype.candidate.yaml"


def run_synthetic_session(
    scenario: str,
    *,
    out_dir: Path,
    session_id: str,
    active: str = "A",
    shadow: tuple[str, ...] = ("B",),
    config: Path = DEFAULT_CONFIG,
    extra_args: list[str] | None = None,
    on_frame=None,
) -> dict[str, Any]:
    """One SYNTHETIC scenario through the app in record mode; returns ``run``'s summary (with session dir)."""
    argv = [
        "--config",
        str(config),
        "--synthetic",
        scenario,
        "--record",
        "--no-window",
        "--no-audio",
        "--output-dir",
        str(out_dir),
        "--session-id",
        session_id,
        "--arm",
        active,
        "--shadow",
        *shadow,
    ]
    args = build_parser().parse_args(argv + (extra_args or []))
    return run(args, on_frame=on_frame)


def hit_type_table(evaluations: dict[str, dict[str, Any]]) -> list[str]:
    """Markdown rows: per scenario, per arm: truth / committed / matched / FP / FN / dup / lead time."""
    lines = [
        "| Scenario (SYNTHETIC) | Arm | truth | commits | matched | FP | FN | dup | zone acc | "
        "L_pred median s | TE median s |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, ev in evaluations.items():
        for arm, a in sorted(ev["arms"].items()):
            lp = a["L_pred_s"]["median_s"]
            te = a["TE_s"]["median_s"]
            lines.append(
                f"| {name} | {arm} | {ev['n_truth']} | {a['n_commits']} | {a['n_matched']} | "
                f"{a['false_positives']} | "
                f"{a['false_negatives']} | {a['duplicates']} | {a['zone_accuracy']} | "
                f"{'n/a' if lp is None else f'{lp:+.4f}'} | {'n/a' if te is None else f'{te:+.4f}'} |"
            )
        if not ev["arms"]:
            lines.append(
                f"| {name} | - | {ev['n_truth']} | 0 | 0 | 0 | {ev['n_truth']} | 0 | n/a | n/a | n/a |"
            )
    return lines


__all__ = ["DEFAULT_CONFIG", "ROOT", "hit_type_table", "run_synthetic_session"]
