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
| `python manage.py cohort_report` | Verify the archetypes behave differently |
| `python scripts/check_compat.py` | Fail if anything needs > Python 3.13 |
| `python manage.py check --deploy` | Security posture under production settings |

## Layout

```
config/      settings, urls, wsgi
core/        User + Role, School, AuditLog, permissions, mixins, audit helpers
children/    Child, Guardianship, Mentorship, ConsentRecord
domains/     the four wellness modules (shared base + per-domain models)
analytics/   scoring, baselines, anomaly detection, management commands
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
