"""Deterministic, zone-blind, one-to-one event matching within a time tolerance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MatchResult:
    pairs: tuple[tuple[dict[str, Any], dict[str, Any]], ...]
    false_positives: tuple[dict[str, Any], ...]
    false_negatives: tuple[dict[str, Any], ...]


def match_events(strikes: list[dict[str, Any]], labels: list[dict[str, Any]], *, w_s: float) -> MatchResult:
    """Greedily take the closest available time pair per hand, including |dt| == W.

    Zone is intentionally absent from the assignment cost so wrong-zone strikes are
    matched and count against zone accuracy. Session identity is mandatory as well.
    """
    if not 0 <= w_s < float("inf"):
        raise ValueError("w_s must be finite and nonnegative")
    ids_s = [(str(s["session_id"]), str(s["hand_id"])) for s in strikes]
    ids_g = [(str(g["session_id"]), str(g["hand_id"])) for g in labels]
    edges = []
    for i, s in enumerate(strikes):
        for j, g in enumerate(labels):
            if ids_s[i] != ids_g[j]:
                continue
            delta = abs(float(s["t_commit"]) - float(g["t_impact_est"]))
            if delta <= w_s + 1e-12:
                edges.append((round(delta, 12), float(s["t_commit"]), float(g["t_impact_est"]), i, j))
    used_s: set[int] = set()
    used_g: set[int] = set()
    pairs = []
    for _, _, _, i, j in sorted(edges):
        if i not in used_s and j not in used_g:
            used_s.add(i)
            used_g.add(j)
            pairs.append((strikes[i], labels[j]))
    return MatchResult(
        tuple(pairs),
        tuple(s for i, s in enumerate(strikes) if i not in used_s),
        tuple(g for j, g in enumerate(labels) if j not in used_g),
    )


def w_sweep(strikes: list[dict[str, Any]], labels: list[dict[str, Any]], widths: tuple[float, ...]):
    return {str(w): match_events(strikes, labels, w_s=w) for w in widths}
