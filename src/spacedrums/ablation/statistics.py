"""Paired participant analysis with folds/seeds aggregated before resampling."""

import math
from collections import defaultdict

import numpy as np

from spacedrums.live_eval.stats import bootstrap_mean


def _index(rows):
    result = {}
    for row in rows:
        key = (row["participant"], row["fold"], row["seed"])
        if key in result:
            raise ValueError("duplicate participant/fold/seed result")
        value = row["value"]
        if value is not None and not math.isfinite(value):
            raise ValueError("nonfinite metric")
        result[key] = value
    return result


def seed_band(reference, *, multiplier=2.0):
    """2 * pooled within-fold SD of seed-level participant-macro reference lead.

    Use complete support across every seed in a fold. Missing feasibility leaves the band
    undefined, so it cannot support a materiality decision.
    """
    cells = _index(reference)
    folds = defaultdict(lambda: defaultdict(dict))
    for (participant, fold, seed), value in cells.items():
        folds[fold][seed][participant] = value
    if not folds or multiplier <= 0 or not math.isfinite(multiplier):
        return None
    ss, df = 0.0, 0
    for seeds in folds.values():
        support = [set(v) for v in seeds.values()]
        if (
            len(seeds) < 2
            or any(s != support[0] for s in support)
            or any(v is None for values in seeds.values() for v in values.values())
        ):
            return None
        means = np.array([np.mean(list(v.values())) for _, v in sorted(seeds.items())])
        ss += float(((means - means.mean()) ** 2).sum())
        df += len(means) - 1
    return multiplier * math.sqrt(ss / df)


def compare(reference, variant, *, repeats=10000, seed=19, band=None, primary=True):
    ref, var = _index(reference), _index(variant)
    if ref.keys() != var.keys():
        raise ValueError("paired comparison requires identical participant/fold/seed keys")
    grouped, missing = defaultdict(list), []
    for key in sorted(ref):
        if ref[key] is None or var[key] is None:
            missing.append(list(key))
        else:
            grouped[key[0]].append(var[key] - ref[key])
    # Partial seed support is reported, never silently compared with a different seed set.
    incomplete = {key[0] for key in missing}
    values = {p: float(np.mean(v)) for p, v in grouped.items() if p not in incomplete}
    stats = bootstrap_mean(values, repeats=repeats, seed=seed)
    if band is not None and (not math.isfinite(band) or band < 0):
        raise ValueError("seed band must be finite and nonnegative")
    ci, estimate = stats["ci"], stats["estimate"]
    decision = "INSUFFICIENT_SUPPORT"
    if not primary:
        decision = "DESCRIPTIVE_SECONDARY"
    elif ci is not None and band is not None:
        material = abs(estimate) > band and (ci[0] > 0 or ci[1] < 0)
        decision = "MATERIAL" if material else "NO_MATERIAL_EFFECT"
    return {
        **stats,
        "difference": "variant minus reference",
        "missing_cells": missing,
        "excluded_incomplete_participants": sorted(incomplete),
        "seed_band": band,
        "interpretation": decision,
        "direction": None
        if estimate is None
        else ("higher" if estimate > 0 else "lower" if estimate < 0 else "equal"),
        "multiplicity": "unadjusted intervals; descriptive ablations; no p-values",
    }
