# 3. Requirements and analysis

## 3.1 Approach

No children, families or staff were recruited, so requirements could not be
elicited through interviews or observation. Instead they were derived from three
sources:

1. **Published guidance** — safeguarding, mental health and attendance guidance,
   the UK GDPR and the ICO's children's code (Chapter 2).
2. **Workflow reconstruction** — the daily, weekly and termly tasks implied by a
   single-school pastoral model, written as scenarios and walked through on paper.
3. **Design principles P1–P8** from Section 2.7, each of which rules out a class
   of feature that would otherwise look reasonable.

This is a limitation, and it is stated as one in Section 7.5. The mitigation is
that every requirement is expressed as a testable behaviour, so the artefact can
be evaluated even though the requirements were not co-designed with users.

## 3.2 Stakeholders

| Stakeholder | Primary goal | Main risk if the design is wrong |
|---|---|---|
| Child | Be heard; get help without being labelled | Seeing a risk score about themselves; private notes read by staff |
| Parent / guardian | Know how their child is doing; feel included | Being excluded, or seeing another family's data |
| Mentor (teacher, counsellor) | Notice change; coordinate with home | Drowning in alerts; seeing raw diary text they should not |
| Designated safeguarding lead | Act on urgent concerns quickly and correctly | Missing a disclosure; receiving it in an unlogged channel |
| Administrator / head | Understand the cohort; manage accounts and consent | Becoming "the person who can see everything" |
| School as data controller | Meet legal and safeguarding duties | Unlawful processing; no audit trail; reputational harm |
| Developer / marker | Inspect, run and evaluate the system | A demo that cannot be reproduced |

The child is the most vulnerable stakeholder and the one with the least
institutional power, so the design gives the child explicit protections rather
than relying on staff goodwill.

## 3.3 Functional requirements

Priorities use MoSCoW: **M**ust, **S**hould, **C**ould, **W**on't (this release).

### Accounts, access and audit

| ID | Requirement | Priority |
|---|---|---|
| FR1 | A user signs in with a username and password; every sign-in and sign-out is recorded | M |
| FR2 | Access is decided by `(role, relationship) × resource → access level`, not by role alone | M |
| FR3 | A guardian relationship without current consent grants no access; revocation takes effect immediately | M |
| FR4 | Sensitive denials are recorded in an append-only audit log with actor, resource, child and reason | M |
| FR5 | The administrator can read aggregates and configuration, but not emotional content, case notes or messages | M |
| FR6 | A child can open only their own profile and never an adult's observation about them | M |

### Data capture

| ID | Requirement | Priority |
|---|---|---|
| FR7 | A child completes a daily emotional check-in on four 1–5 scales with an optional note | M |
| FR8 | A mentor or guardian records a structured observation about a child's emotional presentation | M |
| FR9 | An assigned mentor records marks as `score / max_score`, with an optional target | M |
| FR10 | Attendance is recorded per child per day | S |
| FR11 | An assigned mentor records structured social observations | M |
| FR12 | A child, guardian or mentor logs sleep, activity, screen time, nutrition and breakfast | M |
| FR13 | The reporter's source is derived from their role, never chosen by the form | M |
| FR14 | Note visibility is per row: private, mentors only, or all adults with access | M |
| FR15 | Future-dated entries are rejected; marks above the maximum are rejected; an empty habit log is rejected | M |
| FR16 | Two reporters may describe the same habit day without overwriting each other | S |

### Scoring and analytics

| ID | Requirement | Priority |
|---|---|---|
| FR17 | The platform computes a 0–100 score per domain and a combined score per rolling 7-day window, eight windows deep | M |
| FR18 | Each score stores its data-point count, confidence label and method version | M |
| FR19 | A window with no data produces no row, not a zero | M |
| FR20 | A personal 28-day baseline (mean and standard deviation) is stored per child and domain | M |
| FR21 | Trends render as accessible charts with a fixed 0–100 axis, gaps and a baseline band | M |
| FR22 | The administrator sees cohort averages, distribution and confidence counts, with no child named | M |
| FR23 | A child is refused access to any individual score page, including their own | M |

### Alerts and response

| ID | Requirement | Priority |
|---|---|---|
| FR24 | Deterministic rules turn scores, baselines and guardian pulse into findings with embedded evidence | M |
| FR25 | Each rule keeps one rolling alert per child; re-runs increment occurrences once per day and never auto-resolve | M |
| FR26 | An open alert may escalate but never downgrade | M |
| FR27 | Every alert is assigned to a named person, preferring the safeguarding lead for urgent findings | M |
| FR28 | A mentor can acknowledge, note, resolve or dismiss an alert; the timeline is append-only | M |
| FR29 | A non-urgent alert can be shared with consenting guardians; urgent alerts cannot be shared | M |
| FR30 | Free-text notes are screened for a short list of safeguarding phrases; the alert stores the category and entry reference, never the text | M |
| FR31 | A guardian sees only shared, non-urgent updates for their own child, plus the pulse | M |

### Guardian feedback and messaging

| ID | Requirement | Priority |
|---|---|---|
| FR32 | A guardian submits one pulse per child per week: two ratings and an optional comment | M |
| FR33 | A mentor reads the pulse history; the administrator sees aggregate participation only | M |
| FR34 | A mentor and a consenting guardian exchange append-only messages about a child | M |
| FR35 | The child and the administrator cannot read or write message threads | M |
| FR36 | Ending a mentorship or revoking consent removes message access immediately | M |
| FR37 | A mentor can close a thread without deleting it; a closed thread stays readable | S |

### Machine-learning benchmark and operations

| ID | Requirement | Priority |
|---|---|---|
| FR38 | An offline benchmark fits a 13-feature logistic regression and validates it leave-one-child-out | S |
| FR39 | The stored report contains aggregate metrics and coefficients only, with no child identifier | M |
| FR40 | Only an administrator can open the benchmark page | M |
| FR41 | `/healthz/` reports application and database status without exposing configuration | M |
| FR42 | A seed command rebuilds a labelled synthetic cohort for demonstration and evaluation | M |

## 3.4 Non-functional requirements

| ID | Requirement | How it is met |
|---|---|---|
| NFR1 | **Security** — every access decision is server-side and fail-closed | Permission gate in `dispatch`; no client-side authorisation |
| NFR2 | **Privacy** — collect the minimum; no free text in scores or ML | Numeric-only scoring; aggregate-only model artefact |
| NFR3 | **Auditability** — reads, writes, shares, denials and safeguarding screens are recorded | `AuditLog`; append-only models |
| NFR4 | **Integrity** — scores are reproducible; re-running does not duplicate | Method version; idempotent recompute; unique constraints |
| NFR5 | **Usability** — a check-in takes under a minute; a mentor reaches the queue in one click | Short forms; role-specific dashboard |
| NFR6 | **Accessibility** — WCAG 2.2 AA intent: semantics, labels, focus, contrast, non-colour cues | Hand-written CSS and templates; table alternative to charts |
| NFR7 | **Performance** — routine pages respond in well under a second on the target host | Indexed queries; server-rendered SVG; measured in 6.7 |
| NFR8 | **Maintainability** — one authority per rule; no duplicated permission logic | Matrix, row gate, services layer |
| NFR9 | **Testability** — every rule has an automated test | 270 tests; see 6.2 |
| NFR10 | **Portability** — runs locally and on the host without code changes | Environment-driven settings |
| NFR11 | **Deployability** — no build step, no separate static server | WhiteNoise; collected static files |
| NFR12 | **Compatibility** — no syntax newer than the host interpreter | `scripts/check_compat.py` |
| NFR13 | **Safety of absence** — missing data is never interpreted as a low score | No-row rule; gap-aware rules |
| NFR14 | **Least surprise** — the interface never shows a child a risk label | `SCORE/ALERT: NONE` for the child role |

## 3.5 Constraints

- **Single school, single database.** No tenant isolation, no cross-school
  administration.
- **Python and Django.** The brief requires a Python backend.
- **Server-rendered HTML, hand-written CSS, vanilla JavaScript.** Bootstrap and
  Tailwind were explicitly excluded, so there is no utility-class dependency and
  no front-end build pipeline.
- **SQLite.** Adequate for one school and a free host; concurrency is a known
  limitation (Section 7.5).
- **Free hosting.** The public URL must remain available for marking without a
  paid tier.
- **No user file uploads.** This removes a malware and moderation surface that
  cannot be defended within the project.
- **One-week build window.** Scope had to be complete rather than broad; the ML
  layer was kept but confined to offline evaluation.
- **No real personal data.** Evaluation uses a generated cohort.

## 3.6 Key scenarios and acceptance criteria

**S1 — Child without consent.** A child whose guardian has not consented opens
the check-in page. The system refuses and explains that consent is needed; no
check-in is written.

**S2 — Mentor and the private note.** A child shares a check-in with mentors but
writes a private note. The mentor sees the ratings, the adult observations and
the fact that a note exists, but not its text.

**S3 — Another family.** A parent changes the child id in the URL to a child they
are not linked to. The system returns 403 and records the denial; it does not
reveal whether the child exists.

**S4 — Administrator scope.** The administrator opens the cohort page and sees
averages, distribution and confidence counts. No child name, emotional note or
case note appears, and the individual trend page is refused.

**S5 — Repeat evaluation.** The alert engine runs twice on the same day for a
child in difficulty. One alert exists, `occurrences` does not increase, and the
tier does not downgrade. On a later day it increments once.

**S6 — Urgent sharing.** A mentor tries to share an urgent safeguarding alert
with a guardian. The action is refused; the alert remains internal and assigned
to the designated lead.

**S7 — Consent withdrawn.** A guardian revokes consent. Their message thread and
child pages immediately return 403, while the history remains on record for the
school.

**S8 — Missing week.** A child stops recording for a week. The trend shows a gap,
the score table says "no data", and no rule treats the gap as a decline. If there
is earlier history, a `no_recent_data` watch is raised for a human to follow up.

Each scenario has at least one automated test; S2, S3, S4, S6 and S7 also have a
live check in Section 6.9.

## 3.7 Prioritisation and traceability

The must-have set is the smallest system that is safe to operate: accounts,
consent gate, four capture paths, scores, alerts with an owner, audit, and the
child/administrator restrictions. Should-have items improve coverage and
coordination (attendance, shared habit days, thread closing, the ML benchmark).
Could-have items were deliberately dropped: email notifications, attachments,
bulk import, per-school configuration, dark mode, and a mobile app.

Traceability is maintained in two directions. Each functional requirement maps to
at least one test or measured behaviour (Table 6.10), and each design element in
Chapter 4 names the requirement it satisfies. This prevents the common failure in
which a feature exists but nothing in the evaluation depends on it.

## 3.8 Summary

The requirements make the governance constraints operational: consent is a gate,
denials are auditable, the child is protected from their own label, and the
administrator is powerful but not omniscient. Chapter 4 shows how those
requirements are realised in the architecture.
