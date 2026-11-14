# Kito — child wellness monitoring platform

A web platform for a single school to monitor, support and act on four
dimensions of child wellbeing:

| Module | What it captures |
|---|---|
| Emotional wellness | Child self check-ins and adult observations |
| Academic progress | Assessment records, targets, attendance |
| Social development | Structured peer/participation observations |
| Healthy habits | Sleep, activity, screen time, nutrition |

Four roles (parent, mentor, child, administrator) see different, explicitly
permissioned slices of the data. Derived wellness scores drive tiered
early-warning alerts that are routed to a named person and tracked to
resolution.

## Design principles

- **Fail closed.** `core.permissions` is the single gate; anything not
  explicitly granted is denied and sensitive denials are audited.
- **A child never sees their own risk score or tier.** Labelling a child as
  "at risk" in their own interface is a harm vector.
- **Admins see aggregates, not content.** Emotional notes and case notes are
  not readable by the administrator role.
- **Consent is a gate, not a checkbox.** A guardian link without recorded
  consent grants no access at all.
- **No real children's data.** The demo runs on a synthetic cohort generated
  by `manage.py seed_demo`.
- **No user file uploads anywhere.** Emoji avatars, print-to-PDF exports.

## How access works

Access is decided in two layers, and both are enforced server-side:

1. **Page gate** — `core/permissions.MATRIX` maps
   `(role, relationship) × resource → Access`. The role alone is never
   sufficient: a mentor with no assignment to a child gets nothing, and a
   guardian whose consent was withdrawn gets nothing either. Views inherit
   `core.mixins.ChildScopedMixin`, which resolves the child from the URL and
   refuses before the view body runs. Denials are audited.
2. **Row gate** — `domains/access.entries_for` decides which *individual
   records* a permitted user may see. A mentor has `SUMMARY` on emotional
   wellness, so they see staff observations and check-ins the child chose to
   share — never private ones. Free text is filtered again per row by
   `note_visible_to`, so seeing a rating never implies seeing the note.

A consequence worth stating explicitly: a child account has `WRITE` on its own
emotional data, but the row gate still hides every adult observation about
them. Being allowed to write is not the same as being allowed to read, and the
platform does not conflate the two.

## Entering data

| Domain | Who writes | Shape of an entry |
|---|---|---|
| Emotional wellness | Child (daily check-in), mentor or guardian (observation) | 1–5 scales plus optional note |
| Academic progress | Assigned mentor | Mark, maximum mark, optional target |
| Social development | Assigned mentor | One dimension rated 1–5, with context |
| Healthy habits | Child, guardian or mentor | Sleep, activity, screen time, nutrition, breakfast |

Two details are deliberate:

- **The reporter is derived from the role, never chosen by the form.** A mentor
  cannot file a record as a guardian's observation. The stored `source` is what
  the row-level gate uses later.
- **Habits are keyed by `(child, day, source)`.** A child, a guardian and a
  mentor may each describe the same day, and the platform keeps them as
  separate rows rather than letting the second reporter overwrite the first.
  Re-submitting as the same person updates your own row; a *different* person
  is told the day is already covered.

## Wellness scores (method 1.0)

Scores are a **derived** summary, not source data. `DomainScore` and
`BaselineStat` are a cache of a calculation: delete them, run
`manage.py recompute_wellness`, and the same entries produce the same numbers.
Every row carries the `method_version` that produced it, so an old figure can be
explained by the arithmetic that was in force at the time.

**Shape.** For each child, each of the four domains and a combined `overall`
pseudo-domain, the platform stores one score per rolling 7-day window, eight
windows deep. The latest window always ends today, so a new entry is visible on
the next page load rather than waiting for a calendar week to close. Each window
also stores how many distinct days contributed and a confidence label.

**Normalisation.** Every domain is reduced to a per-day value between 0 and 1
before anything is averaged, because minutes of activity, marks out of twenty
and 1–5 ratings are not the same kind of quantity:

| Domain | Daily value | Weight |
|---|---|---|
| Emotional wellness | Mean of mood, energy, sleep quality and felt connection (1–5 → 0–1) | 40% |
| Academic progress | Mark as a share of the maximum available | 25% |
| Healthy habits | Sleep against age-appropriate guidelines, activity, screen time, nutrition, breakfast | 20% |
| Social development | Structured 1–5 observation ratings | 15% |

When several people report on the same day, their values are averaged for that
day. A window with no entries produces **no row at all** rather than a zero:
a missing week is a gap in the chart, not evidence of a decline.

**Combining domains.** The overall score uses the weights of the domains that
actually have data on a given day, renormalised so absent domains are not
counted as zero. It also requires at least two domains that day; a child with
only emotional check-ins gets no overall score, and the page says why.
"Averaging missing domains as zero" is how a monitoring system quietly labels an
unmeasured child as unwell.

**Baselines.** For each child and domain the platform stores a 28-day mean and
standard deviation. That personal band is what the charts shade and what the
alert engine compares against — not a population average, because the
population includes children whose normal is already a concern.

**Confidence is coverage, not certainty.** Labels are set per domain's natural
reporting cadence: `good` when a window has enough distinct days for that domain,
`moderate` at roughly half, `thin` for one or two entries, `none` for a gap.
Academic and social observations are less frequent than a daily check-in, so
they have a lower threshold than emotional or habits.

**Free text is excluded.** The scoring code queries numeric fields only. A note
on a check-in is the highest-risk field on the platform; a numeric score must
not become a side channel that leaks it.

**Who sees what.** Mentors and guardians with `SCORE: READ` for a child see that
child's trend. The administrator has `SCORE: AGGREGATE` at institution scope:
they see cohort averages, distribution and confidence counts, never a child's
individual trend, and the aggregate page has no names to redact. A child is
refused both — `(CHILD, SELF)` has `SCORE: NONE`.

Charts are inline server-rendered SVG with a fixed 0–100 axis (auto-scaling
makes a two-point wobble look like a crisis), gaps that break the line, and the
same numbers repeated in a `<details>` table so the chart is never the only way
to read the data.

## Early-warning alerts (D5)

Scores describe; alerts route attention. The engine in `alerts/` turns stored
scores, baselines and the guardian pulse into findings, and every finding is
persisted as an alert owned by a named person.

**Rules are deterministic and explainable.** Each finding embeds the numbers
that produced it, so a mentor can answer "why did this fire?" a week later
without re-running a model. There is no machine-learning classifier in the
production path; the D6 benchmark is an offline evaluation only.

| Rule | Tier | Fires when |
|---|---|---|
| `overall_very_low` | urgent | Two consecutive reasonably-covered weeks at or below 35/100 |
| `overall_below_baseline` | concern | Latest overall score is ≥1.5 SD below the child's own 28-day baseline |
| `sustained_low` | concern | Three consecutive weeks at or below 45/100 |
| `declining_trend` | watch | Overall score falls ≥10 points versus four weeks earlier |
| `domain_below_baseline:<domain>` | watch | A domain falls ≥1.5 SD below that child's own baseline |
| `multiple_domains_low` | concern | Two or more domains at or below 50/100 in the latest window |
| `no_recent_data` | watch | Entries earlier in the eight-week window but none in the latest week |
| `guardian_pulse_low` | concern | Two consecutive weekly guardian pulses rate the week difficult |
| `safeguarding_signal:<category>` | urgent | Free text matches a short behavioural phrase list (self-harm, harm by others, unsafe home, neglect) |

Three constraints keep the queue meaningful:

- **A child is compared with themselves.** Baselines are the child's own recent
  mean and standard deviation, not a class average; a child whose normal is low
  is not flagged for being consistently themselves.
- **Confidence gates severity.** Score rules require at least `moderate`
  coverage. A single blip cannot become an urgent alert, and a missing week is a
  gap, not a zero.
- **One overall alert per child per run, and one rolling alert per rule.** A
  child in difficulty produces one explainable overall alert rather than four
  overlapping ones. Re-running the engine updates the open alert, increments
  `occurrences` only on a new day, and never downgrades a tier or auto-resolves.

**Assignment.** Urgent and safeguarding findings go to `School.safeguarding_lead`
when one is named; otherwise to the child's class teacher, then mentor, then
counsellor. An unassigned alert is a notification nobody reads, so the engine
always looks for a person first.

**Safeguarding screening is a safety net, not a classifier.** Matched phrases are
short and behavioural. The alert stores the category, date and entry reference —
**never the note text**. The original note stays in its domain table under that
domain's access rule, so a safeguarding queue cannot become a second, less
protected copy of a child's diary. A match is always urgent and is never
auto-notified or shared with a guardian; the designated lead follows the
school's procedure and speaks to the family directly.

**Guardian sharing is an explicit mentor action.** A non-urgent alert can be
shared with the child's guardians; internal case notes and evidence stay private.
Urgent alerts cannot be shared at all, and sharing is refused when the child has
no active guardian consent.

**Case timeline is append-only.** Acknowledge, note, resolve, dismiss and share
all go through `alerts/services.py`, which refuses transitions on a closed alert.
Every action is audited. The administrator sees cohort counts only — no child
names, no case notes.

**What a guardian sees.** `/alerts/family/` shows only updates a mentor chose to
share, plus this week's pulse. It never shows scores, tiers, case notes, other
families, or urgent safeguarding matters.

## Guardian pulse (D5)

`/children/<id>/pulse/` is a guardian's own channel: two ratings (the child's
week, and how supported the family feels) and an optional 600-character comment,
one response per guardian per child per week. A mentor assigned to the child can
read the history; the administrator sees aggregate participation and averages
only, with no names and no comments. The scoring and alert code reads the two
ratings only — the comment is for a human.

Two consecutive low weeks raise a `concern` alert. One difficult week is a
difficult week, not a case.

**Evaluation.** `manage.py backtest_alerts` replays the rules over the synthetic
cohort's labelled trajectories and reports child-level precision, recall and
median lead time. The demo cohort currently gives precision 0.70, recall 1.00
and a median lead time of 10 days after simulated onset (3 false positives out
of 15 negative children). Ground truth is synthetic: these figures measure the
rules against the generator's labels, not against clinical outcomes.

## Stakeholder messages (D6)

`/messages/` is an adult-to-adult channel: a mentor and a guardian writing to
each other about a child they both already care for. It is deliberately **not** a
child-facing inbox.

| Who | Access | Why |
|---|---|---|
| Mentor assigned to the child | read and write | Day-to-day coordination with home |
| Guardian with consent on file | read and write | The other half of that conversation |
| Any other mentor or guardian | none | Row gate: only assigned/consented adults reach a thread |
| Child | none | A private adult-managed channel around a child is an unmonitored space, not support. The child's own channel is the check-in |
| Administrator | none | Correspondence about a family is not configuration data |

Four rules make the boundary enforceable rather than aspirational:

- **Visibility is per child, not per role.** `messaging.services` asks the
  permission gate for every thread. Ending a mentorship or revoking consent
  removes access immediately; the history stays on record.
- **Messages are append-only.** `Message.save()` refuses an update and
  `Message.delete()` refuses a delete, so a correction is a new message rather
  than a silent edit of the record.
- **A closed thread stays readable.** A mentor can close a conversation; it then
  accepts no new replies but remains visible to the adults who had access.
- **Everything is audited.** Opening the inbox, reading a thread, starting one,
  replying and closing all write an `AuditLog` row, and a denial is recorded
  because `Resource.MESSAGE` is in `AUDITED_RESOURCES`.

`messaging.admin` registers **nothing**. Registering these models would give the
administrator role a second surface on the same data and make the permission
matrix a decoration.

Deliberately out of scope: attachments (no uploads anywhere), outbound email or
push, guardian-to-guardian threads, and any child participation.

## Offline model benchmark (D6)

`/cohort/model/` answers a narrow, falsifiable question:

> Can a plain logistic regression, given only the same structured features the
> deterministic rules already use, separate the synthetic cohort's labelled
> difficult periods from its stable periods when every held-out child is one the
> model has never seen?

It is an **offline evaluation, not a production classifier**. It writes no alert,
no score and no per-child prediction; nothing in the care path reads it. The
alert backtest above remains the early-warning measurement. This benchmark is a
check on whether the features carry signal at all.

| Property | Choice |
|---|---|
| Features | 13 numeric features: latest and prior overall scores, four-week change, deviation from the child's own recent range, the four domain scores, share of domains at or below 50, domain coverage, and the latest guardian wellbeing/support ratings with a missing-pulse flag |
| Excluded inputs | Free text of every kind — check-in notes, observations, case notes, pulse comments, messages |
| Labels | The synthetic archetype's *current* state: declining from its simulated onset, recovering before its recovery, healthy throughout. Sparse children are excluded because missing data is not a wellness label |
| Validation | Leave-one-child-out by child. Splitting by snapshot would leak the same child into training and produce a flattering number |
| Model | Ridge-penalised logistic regression fitted with IRLS in pure Python; no numpy, scikit-learn or extra deployment dependency |
| Tuning | Fixed L2 = 0.05 and threshold 0.5. No hyper-parameter search on the evaluation data |

Current report on the demo cohort: 176 held-out snapshots from 22 children
(42 difficult, 134 stable), 22 folds.

| Metric | Value |
|---|---|
| Accuracy | 0.9489 |
| Precision | 0.9459 |
| Recall | 0.8333 |
| F1 | 0.8861 |
| Specificity | 0.9851 |
| ROC AUC | 0.9492 |
| Brier score | 0.0455 |
| Confusion | tp 35, fp 2, tn 132, fn 7 |

**Reading the coefficients carefully.** The page also shows a separate
full-cohort fit so each feature's direction can be discussed. Those standardised
weights are unstable under collinearity — overall and domain scores move
together, so an individual sign can flip even while the model predicts well. The
weights answer "which features move the score?", not "what causes difficulty",
and they are not part of the validated result.

**Limits, stated plainly.** Ground truth is synthetic, so the figures measure the
method against the generator's labels, not clinical outcomes. The task is
state classification, not forecasting: a declining child is positive from onset,
which is easier than predicting onset in advance. The stored `ModelReport` holds
aggregate metrics, coefficients and counts only — no child id, name or
per-child prediction — so the evaluation artefact cannot become a label about a
person.

Regenerate with `python manage.py ml_report` (or `seed_demo --reset`, which runs
it at the end). Only an administrator can open the page; every other role is
refused and the refusal is audited.

## Local development

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
python manage.py migrate
python manage.py seed_demo          # synthetic cohort, 24 children / 84 days
python manage.py runserver
```

Then open http://127.0.0.1:8000/. Demo accounts all use `kito-demo-2026`;
`seed_demo` prints examples of each role.

Useful commands:

| Command | Purpose |
|---|---|
| `python manage.py seed_demo --reset` | Rebuild the synthetic cohort |
| `python manage.py recompute_wellness` | Rebuild every stored score and baseline |
| `python manage.py evaluate_alerts` | Run the alert rules and persist findings |
| `python manage.py evaluate_alerts --dry-run` | Show what would fire without writing |
| `python manage.py backtest_alerts --weeks 8` | Precision, recall and lead time on the synthetic cohort |
| `python manage.py ml_report` | Re-run the offline classifier benchmark and store an aggregate report |
| `python manage.py cohort_report` | Verify the archetypes behave differently |
| `python scripts/check_compat.py` | Fail if anything needs > Python 3.13 |
| `python manage.py check --deploy` | Security posture under production settings |

## Layout

```
config/      settings, urls, wsgi
core/        User + Role, School, AuditLog, permissions, mixins, audit helpers
children/    Child, Guardianship, Mentorship, ConsentRecord
domains/     the four wellness modules (shared base + per-domain models)
analytics/   scoring engine, baselines, SVG charts, offline model benchmark, commands
alerts/      deterministic rules, alert engine, safeguarding screen, case workflow
feedback/    weekly guardian pulse and aggregate participation
messaging/   adult-to-adult threads about a child (append-only, audited)
templates/   server-rendered pages
static/      hand-written CSS and vanilla JS (no build step)
```

## Deployment

See `DEPLOY.md`. Target: PythonAnywhere, always-on, SQLite.

## Compatibility

Developed on Python 3.14, deployed on Python 3.13. Django 5.2.8+ supports both.
`vermin --target=3.13` is run before every deploy to guarantee the codebase has
no 3.14-only syntax or standard-library usage.
