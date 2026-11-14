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
standard deviation. That personal band is what the charts shade and what D5's
alert engine will compare against — not a population average, because the
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
| `python manage.py cohort_report` | Verify the archetypes behave differently |
| `python scripts/check_compat.py` | Fail if anything needs > Python 3.13 |
| `python manage.py check --deploy` | Security posture under production settings |

## Layout

```
config/      settings, urls, wsgi
core/        User + Role, School, AuditLog, permissions, mixins, audit helpers
children/    Child, Guardianship, Mentorship, ConsentRecord
domains/     the four wellness modules (shared base + per-domain models)
analytics/   scoring engine, baselines, SVG charts, management commands
alerts/      alert engine, case workflow
feedback/    structured stakeholder feedback
templates/   server-rendered pages
static/      hand-written CSS and vanilla JS (no build step)
```

## Deployment

See `DEPLOY.md`. Target: PythonAnywhere, always-on, SQLite.

## Compatibility

Developed on Python 3.14, deployed on Python 3.13. Django 5.2.8+ supports both.
`vermin --target=3.13` is run before every deploy to guarantee the codebase has
no 3.14-only syntax or standard-library usage.
