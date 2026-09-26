"""Apply the pre-declared Phase 12 go/no-go rule (docs/experiments/phase-12-prereg.md) mechanically.

Inputs: one completed reference run, completed extension runs, the isolated latency run and the E3
feasibility run. Per variant and family: feasibility count, paired lead/timing differences against
the same-family reference (same fold and seed; per fold for the seed ensemble; both families for
the Tiny Transformer), the reference seed-variance band, and the CPU criterion. On SYNTHETIC runs
the outcome is labelled a development verdict, never an adoption decision.
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
from _p10 import hardware, provenance, source_hashes, write_json
from _p12 import BAND_SIGMAS, F_CPU, NOT_CODEX, RULES, dev_pick, load_run_rows, predeclaration_record
from _runlog import RunLog

from spacedrums.config import load_config

ROOT = Path(__file__).resolve().parents[1]
LEAD = ("harness", "median_lead_s")
TIMING = ("harness", "timing_mae_s")


def get(tree, path):
    for key in path:
        if not isinstance(tree, dict):
            return None
        tree = tree.get(key)
    return tree


def finite(value):
    return value is not None and isinstance(value, (int, float)) and math.isfinite(value)


def band(rows, path):
    """Pooled within-fold seed SD of a metric over reference rows; complete = every fold has >= 2."""
    per_fold = {}
    for row in rows:
        per_fold.setdefault(row["fold"], [])
        if finite(get(row, path)):
            per_fold[row["fold"]].append(get(row, path))
    sds = [float(np.std(v, ddof=1)) for v in per_fold.values() if len(v) > 1]
    complete = bool(per_fold) and all(len(v) > 1 for v in per_fold.values())
    return (float(np.sqrt(np.mean(np.square(sds)))) if sds else None), complete


def paired(variant_rows, reference_rows, path, *, ensemble):
    """Variant minus reference on cells where both have a value (same fold [and seed])."""
    if ensemble:
        reference = {}
        for row in reference_rows:
            if finite(get(row, path)):
                reference.setdefault(row["fold"], []).append(get(row, path))
        pairs = [
            (get(r, path), float(np.mean(reference[r["fold"]])))
            for r in variant_rows
            if finite(get(r, path)) and reference.get(r["fold"])
        ]
    else:
        reference = {(r["fold"], r["seed"]): get(r, path) for r in reference_rows}
        pairs = [
            (get(r, path), reference[(r["fold"], r["seed"])])
            for r in variant_rows
            if finite(get(r, path)) and finite(reference.get((r["fold"], r["seed"])))
        ]
    deltas = [a - b for a, b in pairs]
    return {
        "n": len(deltas),
        "mean": float(np.mean(deltas)) if deltas else None,
        "sd": float(np.std(deltas, ddof=1)) if len(deltas) > 1 else None,
    }


def verdict(variant, family, rows, reference_rows, latency, *, delta_te=0.0):
    ensemble = variant == "e4-ens3"
    feasible = sum(bool(get(r, ("harness", "feasible"))) for r in rows)
    reference_feasible = sum(bool(get(r, ("harness", "feasible"))) for r in reference_rows)
    if ensemble:  # one ensemble per fold: compare with the number of folds with a feasible seed
        reference_feasible = len({r["fold"] for r in reference_rows if get(r, ("harness", "feasible"))})
    lead_band, lead_complete = band(reference_rows, LEAD)
    timing_band, _ = band(reference_rows, TIMING)
    lead = paired(rows, reference_rows, LEAD, ensemble=ensemble)
    timing = paired(rows, reference_rows, TIMING, ensemble=ensemble)
    checks = {
        "feasibility": feasible >= reference_feasible and feasible > 0,
        "lead": bool(
            lead_complete
            and lead_band is not None
            and lead["mean"] is not None
            and lead["mean"] > BAND_SIGMAS * lead_band
        ),
        "timing": bool(
            timing["mean"] is not None and timing["mean"] <= max(BAND_SIGMAS * (timing_band or 0.0), delta_te)
        ),
        "cpu": None if latency is None else bool(latency["within_budget"]),
    }
    if not lead_complete or lead_band is None:
        outcome = "NO-GO (insufficient evidence)"
    elif all(checks[k] for k in ("feasibility", "lead", "timing")) and checks["cpu"] is True:
        outcome = "GO"
    else:
        outcome = "NO-GO"
    return {
        "variant": variant,
        "family": family,
        "cells": len(rows),
        "feasible_cells": feasible,
        "reference_feasible_cells": reference_feasible,
        "lead_paired_delta_s": lead,
        "lead_band_s": None if lead_band is None else BAND_SIGMAS * lead_band,
        "lead_band_complete": lead_complete,
        "timing_paired_delta_s": timing,
        "timing_band_s": None if timing_band is None else BAND_SIGMAS * timing_band,
        "delta_te_s": delta_te,
        "cpu": latency,
        "checks": checks,
        "outcome": outcome,
    }


def secondary(rows):
    """Reported, never deciding: trajectory error, FP/FN, zone accuracy, calibration."""

    def mean(path):
        values = [get(r, path) for r in rows if finite(get(r, path))]
        return {"n": len(values), "mean": float(np.mean(values)) if values else None}

    return {
        "ade": mean(("validation", "trajectory", "ade")),
        "fde": mean(("validation", "trajectory", "fde")),
        "macro_ade": mean(("validation", "trajectory", "participant_macro_ade")),
        "dev_fp_per_min": mean(("harness", "fp_per_min")),
        "dev_fn_rate": mean(("harness", "fn_rate")),
        "dev_zone_accuracy": mean(("harness", "zone_accuracy")),
        "ece": mean(("calibration", "ece")),
        "brier": mean(("calibration", "brier")),
        "roc_auc": mean(("calibration", "roc_auc")),
        "best_of_m_ade": mean(("validation", "trajectory", "mixture", "best_of_m_ade")),
        "most_probable_ade": mean(("validation", "trajectory", "mixture", "most_probable_ade")),
    }


def table(results):
    lines = [
        "| Variant | Family (vs ref) | Feasible cells (ref) | Paired Δ lead ms (n) | Band ms | "
        "Paired Δ TE MAE ms | CPU path p95 ratio | Checks F/L/T/C | Development verdict |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    def ms(value, signed=True):
        if value is None:
            return "—"
        return f"{1000 * value:+.1f}" if signed else f"{1000 * value:.1f}"

    marks = {True: "Y", False: "N", None: "–"}
    for r in results:
        cpu = "—" if r["cpu"] is None else "{:.2f}".format(r["cpu"]["ratio_to_reference"])
        checks = "/".join(marks[r["checks"][k]] for k in ("feasibility", "lead", "timing", "cpu"))
        lead = r["lead_paired_delta_s"]
        cells = [
            r["variant"],
            "{} ({})".format(r["family"], r["reference_family"]),
            "{}/{} ({})".format(r["feasible_cells"], r["cells"], r["reference_feasible_cells"]),
            "{} ({})".format(ms(lead["mean"]), lead["n"]),
            ms(r["lead_band_s"], signed=False),
            ms(r["timing_paired_delta_s"]["mean"]),
            cpu,
            checks,
            r["outcome"],
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


# Figure tokens (validated categorical slots 1-3, light mode; reference in neutral gray).
SURFACE, INK, MUTED, GRID, REFERENCE_GRAY = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1", "#8a8984"
SERIES = ("#2a78d6", "#eb6834", "#1baf7a")


def _figure(rows, cols, *, width=3.6, height=3.0):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(
        rows, cols, figsize=(width * cols, height * rows), squeeze=False, layout="constrained"
    )
    fig.patch.set_facecolor(SURFACE)
    for ax in axes.flat:
        ax.set_facecolor(SURFACE)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(GRID)
        ax.grid(True, color=GRID, linewidth=0.8, linestyle="-")
        ax.set_axisbelow(True)
        ax.tick_params(colors=MUTED, labelsize=8)
    return plt, fig, axes


def _save(plt, fig, path, title):
    fig.suptitle(title, color=INK, fontsize=10)
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def plot_lead_fp_panels(reference_points, points, variants, path, title):
    """Small multiples: one panel per family x variant, the family's reference in gray behind it."""
    families = [f for f in ("gru", "tcn", "tt") if any(p["settings"]["family"] == f for p in points)]
    if not families or not variants:
        return None
    plt, fig, axes = _figure(len(families), len(variants))
    for i, family in enumerate(families):
        for j, variant in enumerate(variants):
            ax = axes[i][j]
            own = [p for p in points if p["variant"] == variant and p["settings"]["family"] == family]
            ref_families = ("gru", "tcn") if family == "tt" else (family,)
            ref = [p for p in reference_points if p["settings"]["family"] in ref_families]
            for group, color, label in ((ref, REFERENCE_GRAY, "reference"), (own, SERIES[0], variant)):
                xy = [
                    (p["fp_per_min"], 1000 * p["median_lead_s"])
                    for p in group
                    if p["median_lead_s"] is not None
                ]
                if xy:
                    ax.scatter(*zip(*xy, strict=True), s=22, color=color, edgecolors=SURFACE, linewidths=0.8,
                               label=label, alpha=0.85)  # fmt: skip
            ax.axvline(30.0, color=MUTED, linewidth=0.8)  # development FP budget
            ax.set_title(f"{variant} / {family}", color=INK, fontsize=9)
            ax.set_xlabel("FP per active minute", color=MUTED, fontsize=8)
            ax.set_ylabel("Median lead (ms)", color=MUTED, fontsize=8)
            if not own:
                ax.text(0.5, 0.5, "no matched points", ha="center", va="center", transform=ax.transAxes,
                        color=MUTED, fontsize=8)  # fmt: skip
            ax.legend(fontsize=7, frameon=False, labelcolor=INK)
    _save(plt, fig, path, title + "\n(vertical line: SYNTHETIC development FP budget, 30 per minute)")
    return str(path)


def _pooled_bins(rows):
    totals = {}
    for row in rows:
        for b in get(row, ("calibration", "bins")) or []:
            if b["n"]:
                t = totals.setdefault(b["lower"], [0, 0.0, 0.0])
                t[0] += b["n"]
                t[1] += b["n"] * b["mean_probability"]
                t[2] += b["n"] * b["observed_rate"]
    return [(t[1] / t[0], t[2] / t[0], t[0]) for _, t in sorted(totals.items())]


def plot_reliability(reference_rows, rows, variants, path):
    families = [f for f in ("gru", "tcn") if any(r["family"] == f for r in rows)]
    if not families:
        return None
    plt, fig, axes = _figure(1, len(families), width=3.8, height=3.4)
    for ax, family in zip(axes[0], families, strict=True):
        ax.plot([0, 1], [0, 1], color=MUTED, linewidth=0.8)
        series = [
            (
                "reference (0/1 indicator)",
                REFERENCE_GRAY,
                [r for r in reference_rows if r["family"] == family],
            )
        ]
        series += [
            (variant, SERIES[k], [r for r in rows if r["variant"] == variant and r["family"] == family])
            for k, variant in enumerate(variants)
        ]
        for label, color, group in series:
            pooled = _pooled_bins(group)
            if pooled:
                x, y, _ = zip(*pooled, strict=True)
                # A 0/1 indicator has two bins only: markers, no line implying intermediate calibration.
                style = "none" if group is series[0][2] else "-"
                ax.plot(x, y, color=color, linewidth=2, linestyle=style, marker="o", markersize=6,
                        markeredgecolor=SURFACE, label=label)  # fmt: skip
        ax.set(xlim=(0, 1), ylim=(0, 1))
        ax.set_title(f"{family}: crossing probability vs strike within H", color=INK, fontsize=9)
        ax.set_xlabel("Mean predicted probability (bin)", color=MUTED, fontsize=8)
        ax.set_ylabel("Observed strike rate", color=MUTED, fontsize=8)
        ax.legend(fontsize=7, frameon=False, labelcolor=INK)
    _save(plt, fig, path, "SYNTHETIC development calibration (pooled over folds and seeds)")
    return str(path)


def plot_error_growth(reference_rows, rows, variants, path):
    families = [f for f in ("gru", "tcn") if any(r["family"] == f for r in rows)]
    if not families:
        return None
    plt, fig, axes = _figure(1, len(families), width=3.8, height=3.2)

    def curve(group):
        by = {}
        for row in group:
            trajectory = row["validation"]["trajectory"]
            steps = trajectory.get("error_by_offset") or [
                {"offset_s": s["step"] / 30, "error": s["error"]} for s in trajectory["by_step"]
            ]
            for s in steps:
                if s["error"] is not None:
                    by.setdefault(round(s["offset_s"], 6), []).append(s["error"])
        return sorted((1000 * t, float(np.mean(v))) for t, v in by.items())

    for ax, family in zip(axes[0], families, strict=True):
        series = [("reference K=4", REFERENCE_GRAY, [r for r in reference_rows if r["family"] == family])]
        series += [
            (variant, SERIES[k], [r for r in rows if r["variant"] == variant and r["family"] == family])
            for k, variant in enumerate(variants)
        ]
        for label, color, group in series:
            points = curve(group)
            if points:
                ax.plot(*zip(*points, strict=True), color=color, linewidth=2, marker="o", markersize=5,
                        markeredgecolor=SURFACE, label=label)  # fmt: skip
        ax.set_title(f"{family}: displacement error by horizon", color=INK, fontsize=9)
        ax.set_xlabel("Prediction offset (ms)", color=MUTED, fontsize=8)
        ax.set_ylabel("Mean error (ROI units)", color=MUTED, fontsize=8)
        ax.legend(fontsize=7, frameon=False, labelcolor=INK)
    _save(plt, fig, path, "SYNTHETIC development E1: error growth with horizon (validation windows)")
    return str(path)


def gate_effect(sources):
    """Reported only: per probabilistic cell, the development pick with the p_commit gate available
    versus the gate-off subset (p_commit = 0) of the same curve."""
    out = {}
    for source in sources.values():
        points = json.loads((Path(source) / "curves.json").read_text(encoding="utf-8"))
        cells = {}
        for p in points:
            if p["settings"].get("gate"):
                key = (p["variant"], p["settings"]["family"], p["settings"].get("seed"), p["participant"])
                cells.setdefault(key, []).append(p)
        for (variant, family, _, _), group in sorted(cells.items(), key=lambda item: str(item[0])):
            entry = out.setdefault(f"{variant}/{family}", {"cells": 0, "pairs": []})
            entry["cells"] += 1
            with_gate = dev_pick(group)
            gate_off = dev_pick([p for p in group if p["settings"]["p_commit"] == 0.0])
            entry["pairs"].append(
                {
                    "with_gate": {
                        k: with_gate[k] for k in ("feasible", "median_lead_s", "fp_per_min", "fn_rate")
                    },
                    "gate_off": {
                        k: gate_off[k] for k in ("feasible", "median_lead_s", "fp_per_min", "fn_rate")
                    },
                    "selected_p_commit": (with_gate["settings"] or {}).get("p_commit"),
                }
            )
    for entry in out.values():
        pairs = entry["pairs"]
        both = [p for p in pairs if p["with_gate"]["feasible"] and p["gate_off"]["feasible"]]
        entry["feasible_with_gate"] = sum(p["with_gate"]["feasible"] for p in pairs)
        entry["feasible_gate_off"] = sum(p["gate_off"]["feasible"] for p in pairs)
        entry["gate_selected"] = sum(
            (p["selected_p_commit"] or 0) > 0 for p in pairs if p["with_gate"]["feasible"]
        )
        entry["mean_lead_gain_s_both_feasible"] = (
            float(np.mean([p["with_gate"]["median_lead_s"] - p["gate_off"]["median_lead_s"] for p in both]))
            if both
            else None
        )
    return out


def figures(run_dir, reference_run, sources, reference, rows):
    reference_points = json.loads((Path(reference_run) / "curves.json").read_text(encoding="utf-8"))
    made = {}
    for extension, source in sorted(sources.items()):
        points = json.loads((Path(source) / "curves.json").read_text(encoding="utf-8"))
        variants = sorted({p["variant"] for p in points})
        made[f"lead-vs-fp-{extension}"] = plot_lead_fp_panels(
            reference_points,
            points,
            variants,
            run_dir / f"lead-vs-fp-{extension}.png",
            f"SYNTHETIC development {extension.upper()}: lead vs FP per operating point",
        )
    probabilistic = [
        v for v in ("e4-gauss", "e4-ens3", "e2-mix2-agg") if any(r["variant"] == v for r in rows)
    ]
    made["reliability"] = plot_reliability(reference, rows, probabilistic, run_dir / "reliability.png")
    e1 = [v for v in ("e1-k6", "e1-k8", "e1-2rate") if any(r["variant"] == v for r in rows)]
    if e1:
        made["e1-error-growth"] = plot_error_growth(reference, rows, e1, run_dir / "e1-error-growth.png")
    return made


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reference-run", type=Path, required=True)
    ap.add_argument("--runs", type=Path, nargs="+", required=True)
    ap.add_argument("--latency-run", type=Path, required=True)
    ap.add_argument("--feasibility-run", type=Path, required=True)
    ap.add_argument("--output", type=Path, default=ROOT / "experiments/phase-12")
    args = ap.parse_args()
    _, reference = load_run_rows(args.reference_run, extension="ref")
    rows, sources = [], {}
    for run_dir in args.runs:
        plan, run_rows = load_run_rows(run_dir)
        rows.extend(run_rows)
        sources[plan["extension"]] = str(run_dir)
    if any(r["source_kind"] != "SYNTHETIC" for r in reference + rows):
        raise SystemExit("participant comparisons are PENDING; this development tool refuses them")
    latency = json.loads((args.latency_run / "latency-memory.json").read_text(encoding="utf-8"))
    feasibility = json.loads((args.feasibility_run / "feasibility.json").read_text(encoding="utf-8"))
    cfg = load_config(ROOT / "configs/prototype.candidate.yaml")
    with RunLog(
        phase="12",
        task="12.2",
        slug="synthetic-go-no-go",
        config=cfg,
        experiments_dir=args.output,
        description="Mechanical application of the pre-declared go/no-go rule to SYNTHETIC development runs",
    ) as run:
        context = {**provenance(), "hardware": hardware(), **NOT_CODEX}
        write_json(run.dir / "execution.json", context)
        write_json(run.dir / "source-hashes.json", source_hashes())
        results = []
        for variant in sorted({r["variant"] for r in rows}):
            for family in ("gru", "tcn", "tt"):
                cells = [r for r in rows if r["variant"] == variant and r["family"] == family]
                if not cells:
                    continue
                families = ("gru", "tcn") if family == "tt" else (family,)
                for reference_family in families:
                    ref_rows = [r for r in reference if r["family"] == reference_family]
                    cpu = get(latency, (f"{variant}/{family}", "cpu_rule"))
                    result = verdict(variant, family, cells, ref_rows, cpu)
                    result["reference_family"] = reference_family
                    result["secondary"] = secondary(cells)
                    result["reference_secondary"] = secondary(ref_rows)
                    result["rule_of"] = RULES.get(variant, {}).get("source")
                    results.append(result)
        summary = {
            "label": "development verdict (SYNTHETIC; not an adoption decision)",
            "predeclaration": predeclaration_record(),
            "rule": {
                "band_sigmas": BAND_SIGMAS,
                "cpu_factor": F_CPU,
                "delta_te_s": 0.0,
                "budget": "Phase 11 DEV_BUDGET (FP 30/min, FN 0.6)",
            },
            "e3_feasibility": {k: feasibility[k] for k in ("verdict", "budget_p95_ms", "rule")},
            "reference_run": str(args.reference_run),
            "runs": sources,
            "latency_run": str(args.latency_run),
            "results": results,
            "adopted": [],
            "adoption_note": "No adoption is possible without participant CV folds (PENDING).",
        }
        summary["figures"] = figures(run.dir, args.reference_run, sources, reference, rows)
        summary["gate_effect"] = gate_effect(sources)
        write_json(run.dir / "go-no-go.json", summary)
        (run.dir / "go-no-go.md").write_text(table(results), encoding="utf-8", newline="\n")
        for path in sorted(run.dir.iterdir()):
            if path.is_file() and path.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(path, "other")
        run.finish(
            {"comparisons": len(results), "development_go": sum(r["outcome"] == "GO" for r in results)},
            notes="SYNTHETIC development verdicts; not adoption decisions.",
        )
        for r in results:  # ASCII only: the Windows console code page cannot print the table
            print(f"{r['variant']} {r['family']} vs {r['reference_family']}: {r['outcome']}", flush=True)
        print(run.dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
