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

## Local development

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo          # synthetic cohort (added in the next step)
python manage.py runserver
```

Then open http://127.0.0.1:8000/ and sign in with a seeded account.

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
