"""Replay saved endpoint/body observations through automatic calibration, without inventing pixels."""

import argparse
import json
from pathlib import Path

from spacedrums.calib.automatic import AutomaticCalibration
from spacedrums.calib.reach import ReachSettings
from spacedrums.contracts import CommittedStrike
from spacedrums.contracts.perception import BodyReference, EndpointEvidence
from spacedrums.contracts.schema import validator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    original = json.loads((args.session / "report.json").read_text())
    cal = AutomaticCalibration(
        tuple(original["calibration"]["roi_size"]),
        settings=ReachSettings(**original["calibration"]["settings"]),
        provenance="DEVELOPER_REPLAY",
    )
    for line in (args.session / "observations.jsonl").read_text().splitlines():
        row = json.loads(line)
        evidence = {}
        for entry in row["endpoints"]:
            e = EndpointEvidence(**{k: v for k, v in entry.items() if k != "schema_version"})
            evidence[e.hand_id] = e
        body = BodyReference(**row["body_reference"]) if row.get("body_reference") else None
        cal.update(
            row["frame"]["t_capture"], evidence, body, [CommittedStrike.from_dict(c) for c in row["commits"]]
        )
    report = cal.report()
    validator("product-calibration").validate(report)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "state": report["state"],
                "strokes": len(report["strokes"]),
                "failures": report["failures"],
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
