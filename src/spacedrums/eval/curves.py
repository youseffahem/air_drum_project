"""Interpolation-free operating-point plots for comparable arm sweeps."""

from __future__ import annotations

from pathlib import Path


def plot_lead_fp(points: list[dict], output: str | Path, *, title: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    groups = {}
    for point in points:
        x, y = point["fp_per_min"], point["median_lead_s"]
        if x is None or y is None:
            continue
        settings = point["settings"]
        key = (settings["arm"], settings.get("motion_model"), settings.get("K"))
        groups.setdefault(key, []).append((x, y * 1000))
    fig, ax = plt.subplots(figsize=(7, 4.5), layout="constrained")
    for key, coordinates in sorted(groups.items()):
        ax.scatter(
            [p[0] for p in coordinates],
            [p[1] for p in coordinates],
            s=28,
            label="/".join(str(v) for v in key if v is not None),
            alpha=0.8,
        )
    ax.axhline(0, color="0.5", linewidth=0.8)
    ax.set(xlabel="False positives per active minute", ylabel="Median prediction lead (ms)", title=title)
    if groups:
        ax.legend(title="Arm/model/horizon steps", fontsize=8)
    else:
        ax.text(0.5, 0.5, "No matched operating points", ha="center", va="center", transform=ax.transAxes)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=160)
    plt.close(fig)


def plot_result_diagnostics(result: dict, output: str | Path) -> None:
    """Timing histogram, zone confusion and FP attribution from one result."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    timing = [
        1000 * (e["t_impact_pred"] - e["t_impact_est"])
        for e in result["events"]
        if e["kind"] == "MATCH" and e.get("t_impact_pred") is not None
    ]
    fig, ax = plt.subplots(figsize=(6, 4), layout="constrained")
    if timing:
        ax.hist(timing, bins=min(20, max(3, len(timing))), color="#2669a8")
    else:
        ax.text(0.5, 0.5, "No predicted matched strikes", ha="center", va="center", transform=ax.transAxes)
    ax.set(xlabel="Predicted impact minus label (ms)", ylabel="Count", title="Timing error")
    fig.savefig(output / "timing-error.png", dpi=160)
    plt.close(fig)

    confusion = result["pooled"]["zone_confusion"]
    zones = sorted({r["actual"] for r in confusion} | {r["predicted"] for r in confusion})
    fig, ax = plt.subplots(figsize=(6, 5), layout="constrained")
    if zones:
        index = {z: i for i, z in enumerate(zones)}
        matrix = np.zeros((len(zones), len(zones)), dtype=int)
        for row in confusion:
            matrix[index[row["actual"]], index[row["predicted"]]] = row["n"]
        ax.imshow(matrix, cmap="Blues")
        ax.set_xticks(range(len(zones)), zones, rotation=45, ha="right")
        ax.set_yticks(range(len(zones)), zones)
        for (i, j), count in np.ndenumerate(matrix):
            ax.text(j, i, str(count), ha="center", va="center")
    else:
        ax.text(0.5, 0.5, "No matched strikes", ha="center", va="center", transform=ax.transAxes)
    ax.set(xlabel="Predicted zone", ylabel="Actual zone", title="Zone confusion")
    fig.savefig(output / "zone-confusion.png", dpi=160)
    plt.close(fig)

    counts = result["pooled"]["fp_by_segment_type"]
    fig, ax = plt.subplots(figsize=(6, 4), layout="constrained")
    if counts:
        ax.barh(list(counts), list(counts.values()), color="#c0642d")
    else:
        ax.text(0.5, 0.5, "No false positives", ha="center", va="center", transform=ax.transAxes)
    ax.set(xlabel="False positives", ylabel="Segment type", title="FP attribution")
    fig.savefig(output / "fp-by-segment.png", dpi=160)
    plt.close(fig)
