"""Phase 06, Task 06.5 — operator setup checklist, filed per session as ``<session_dir>/checklist.json``.

    python scripts/session_checklist.py <session_dir> --operator <initials> [--answers answers.json]
        [--yes ITEM ...]
        [--no ITEM ...] [--note ITEM="text" ...]

Items come from ``docs/protocols/operator-checklist.md`` (the document is the source of truth; the
list below mirrors it and its version). Each item is answered ``YES`` / ``NO`` / ``NA`` /
``NOT_ANSWERED``; nothing is answered by default. The script never fills an answer it was not given —
an unanswered checklist is written as such and ``verify_session`` only records whether a checklist
file exists. Non-interactive by design (answers via ``--answers`` JSON or ``--yes/--no`` flags), so
it can also be exercised in tests without a person; the signed paper copy stays with the operator.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from spacedrums import timing  # noqa: E402

CHECKLIST_VERSION = "0.1-draft"
CHECKLIST_FILENAME = "checklist.json"

# (item id, text) — mirrors docs/protocols/operator-checklist.md section 2, in order.
ITEMS: list[tuple[str, str]] = [
    ("CL-01", "Ethics status checked: recording of this session kind is permitted (ethics-approval-note.md)"),
    ("CL-02", "Consent signed (participant / pilot), form version noted, consent_record_id assigned"),
    ("CL-03", "Pseudonym assigned (P<NN> / PILOT<NN>); no name stored with the recording"),
    (
        "CL-04",
        "Camera on its fixed mount at the marked tripod position and height; not moved since the marks",
    ),
    ("CL-05", "Floor marks present: primary distance mark and second distance mark (labels recorded)"),
    (
        "CL-06",
        "Lighting condition set and identified (L1-L5); exposure_blur_check.py inspect run; values recorded",
    ),
    ("CL-07", "Camera profile confirmed (profile id, resolution, requested FPS, exposure mode/value)"),
    ("CL-08", "Playing area: participant stands inside the on-screen box; both hands and sticks visible"),
    ("CL-09", "Sticks described (colour, length class, marker NONE / TAPE, own / project)"),
    ("CL-10", "Audio output checked: drum sounds audible (active arm recorded)"),
    (
        "CL-11",
        "Pad + microphone (if used): pad placed at the zone's marked position; microphone level checked",
    ),
    ("CL-12", "Background described (tag, people present yes/no)"),
    ("CL-13", "Participant instruction sheet read to / by the participant; questions answered"),
    ("CL-14", "Session metadata options entered into record_session.py (participant, lighting, sticks, ...)"),
    ("CL-15", "Free disk space sufficient for the session (storage estimate in ADR-0019)"),
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session_dir", type=Path)
    ap.add_argument("--operator", required=True, help="operator initials (not a participant identity)")
    ap.add_argument("--answers", type=Path, default=None, help='JSON {"CL-01": "YES", ...}')
    ap.add_argument("--yes", nargs="*", default=[], metavar="ITEM")
    ap.add_argument("--no", nargs="*", default=[], metavar="ITEM")
    ap.add_argument("--na", nargs="*", default=[], metavar="ITEM")
    ap.add_argument("--note", nargs="*", default=[], metavar="ITEM=TEXT")
    ap.add_argument("--print", action="store_true", help="print the checklist items and exit")
    args = ap.parse_args(argv)
    if args.print:
        for cid, text in ITEMS:
            print(f"{cid}  {text}")
        return 0
    known = {cid for cid, _ in ITEMS}
    answers: dict[str, str] = {}
    if args.answers:
        answers.update(
            {str(k): str(v).upper() for k, v in json.loads(args.answers.read_text(encoding="utf-8")).items()}
        )
    for cid in args.yes:
        answers[cid] = "YES"
    for cid in args.no:
        answers[cid] = "NO"
    for cid in args.na:
        answers[cid] = "NA"
    notes: dict[str, str] = {}
    for item in args.note:
        cid, _, text = item.partition("=")
        notes[cid] = text
    bad = sorted((set(answers) | set(notes)) - known)
    if bad:
        print(f"ERROR: unknown checklist items {bad}")
        return 1
    if any(v not in ("YES", "NO", "NA") for v in answers.values()):
        print("ERROR: answers must be YES, NO or NA")
        return 1
    doc = {
        "checklist_version": CHECKLIST_VERSION,
        "source": "docs/protocols/operator-checklist.md",
        "session_dir": args.session_dir.name,
        "operator": args.operator,
        "filed_at": timing.wall_clock_iso(),
        "items": [
            {"id": cid, "text": text, "answer": answers.get(cid, "NOT_ANSWERED"), "note": notes.get(cid, "")}
            for cid, text in ITEMS
        ],
        "complete": all(cid in answers for cid, _ in ITEMS),
        "all_yes_or_na": all(answers.get(cid) in ("YES", "NA") for cid, _ in ITEMS),
    }
    args.session_dir.mkdir(parents=True, exist_ok=True)
    out = args.session_dir / CHECKLIST_FILENAME
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    n_ans = sum(1 for i in doc["items"] if i["answer"] != "NOT_ANSWERED")
    print(
        f"[checklist] {out}: {n_ans}/{len(ITEMS)} items answered; complete={doc['complete']}; "
        f"all YES/NA={doc['all_yes_or_na']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
