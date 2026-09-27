"""Phase 18 report rendering: every Experiment 1 table and figure, from ``results.json`` alone.

``render(results, out_dir)`` writes the tables T1-T9 (Markdown) and figures F1-F6 (PNG plus a JSON
file of the plotted data) declared in pre-registration §10, and returns their digests.
``scripts/regenerate_phase18.py`` calls it again on the stored results and compares the digests,
which is the Task 18.9 regeneration check.

Chart conventions (dataviz reference palette, light surface, validated with
``validate_palette.js --pairs all``):

* the three hypothesis arms take the first three categorical slots (C blue ``#2a78d6``, B orange
  ``#eb6834``, A aqua ``#1baf7a``; worst all-pairs CVD ΔE 9.2);
* secondary arms are muted gray with distinct marker shapes, a legend, and direct labels on the
  frozen points;
* one axis per panel, hairline solid grid, text in ink colours;
* aqua is below 3:1 contrast on the surface, so every figure has a table twin (the relief rule).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SLOT = {"C": "#2a78d6", "B": "#eb6834", "A": "#1baf7a"}
MUTED, INK, INK2, GRID, AXIS, SURFACE = "#898781", "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#fcfcfb"
SECONDARY_MARKERS = ("s", "^", "D", "v", "P")
BLUE_RAMP = ("#fcfcfb", "#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#104281")


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _ms(v: float | None, digits: int = 1) -> str:
    return "—" if v is None else f"{1000.0 * v:.{digits}f}"


def _num(v: float | None, digits: int = 3) -> str:
    return "—" if v is None else f"{v:.{digits}f}"


def _ci(stat: Mapping[str, Any] | None, *, ms: bool = False) -> str:
    if not stat or stat.get("ci") is None:
        return "—"
    lo, hi = stat["ci"]
    return f"[{_ms(lo)}, {_ms(hi)}] ms" if ms else f"[{lo:.3f}, {hi:.3f}]"


def roles(results: Mapping[str, Any]) -> dict[str, str]:
    """arm id -> hypothesis role letter (C / B / A) or '' for secondary arms."""
    return {
        arm: (
            "C"
            if arm == results["c_primary"]
            else "B"
            if arm == results["b_primary"]
            else "A"
            if arm == results["a_arm"]
            else ""
        )
        for arm in results["arms"]
    }


def _style(results: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    role = roles(results)
    out, k = {}, 0
    for arm in results["arms"]:
        if role[arm]:
            out[arm] = {"color": SLOT[role[arm]], "marker": "o", "z": 3, "role": role[arm]}
        else:
            out[arm] = {
                "color": MUTED,
                "marker": SECONDARY_MARKERS[k % len(SECONDARY_MARKERS)],
                "z": 2,
                "role": "",
            }
            k += 1
    return out


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def _header(results: Mapping[str, Any], title: str) -> str:
    return (
        f"# {title}\n\n**Evidence: {results['label']}.** "
        f"Lock `{results['lock']['sha256']}`, pre-registration "
        f"v{results['prereg']['version']} `{results['prereg']['sha256']}`, run `{results['run_id']}`. "
        f"W = {_ms(results['w_primary_s'])} ms; test participants P = {results['dataset']['p_test']}.\n\n"
    )


# ----------------------------------------------------------------------------- tables


def _metric_row(arm: str, role: str, m: Mapping[str, Any], delay: float | None) -> str:
    iqr = None if m["lead_q1_s"] is None else m["lead_q3_s"] - m["lead_q1_s"]
    return (
        f"| {arm} | {role or 'secondary'} | {_ms(delay)} | {m['matched']} | {m['fp']} | {m['fn']} | "
        f"{_num(m['fp_per_min'], 2)} | {_num(m['fn_rate'])} | {_ms(m['lead_median_s'])} | {_ms(iqr)} | "
        f"{_num(m['lead_positive_fraction'])} | {_ms(m['te_pred_mae_s'])} | {_ms(m['te_pred_bias_s'])} | "
        f"{_num(m['zone_accuracy'])} | {_num(m['impact_position_error_median'], 4)} | "
        f"{_num(m['intensity_spearman_rho'])} |\n"
    )


METRIC_HEAD = (
    "| Arm | Role | Δ_proc (ms) | Matched | FP | FN | FP/min | FN rate | Lead median (ms) | Lead IQR (ms) | "
    "Lead > 0 | TE_pred MAE (ms) | TE_pred bias (ms) | Zone acc. | Impact pos. err. (ROI) | Intensity ρ |\n"
    "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
)


def tables(results: Mapping[str, Any]) -> dict[str, str]:
    role = roles(results)
    arms = results["arms"]
    t: dict[str, str] = {}
    body = "".join(
        _metric_row(a, role[a], arms[a]["primary"]["pooled"], arms[a]["delay_primary_s"]) for a in arms
    )
    t["T1-pooled"] = _header(results, "T1 — Per-arm pooled metrics (primary Δ_proc)") + METRIC_HEAD + body
    rows = []
    for a in arms:
        for p, m in arms[a]["primary"]["per_participant"].items():
            rows.append(
                f"| {a} | {p} | {m['sessions']} | {m['matched']} | {m['fp']} | {m['fn']} | "
                f"{_num(m['fp_per_min'], 2)} | "
                f"{_ms(m['lead_median_s'])} | {_ms(m['te_pred_mae_s'])} | {_num(m['zone_accuracy'])} |\n"
            )
    t["T2-participants"] = (
        _header(results, "T2 — Per-participant metrics per arm (primary Δ_proc)")
        + "| Arm | Participant | Sessions | Matched | FP | FN | FP/min | Lead median (ms) | "
        + "TE_pred MAE (ms) | Zone acc. |\n"
        + "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|\n"
        + "".join(rows)
    )
    s1 = {h["id"]: h for h in results["sensitivity_s1"]}
    hrows = []
    for h in results["hypotheses"]:
        ms = h["id"] in ("H1a", "H1b", "CB", "H3", "H4", "H4-B")
        est = h.get("estimate")
        est_txt = (_ms(est) + " ms" if ms else _num(est, 2)) if est is not None else "—"
        other = s1.get(h["id"], {})
        hrows.append(
            f"| {h['id']} | **{h['decision']}** | {est_txt} | {_ci(h, ms=ms)} | "
            f"{h.get('n') if h.get('n') is not None else '—'} | "
            f"{other.get('decision', '—')} | {h['reading']} |\n"
        )
    t["T3-hypotheses"] = (
        _header(results, "T3 — Hypothesis outcomes (pre-registration §3)")
        + "| Id | Decision (primary) | Estimate | 95 % CI | P | Decision under S1 | Reading |\n"
        + "|---|---|---:|---|---:|---|---|\n"
        + "".join(hrows)
        + "\nA P ≤ 3 interval spans the participant values (per-participant consistency, not a population "
        "inference; pre-registration §6).\n"
    )
    prow = []
    for name, metrics in results["paired"].items():
        for metric, stat in metrics.items():
            ms = metric.endswith("_s")
            est = stat.get("estimate")
            prow.append(
                f"| {name} | {metric} | {(_ms(est) + ' ms') if ms and est is not None else _num(est)} | "
                f"{_ci(stat, ms=ms)} | {stat.get('n')} |\n"
            )
    t["T4-paired"] = (
        _header(
            results, "T4 — Paired participant differences (descriptive except where a hypothesis names them)"
        )
        + "| Comparison | Metric | Macro estimate | 95 % CI | P |\n|---|---|---:|---|---:|\n"
        + "".join(prow)
    )
    srows = []
    for a in arms:
        if not role[a]:
            continue
        st = arms[a]["primary"]["strata"]
        for dim in (
            "by_hand",
            "by_zone",
            "by_segment_type",
            "by_speed_tercile",
            "by_lighting",
            "by_distance",
        ):
            block = st.get(dim, {})
            if "note" in block:
                srows.append(f"| {a} | {dim} | — | {block['note']} | | | | |\n")
                continue
            for level, m in block.items():
                srows.append(
                    f"| {a} | {dim} | {level} | {m['matched']} | {m['fn']} | {_num(m['fn_rate'])} | "
                    f"{_ms(m['lead_median_s'])} | {_ms(m['te_pred_mae_s'])} |\n"
                )
    t["T5-strata"] = (
        _header(results, "T5 — Strata of the hypothesis arms (strata are label / metadata properties)")
        + f"Speed tercile edges (inward crossing speed, ROI/s): {results['speed_tercile_edges']}.\n\n"
        + "| Arm | Stratum | Level | Matched | FN | FN rate | Lead median (ms) | TE_pred MAE (ms) |\n"
        + "|---|---|---|---:|---:|---:|---:|---:|\n"
        + "".join(srows)
    )
    trows = []
    for a in arms:
        tr, m = arms[a]["primary"]["trajectory"], arms[a]["primary"]["pooled"]
        trows.append(
            f"| {a} | {_num(tr['ade'], 4) if tr else '— (no trajectory)'} | "
            f"{_num(tr['fde'], 4) if tr else '—'} | {tr['valid_sequences'] if tr else '—'} | "
            f"{_num(m['impact_position_error_median'], 4)} | {m['intensity_n']} | "
            f"{_num(m['intensity_pearson_r'])} | {_num(m['intensity_spearman_rho'])} | "
            f"{_num(m['intensity_mae'])} |\n"
        )
    t["T6-trajectory-intensity"] = (
        _header(results, "T6 — Trajectory (ROI units) and intensity-proxy agreement at commit time")
        + "Trajectory error is against the future causal tracker output, not the physical tip "
        + "(Phase 08 target "
        "semantics); the intensity proxy is kinematic, not force.\n\n"
        + "| Arm | ADE | FDE | Sequences | Impact pos. err. median | Intensity n | Pearson r | "
        + "Spearman ρ | MAE |\n"
        + "|---|---:|---:|---:|---:|---:|---:|---:|---:|\n"
        + "".join(trows)
    )
    t["T7-s1"] = (
        _header(results, "T7 — Sensitivity S1: README §10.1 reference-time matching (never replaces T1)")
        + METRIC_HEAD
        + "".join(_metric_row(a, role[a], arms[a]["s1"]["pooled"], arms[a]["delay_primary_s"]) for a in arms)
    )
    t["T8-zero-delay"] = (
        _header(results, "T8 — Appendix: Δ_proc = 0")
        + METRIC_HEAD
        + "".join(_metric_row(a, role[a], arms[a]["zero_delay"]["pooled"], 0.0) for a in arms)
    )
    vrows = "".join(
        f"| {a} | {arms[a]['spec']['operating_point']['feasible']} | "
        f"{json.dumps(arms[a]['spec']['controls'], sort_keys=True)} | "
        f"{_ms(arms[a]['validation'].get('median_lead_s'))} | "
        f"{_num(arms[a]['validation'].get('fp_per_min'), 2)} | "
        f"{_num(arms[a]['validation'].get('fn_rate'))} |\n"
        for a in arms
    )
    t["T9-validation"] = (
        _header(results, "T9 — Validation-fold results at the frozen points (from the lock; not re-run)")
        + "| Arm | Feasible | Frozen controls | Val. lead median (ms) | Val. FP/min | Val. FN rate |\n"
        + "|---|---|---|---:|---:|---:|\n"
        + vrows
    )
    return t


# ----------------------------------------------------------------------------- figures


def _axes(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=0.8, linestyle="-")
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.xaxis.label.set_color(INK2)
    ax.yaxis.label.set_color(INK2)
    ax.title.set_color(INK)


def figures(results: Mapping[str, Any], out: Path) -> dict[str, Any]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap

    style = _style(results)
    arms = results["arms"]
    data: dict[str, Any] = {}
    plt.rcParams.update({"font.family": "sans-serif", "font.size": 9, "figure.facecolor": SURFACE})
    label = results["label"]

    # F1 primary figure: median lead vs FP per active minute, one interpolation-free curve per arm.
    fig, ax = plt.subplots(figsize=(7.4, 4.6), layout="constrained")
    _axes(ax)
    f1 = {}
    for arm, rec in arms.items():
        pts = [
            (p["fp_per_min"], p["median_lead_s"], p["frozen"])
            for p in rec["curve"]
            if p["fp_per_min"] is not None and p["median_lead_s"] is not None
        ]
        pts.sort()
        f1[arm] = [{"fp_per_min": x, "median_lead_ms": 1000 * y, "frozen": fz} for x, y, fz in pts]
        s = style[arm]
        if pts:
            # achieved points only (interpolation-free, as the Phase 09 curves): no connecting line
            ax.plot(
                [x for x, _, _ in pts],
                [1000 * y for _, y, _ in pts],
                linestyle="none",
                color=s["color"],
                marker=s["marker"],
                markersize=6,
                markeredgecolor=SURFACE,
                markeredgewidth=1,
                zorder=s["z"],
                label=arm,
            )
            for x, y, fz in pts:
                if fz:
                    ax.plot(
                        [x],
                        [1000 * y],
                        marker=s["marker"],
                        markersize=11,
                        color=s["color"],
                        markeredgecolor=SURFACE,
                        markeredgewidth=2,
                        zorder=s["z"] + 1,
                    )
                    if s["role"]:  # direct labels only for the hypothesis arms; the legend names the rest
                        ax.annotate(
                            f"{arm} (frozen)" if s["role"] == arm else f"{s['role']}: {arm} (frozen)",
                            (x, 1000 * y),
                            textcoords="offset points",
                            xytext={"A": (8, 6), "B": (8, -14), "C": (8, 6)}[s["role"]],
                            fontsize=7,
                            color=INK2,
                        )
    ax.axhline(0, color=AXIS, linewidth=1)
    budget = results["budgets"]["fp_budget_per_min"]
    ax.axvline(budget, color=INK2, linewidth=1)
    ax.annotate(
        f"FP budget {budget:g}/min",
        (budget, ax.get_ylim()[1]),
        textcoords="offset points",
        xytext=(4, -12),
        fontsize=7,
        color=INK2,
    )
    ax.set(
        xlabel="False positives per active minute",
        ylabel="Median prediction lead L_pred (ms)",
        title=f"F1  Lead vs false positives on held-out participants — {label}",
    )
    ax.title.set_fontsize(8.5)
    ax.legend(title="Arm", fontsize=7, title_fontsize=7, frameon=False, loc="best")
    fig.savefig(out / "F1-lead-vs-fp.png", dpi=160, facecolor=SURFACE)
    plt.close(fig)
    data["F1-lead-vs-fp"] = f1

    # F2: per-participant paired lead differences with the macro CI.
    pairs = [k for k in results["paired"] if k.startswith(results["c_primary"] + " - ")]
    fig, axes = plt.subplots(
        1, max(1, len(pairs)), figsize=(3.6 * max(1, len(pairs)), 3.4), layout="constrained", squeeze=False
    )
    f2 = {}
    for ax, name in zip(axes[0], pairs, strict=False):
        _axes(ax)
        stat = results["paired"][name]["lead_median_s"]
        values = stat.get("values", {})
        ys = list(range(len(values)))
        ax.scatter([1000 * v for v in values.values()], ys, s=30, color=MUTED, zorder=3, label="participant")
        if stat.get("estimate") is not None:
            ax.axvline(1000 * stat["estimate"], color=SLOT["C"], linewidth=2, label="macro estimate")
        if stat.get("ci"):
            ax.axvspan(
                1000 * stat["ci"][0], 1000 * stat["ci"][1], color=SLOT["C"], alpha=0.10, label="95 % CI"
            )
        ax.axvline(0, color=AXIS, linewidth=1)
        ax.set_yticks(ys, list(values), fontsize=7)
        ax.set(xlabel="Paired lead difference (ms)", title=f"F2  {name}")
        ax.title.set_fontsize(8.5)
        ax.legend(fontsize=6.5, frameon=False, loc="best")
        f2[name] = {
            "values_ms": {k: 1000 * v for k, v in values.items()},
            "estimate": stat.get("estimate"),
            "ci": stat.get("ci"),
        }
    fig.savefig(out / "F2-paired-lead.png", dpi=160, facecolor=SURFACE)
    plt.close(fig)
    data["F2-paired-lead"] = f2

    # F3-F5: small multiples per arm (TE_pred histogram, zone confusion, FP by segment type).
    names = list(arms)
    cols = 3
    rows = (len(names) + cols - 1) // cols
    f3, f4, f5 = {}, {}, {}
    fig3, ax3 = plt.subplots(rows, cols, figsize=(9, 2.6 * rows), layout="constrained", squeeze=False)
    fig4, ax4 = plt.subplots(rows, cols, figsize=(9, 2.9 * rows), layout="constrained", squeeze=False)
    fig5, ax5 = plt.subplots(rows, cols, figsize=(9, 2.4 * rows), layout="constrained", squeeze=False)
    cmap = LinearSegmentedColormap.from_list("blue", BLUE_RAMP)
    for i, arm in enumerate(names):
        ev = arms[arm]["events"]
        a3, a4, a5 = ax3[i // cols][i % cols], ax4[i // cols][i % cols], ax5[i // cols][i % cols]
        for a in (a3, a4, a5):
            _axes(a)
            a.set_title(arm, fontsize=8)
        te = [1000 * v for v in ev["te_pred_s"]]
        f3[arm] = te
        if te:
            a3.hist(te, bins=min(20, max(3, len(te))), color=style[arm]["color"], rwidth=0.9)
            a3.set_xlabel("TE_pred (ms)")
        else:
            a3.text(
                0.5,
                0.5,
                "no predicted matched strike",
                ha="center",
                va="center",
                transform=a3.transAxes,
                color=INK2,
                fontsize=7,
            )
        zones = sorted(
            {r["actual"] for r in ev["zone_confusion"]} | {r["predicted"] for r in ev["zone_confusion"]}
        )
        f4[arm] = ev["zone_confusion"]
        if zones:
            idx = {z: k for k, z in enumerate(zones)}
            m = np.zeros((len(zones), len(zones)), dtype=int)
            for r in ev["zone_confusion"]:
                m[idx[r["actual"]], idx[r["predicted"]]] = r["n"]
            a4.imshow(m, cmap=cmap, vmin=0)
            a4.set_xticks(range(len(zones)), zones, rotation=45, ha="right", fontsize=6.5)
            a4.set_yticks(range(len(zones)), zones, fontsize=6.5)
            for (r_, c_), n in np.ndenumerate(m):
                a4.text(
                    c_,
                    r_,
                    str(n),
                    ha="center",
                    va="center",
                    fontsize=6.5,
                    color="#ffffff" if n > m.max() * 0.6 else INK,
                )
            a4.grid(False)
        else:
            a4.text(
                0.5,
                0.5,
                "no matched strike",
                ha="center",
                va="center",
                transform=a4.transAxes,
                color=INK2,
                fontsize=7,
            )
        seg = ev["fp_by_segment_type"]
        f5[arm] = seg
        if seg:
            a5.barh(list(seg), list(seg.values()), color=style[arm]["color"], height=0.6)
            a5.tick_params(axis="y", labelsize=6.5)
            a5.set_xlabel("False positives")
        else:
            a5.text(
                0.5,
                0.5,
                "no false positive",
                ha="center",
                va="center",
                transform=a5.transAxes,
                color=INK2,
                fontsize=7,
            )
    for axs in (ax3, ax4, ax5):
        for j in range(len(names), rows * cols):
            axs[j // cols][j % cols].set_visible(False)
    fig3.suptitle(f"F3  Predicted-impact timing error per arm — {label}", fontsize=8.5, color=INK)
    fig4.suptitle(f"F4  Zone confusion (rows actual, columns predicted) — {label}", fontsize=8.5, color=INK)
    fig5.suptitle(f"F5  False positives by segment type — {label}", fontsize=8.5, color=INK)
    fig3.savefig(out / "F3-te-pred.png", dpi=160, facecolor=SURFACE)
    fig4.savefig(out / "F4-zone-confusion.png", dpi=160, facecolor=SURFACE)
    fig5.savefig(out / "F5-fp-by-segment.png", dpi=160, facecolor=SURFACE)
    for fig in (fig3, fig4, fig5):
        plt.close(fig)
    data["F3-te-pred"], data["F4-zone-confusion"], data["F5-fp-by-segment"] = f3, f4, f5

    # F6: FN rate and median lead by speed tercile for the hypothesis arms.
    fig, (fa, fb) = plt.subplots(1, 2, figsize=(8, 3.2), layout="constrained")
    terciles = ("slow", "medium", "fast")
    f6 = {}
    for ax in (fa, fb):
        _axes(ax)
    for arm, s in style.items():
        if not s["role"]:
            continue
        st = arms[arm]["primary"]["strata"]["by_speed_tercile"]
        fn = [st[t]["fn_rate"] for t in terciles]
        lead = [None if st[t]["lead_median_s"] is None else 1000 * st[t]["lead_median_s"] for t in terciles]
        f6[arm] = {"fn_rate": fn, "lead_median_ms": lead}
        fa.plot(
            terciles,
            [np.nan if v is None else v for v in fn],
            color=s["color"],
            marker="o",
            linewidth=2,
            label=arm,
        )
        fb.plot(
            terciles,
            [np.nan if v is None else v for v in lead],
            color=s["color"],
            marker="o",
            linewidth=2,
            label=arm,
        )
    fa.set(ylabel="FN rate", title="F6  FN rate by ground-truth speed tercile")
    fb.set(ylabel="Median lead (ms)", title="F6  Median lead by speed tercile")
    for ax in (fa, fb):
        ax.title.set_fontsize(8.5)
        ax.legend(fontsize=7, frameon=False)
    fig.savefig(out / "F6-speed-terciles.png", dpi=160, facecolor=SURFACE)
    plt.close(fig)
    data["F6-speed-terciles"] = f6
    return data


def render(results: Mapping[str, Any], out_dir: str | Path) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, Any] = {"tables": {}, "figure_data": {}, "figures": {}}
    for name, text in tables(results).items():
        written["tables"][name] = _digest(_write(out / f"{name}.md", text))
    for name, payload in figures(results, out).items():
        path = _write(
            out / f"{name}.json", json.dumps(payload, indent=1, sort_keys=True, allow_nan=False) + "\n"
        )
        written["figure_data"][name] = _digest(path)
        written["figures"][name] = _digest(out / f"{name}.png")
    index = "".join(f"- [{n}]({n}.md)\n" for n in written["tables"]) + "".join(
        f"- ![{n}]({n}.png) (data: [{n}.json]({n}.json))\n" for n in written["figures"]
    )
    _write(out / "README.md", _header(results, "Experiment 1 report (generated)") + index)
    return written


__all__ = ["render", "roles", "tables", "figures"]
