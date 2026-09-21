# Phase 06 — Participant Recording Campaign Report

**Task:** 06.11 · **Date:** 2026-09-21 · **Status: PENDING / NOT VALIDATED — the campaign has not started.**

No participant has been recruited, scheduled or recorded. No pilot has been run (Task 06.10 PENDING), the protocol is not frozen (v0.1-draft), the ethics question is an Open Question (`docs/ethics/ethics-approval-note.md`: no participant recording may be made before it is answered), and the project owner decided that no new recording is made in this phase. This document is the report *template* with every campaign quantity explicitly pending; it is filled only with MEASURED counts after the campaign (phase document: "all MEASURED after the fact; no numbers assumed").

## 1. Campaign facts (all MEASURED after the campaign)

| Quantity | Target (from `project-discovery.md`, Q46 — a target, never a result) | Actual | Label |
|---|---|---|---|
| Participants recruited | ~10–12 | — | **PENDING** |
| Participants recorded | — | — | **PENDING** |
| Sessions per participant | 1–2 | — | **PENDING** |
| Sessions recorded / accepted / review / quarantined | — | — | **PENDING** |
| Segments (takes) accepted / excluded, by segment type | — | — | **PENDING** |
| Total recorded duration (minutes of frames, from the manifest) | — | — | **PENDING** |
| Pad+mic subset (participants, segments, strikes with `t_impact_phys` availability) | To Be Experimentally Determined | — | **PENDING** |
| Lighting conditions covered (ids), distance marks used, background tags | — | — | **PENDING** |
| Handedness / experience distribution (consent-form Part D, where given) | — | — | **PENDING** |
| Withdrawals | — | — | **PENDING** |
| Consent records complete for every listed session | required | — | **PENDING** |
| `ds-raw-v1.0` manifest (`data/manifests/ds-raw-v1.0.json`), `manifest_hash` | required | **does not exist** (the builder refuses to write an empty participant manifest) | **PENDING** |
| Exclusion log (`ds-raw-v1.0.exclusions.jsonl`) | required | does not exist | **PENDING** |

## 2. How the campaign will be run (implemented, not executed)

1. Ethics answered → protocol v1.0 frozen after the pilot → operator checklist + participant instructions in their v1.0 forms.
2. Per session: `scripts/record_session.py --live --kind PARTICIPANT …` → `scripts/session_checklist.py` → `scripts/verify_session.py --exclusions-log data/raw/exclusions.jsonl` (re-take / re-record while the participant is present when the verdict asks for it).
3. After the campaign: `scripts/build_raw_manifest.py build ds-raw-v1.0` → `check`; counts in §1 are read from the manifest totals (`MEASURED from the listed files`) and from the exclusion log; this report is filled with those numbers and nothing else.

## 3. Statement

The Phase 06 machinery (recording tool, protocol, metadata, checklist, verification, policy, manifest) is IMPLEMENTED and tested on SYNTHETIC and DEV CAPTURE input. **There is no participant data.** Nothing in this repository represents the target population, a class balance, a hit distribution, a real-world coverage or a dataset size.
