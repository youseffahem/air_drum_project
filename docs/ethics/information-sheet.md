# Participant Information Sheet — Space Drums recording study

**Phase:** 00 — Task 00.7 · **Status:** DRAFT template for institutional review. Bracketed fields `[…]` must be filled before any participant is approached. Not to be used until the ethics question in [`ethics-approval-note.md`](ethics-approval-note.md) is answered.
**Version:** IS-v0.1 (2026-09-20)

---

**Study title:** Space Drums — webcam-based recording of drumstick motion for anticipating virtual drum strikes
**Principal investigator:** [name, programme, institution, e-mail]
**Supervisor:** [name, department, e-mail]
**Institution:** [institution]

## 1. What is this study about?

Space Drums is a graduation project that lets a person play a virtual drum kit with ordinary drumsticks in front of a single webcam — no sensors, no special sticks. The research question is whether a small computer model can predict, from the recent motion of the hands and sticks, *where and when* a stick is about to hit a virtual drum zone, so that the drum sound can be triggered with less delay. To train and evaluate such a model we need recordings of real people moving real drumsticks.

## 2. Why have I been asked?

You are one of approximately 10–12 adults we are inviting. You do **not** need any drumming experience. You need to be able to hold two drumsticks and move your arms comfortably for the duration of a session.

## 3. What will I be asked to do?

- Attend **1 or 2 sessions** of about [30–60] minutes each, at [location].
- Stand in a marked area in front of a laptop webcam and hold two ordinary drumsticks (provided).
- Follow a **structured protocol** shown on screen: single hits, alternating hands, repeated and fast hits, moving between virtual zones, deliberate "fake" swings, stopping before a hit, pausing, and short segments where a hand is briefly hidden or lighting changes. Some segments may be repeated at a different distance from the camera or under different room lighting.
- **Optional condition:** in some segments you may be asked to hit a small rubber practice pad while a microphone records the tap sound. This lets us measure exactly when the stick touched the pad. You can skip this condition.
- You can rest at any time and stop at any point.

## 4. What is recorded?

| Data | Details |
|---|---|
| **Video** | The webcam view of the playing area: your **hands, forearms, drumsticks, and part of your upper body/torso**. Depending on your height and distance, your **face may be visible**. [If the protocol allows: we will position the camera / crop the stored video to exclude the face where possible — state the actual practice.] |
| **Audio** (optional condition only) | Sound from a microphone near the practice pad during pad segments. Speech during those segments may be captured; segments are trimmed to the protocol tasks. |
| **Derived data** | Positions of hand landmarks and stick tips computed from the video; timing of hits; automatically generated labels. |
| **Session metadata** | Date, session length, camera settings, lighting condition, your **approximate distance** from the camera, **handedness**, whether you have drumming experience (yes/no, optional), and an **age range** (optional). **No name, e-mail, or other direct identifier is stored with the recordings.** |

Nothing is recorded outside the sessions. No physiological measurement is taken.

## 5. How will my data be stored and protected?

- You are assigned a **pseudonymous code** (e.g. `P07`). The list linking codes to names is kept separately by the principal investigator, [encrypted / on paper in a locked location], and destroyed [at the end of the project / after examination / on DATE].
- Recordings are stored on [an encrypted drive of the project laptop and one encrypted backup]; they are **never** uploaded to cloud services.
- Only the principal investigator and supervisor [and named examiners] have access to raw video.
- Raw video is kept for [N years / until DATE] per [institutional policy], then deleted. Derived, non-identifying data (landmark positions, timings, labels) may be kept longer (see §7).

## 6. What are the risks and benefits?

- **Risks:** mild arm fatigue; the small possibility of being recognisable in video if your face is in view. Sessions are short and you may rest or stop.
- **Benefits:** none to you personally beyond trying the system; the study contributes to an open research question in human–computer interaction.
- **Compensation:** [none / small token — state institutional practice].

## 7. What will happen to the results and my data?

We will ask you separately, on the consent form, for permission for three uses:

1. **This project** — training and evaluating models, writing the graduation thesis, and demonstrating the system. Individual recordings may appear as **anonymised illustrations** (landmark overlays, trajectories); raw video frames appear in the thesis only if you consent to that explicitly.
2. **Future research by the same team** — reuse of your recordings and derived data in follow-up studies at [institution] on the same topic.
3. **Release as a research dataset** — publication of your recordings (video and/or derived data — you can choose derived data only) under a research licence so other researchers can reproduce our results. Released video would be [face-cropped / as recorded — state which]. Whether such a release is permitted at all is subject to institutional approval; if it is not, this option lapses.

You can say **yes** to 1 and **no** to 2 and/or 3; participation does not depend on 2 or 3.

## 8. Can I withdraw?

Yes, at any time during a session, without giving a reason. After a session, you can ask for your recordings to be deleted until [DATE / the dataset is frozen for analysis, expected around MONTH YEAR]; after that point, data already used in trained models and published results cannot be removed, but your raw video will still be deleted on request and excluded from any future release.

To withdraw, contact [PI e-mail] quoting your participant code or session date.

## 9. Who has reviewed this study?

[This study has been reviewed and approved by … / A review by … has been requested (reference …) / The institution has confirmed that formal ethics approval is not required for this study — fill per `ethics-approval-note.md`.]

## 10. Contact

Questions: [PI name, e-mail]. Concerns you would rather not raise with the PI: [supervisor or institutional contact, e-mail].

Thank you for considering taking part. Please keep this sheet.
