"""Deterministic report/table/forest-plot data from stored Phase 19 development results."""

import csv
import json
from pathlib import Path

from spacedrums.config import config_hash
from spacedrums.live_eval.prereg import file_digest


def render(results, output):
    if (
        results.get("evidence") != "SYNTHETIC/DEV"
        or results.get("experimental_execution") is not False
        or any(c.get("evidence") != "SYNTHETIC/DEV" for c in results.get("cells", []))
    ):
        raise ValueError("preparation report accepts SYNTHETIC/DEV only")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for aid, metrics in sorted(results["comparisons"].items()):
        for name, stats in sorted(metrics.items()):
            rows.append(
                {
                    "evidence": "SYNTHETIC/DEV",
                    "ablation_id": aid,
                    "metric": name,
                    "estimate": stats["estimate"],
                    "ci_low": (stats["ci"] or [None, None])[0],
                    "ci_high": (stats["ci"] or [None, None])[1],
                    "n": stats["n"],
                    "seed_band": stats["seed_band"],
                    "interpretation": stats["interpretation"],
                }
            )
    fields = (
        "evidence",
        "ablation_id",
        "metric",
        "estimate",
        "ci_low",
        "ci_high",
        "n",
        "seed_band",
        "interpretation",
    )
    with (output / "comparisons.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    forest = [r for r in rows if r["metric"] == "lead_median_s"]
    (output / "forest-data.json").write_text(
        json.dumps(forest, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# Phase 19 preparation — SYNTHETIC/DEV ONLY",
        "",
        "Implementation rehearsal; no participant evidence or experimental completion.",
        "",
        "Primary differences: variant minus reference, seconds. CIs resample grouping identities",
        "after pairing folds/seeds. Synthetic groupings do not represent people.",
        "",
        "| Variant | Status |",
        "|---|---|",
    ]
    for aid, state in sorted(results["variant_status"].items()):
        lines.append(f"| {aid} | {state} |")
    lines += [
        "",
        "External timing, physical latency, participant accuracy and interpretation: PENDING.",
        "CPU latency: PENDING (not timed by this deterministic rehearsal).",
        "Phase 18 remains PENDING. Phase 19 experimental execution is disabled.",
        "",
    ]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    # Standard plotting tool; keep figures derived from the stored numeric data only.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, max(3, len(forest) * 0.32 + 1)))
    for i, row in enumerate(forest):
        if row["estimate"] is not None:
            ax.plot(row["estimate"] * 1000, i, "o", color="#215d91")
        if row["ci_low"] is not None:
            ax.plot([row["ci_low"] * 1000, row["ci_high"] * 1000], [i, i], color="#215d91")
    ax.set_yticks(range(len(forest)), [r["ablation_id"] for r in forest])
    ax.axvline(0, color="gray", linewidth=1)
    ax.set_xlabel("Variant − reference lead (ms); undefined rows have no marker")
    ax.set_title("SYNTHETIC/DEV ONLY — machinery check, no participant evidence")
    fig.tight_layout()
    fig.savefig(output / "forest.png", dpi=120, metadata={"Software": "Space Drums Phase 19 preparation"})
    plt.close(fig)
    return {
        "evidence": "SYNTHETIC/DEV",
        "results_sha256": config_hash(results),
        "files": {p.name: file_digest(p) for p in sorted(output.iterdir()) if p.is_file()},
    }
