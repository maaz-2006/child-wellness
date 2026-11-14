# 5. Implementation

## 5.1 Technology and repository layout

The artefact is a Django 5.2 LTS application (Django Software Foundation, 2025).
Django was chosen because
authentication, an ORM with migrations, forms, CSRF protection, template
inheritance and a tested admin are already coherent, so the project could spend
its week on the parts that are actually novel rather than on rebuilding session
handling. The version pin is `Django>=5.2.8,<5.3`: 5.2.8 is the first release
that supports the Python 3.14 interpreter used locally, while the host runs 3.13.

| Layer | Choice | Note |
|---|---|---|
| Language | Python 3.14.6 local, 3.13 on host | `scripts/check_compat.py` rejects syntax the host cannot parse |
| Framework | Django 5.2.19 | LTS, server-rendered |
| Database | SQLite | one school; a single file on the host |
| Static files | WhiteNoise | no web-server static configuration |
| Front end | Django templates, one CSS file, 31 lines of JavaScript | no build step |
| Tests | Django `TestCase` | 270 tests, in-memory database |

The repository is organised by responsibility, not by technical layer:

```text
config/        settings, root URLs, WSGI
core/          User, School, AuditLog, permissions, mixins, dashboards
children/      Child, Guardianship, Mentorship, ConsentRecord
domains/       four capture modules, row-level access, note filtering
analytics/     scoring, baselines, SVG charts, cohort views, ML benchmark
alerts/        rules, engine, safeguarding screen, case workflow
feedback/      weekly guardian pulse
messaging/     adult-to-adult threads
templates/     32 templates
static/        one stylesheet, one progressive-enhancement script
```

There are 108 Python files and 13,495 lines of Python, 32 templates and 2,844
lines of template, 740 lines of CSS and 31 lines of JavaScript. Those figures are
small on purpose: every line is code the project has to defend, and there is no
generated or vendored front-end bundle inflating them.

## 5.2 The permission gate

`core/permissions.py` is the single authority. Access levels are an ordered
`IntEnum`, so one comparison answers "is this enough":

```python
class Access(IntEnum):
    NONE = 0
    AGGREGATE = 1
    SUMMARY = 2
    READ = 3
    WRITE = 4
    MANAGE = 5
```

The matrix is a dictionary keyed by `(role, relation)` and then by resource. It
contains 56 matrix entries over 14 resources, 38 of which grant something above
`NONE`. `require_access` resolves the
relation, looks up the grant, compares it with the required level, and raises
`PermissionDenied` on failure. There is no `return True` fallback: a missing key
is `NONE`, which is the fail-closed property in one line.

Relationship resolution is a separate function because it needs the database, not
just the request. A guardian passes only when the guardianship is active **and**
consent has been granted **and** it has not been revoked. A mentor passes only
while the mentorship is active. A child resolves to `SELF` for their own profile
and to nothing for any other child. An administrator resolves to `INSTITUTION`
and then receives the deliberately narrow institution grants.

Enforcement lives in `core/mixins.py`. `ChildScopedMixin.dispatch` resolves the
child from the URL, calls `require_access` and only then runs the view body:

```python
def dispatch(self, request, *args, **kwargs):
    self.child = get_object_or_404(Child, pk=kwargs["child_id"])
    permissions.require_access(
        request.user, self.child, self.required_resource, self.required_access
    )
    return super().dispatch(request, *args, **kwargs)
```

Because the check is in `dispatch`, a view cannot forget it by returning early,
and a new view that inherits the mixin is protected before its first query. A
refusal is a 403, not a redirect: a redirect hides an access-control bug as a
navigation quirk and makes the denial harder to audit.

Two layers sit below the matrix. `domains/access.entries_for` decides which rows
inside a page are visible, and the note filter decides whether the free-text note
on a visible row is visible. A mentor with `SUMMARY` on emotional data therefore
sees adult observations and check-ins the child chose to share, never a private
note. Keeping this in one function is what stops each list view from inventing a
slightly different filter.

## 5.3 Capture modules

All four domains share an abstract base with `child`, `recorded_by`, `source`,
`occurred_on`, `note`, `note_visibility` and timestamps. Concrete models add
typed columns and constraints: marks are `score / max_score` with a check that the
score does not exceed the maximum; attendance is one row per child per day; social
observation stores five 1–5 dimensions; habits store sleep hours, activity
minutes, screen minutes, a nutrition rating and a breakfast flag.

Two implementation decisions carry most of the weight:

- **The source is derived from the role.** `source_for(user)` maps a child to
  `SELF`, a guardian to `GUARDIAN` and a mentor to `MENTOR`. The form never
  offers a choice. The stored source is what the row gate uses later, so a
  browser-supplied value would make the gate decorative.
- **Note visibility is per row and defaults to private.** A child can keep a note
  to themselves, share it with mentors, or share it with all adults who already
  have access. This lets a child use the check-in as a diary without turning it
  into a disclosure channel by accident.

Habit rows are keyed by `(child, day, source)`, so a child, a guardian and a
mentor can each describe the same day. A second reporter is told the day is
already covered rather than silently overwriting the first.

The child check-in has no child id in the URL at all. It resolves the child from
the session, so there is no identifier to tamper with. This is a small example of
removing an attack surface by design rather than validating it later.

## 5.4 Scoring implementation

`analytics/scoring.py` holds the whole method. The public entry points are
`recompute_child(child, as_of)` and `recompute_all(as_of)`. Recompute is
idempotent: the stored windows for the child are deleted and rebuilt inside a
transaction, so the same entries always produce the same rows.

The pipeline is:

1. Load entries in the 56-day window that ends at `as_of`.
2. Reduce each entry to a per-day value in 0–1 (ratings via `(x−1)/4`, marks via
   `score / max_score`, habits via a mean of five bounded components).
3. For each of eight rolling seven-day windows, compute the mean daily value per
   domain, skip domains with no data, and combine present domains with weights
   `0.40 / 0.25 / 0.20 / 0.15`, renormalised by the weights present.
4. Write a row only when the domain has data; write an overall row only when at
   least two domains are present.
5. Attach a confidence label from the distinct-day count, using per-cadence
   thresholds, and stamp `method_version = "1.0"`.
6. Recompute the 28-day personal baseline from the stored weekly series.

Two details are worth recording because they are easy to get wrong. First, the
week is rolling, not calendar-aligned: the latest window always ends today, so a
new entry appears immediately instead of waiting for Monday. Second, the baseline
uses population standard deviation of the child's own recent scores and is
clamped to a minimum spread of five points before it is used as a z-score
denominator; otherwise a very stable child produces enormous z-scores from a
two-point change.

Charts are generated in `analytics/charts.py` as inline SVG strings. The axis is
fixed at 0–100, a missing window breaks the path into segments, and isolated
points are drawn as circles. No chart library is loaded, the chart prints to PDF,
and the same values are rendered in a `<details>` table.

## 5.5 Alert engine

`alerts/rules.py` is a pure function of stored numbers: it reads scores,
baselines and pulse rows and returns `Finding` objects with a rule key, tier,
evidence dictionary and human-readable summary. It writes nothing.

`alerts/engine.py` persists findings. Its semantics are the part that matters:

- one open alert per `(child, rule_key)`, with a database uniqueness constraint
  on `(child, rule_key, period_end)`;
- `occurrences` increments only when the evaluation date differs from
  `last_seen_on`, so an hourly cron is harmless;
- the tier is `max(existing, new)` while an alert is open, never a downgrade;
- a closed alert is not reopened for the same period, so a scheduled run cannot
  overturn a person's decision;
- the transaction uses `select_for_update` so two concurrent runs cannot both
  create the first alert;
- assignment prefers the school's designated safeguarding lead for urgent and
  safeguarding findings, then the child's active mentorships.

Every state change writes an `AlertEvent`. The model refuses updates and deletes,
so the case timeline is append-only and a resolution cannot be quietly edited.

`alerts/safeguarding.py` screens free text against a short phrase list in four
categories. On a match it returns a category and the source entry reference. The
engine stores those and never the note. The test suite asserts both directions:
benign text does not match, and the stored alert does not contain the disclosure.

## 5.6 Messaging

`messaging/services.py` holds the rules, and views call it rather than creating
`Message` rows. A thread's audience is computed from current relationships: all
active mentors and all consented guardians of that child. It is not a stored
member list, so ending a mentorship or revoking consent removes access on the
next request without deleting history.

`Message.save()` raises on update and `Message.delete()` raises on delete.
`MAX_BODY` is 4,000 characters and an empty body is rejected. A closed thread is
readable but not writable. Read markers are stored separately and are explicitly
not authorisation: they only decide whether the inbox says "1 new message".

`messaging/admin.py` registers nothing. Even a superuser opening
`/django-admin/` cannot browse threads, because the models are absent from the
admin registry. The platform administrator role additionally has
`MESSAGE: NONE`, so the restriction is enforced at both layers.

## 5.7 Offline ML benchmark

`analytics/ml.py` is pure Python and has no production caller other than the
`ml_report` management command and the admin-only report page. It builds one
example per child per weekly snapshot, using 13 numeric features: latest and
prior mean overall score, four-week change, deviation from the child's own recent
range, the four domain scores, the share of domains at or below 50, domain
coverage, and three guardian-pulse features (wellbeing, support, missing flag).

Features are standardised on the training fold only. The model is a
ridge-penalised logistic regression fitted by iteratively reweighted least
squares, with a hand-written Gaussian elimination solver and partial pivoting.
There is no hyper-parameter search: L2 is fixed at 0.05 and the threshold at 0.5
before evaluation, because tuning on the evaluation data would make the benchmark
optimistic.

Validation is leave-one-child-out. Every snapshot belonging to the held-out child
is predicted by a model trained on the other children, which prevents the same
child's pattern leaking into training. Folds without both classes are skipped and
counted. The stored `ModelReport` contains aggregate metrics, the confusion
matrix, standardised coefficients and the feature list. It contains no child
identifier, no per-child prediction and no free text.

## 5.8 Front end

Templates extend a single `base.html` with role-aware navigation. A link that
would be refused is not rendered, but the gate is still enforced if the URL is
typed, so hiding a link is convenience rather than security.

The stylesheet uses custom properties for colour, spacing and type, with a small
set of components: cards, badges, tables, forms, flash messages and chart
containers. Layout is CSS Grid and Flexbox; there is no framework and no utility
class layer. Status is never communicated by colour alone: every badge has text,
and every chart has a table alternative.

The 31-line script does three non-essential things: confirm `data-confirm`
actions, dismiss flash messages after six seconds, and fill a `data-now` label.
Every page works with JavaScript disabled; there is no fetch call, no client-side
render and no client-side authorisation.

## 5.9 Deployment

The application is deployed to PythonAnywhere at
`https://Maaz2006.pythonanywhere.com` on the free tier, with Python 3.13 and
SQLite. The WSGI file is the only place production environment variables live:
`DJANGO_SECRET_KEY`, `DJANGO_DEBUG=false`, `DJANGO_ALLOWED_HOSTS` and
`DJANGO_CSRF_TRUSTED_ORIGINS`. Settings read them with no insecure production
fallback.

`collectstatic` writes to `staticfiles/`, which is mapped at `/static/`;
WhiteNoise serves the files from the WSGI process, so there is no separate static
server and no `/media/` mapping because the platform accepts no uploads
(WhiteNoise project, 2025).

Deployment of a change is `git pull`, `pip install -r requirements.txt`,
`migrate`, optionally `recompute_wellness` and `evaluate_alerts`,
`collectstatic`, then **Reload**. Reload is required because disk changes are not
picked up by the running process. The full procedure, including the exact Web-tab
fields and a troubleshooting section, is in `DEPLOY.md`.

`/healthz/` returns `{"status": "ok", "database": "ok", "debug": false}` and
touches the database with a trivial query, so it proves the process and the
database rather than only the HTTP server. It exposes no configuration.

## 5.10 Management commands

| Command | Purpose | Safe to re-run |
|---|---|---|
| `seed_demo --reset` | rebuild a labelled synthetic cohort, scores, pulse, messages, alerts and a model report | yes, demo only |
| `recompute_wellness` | rebuild stored scores and baselines | yes |
| `evaluate_alerts` | recompute scores, then run rules and persist findings | yes |
| `backtest_alerts --weeks 8` | replay rules against labelled trajectories and print precision, recall and detection delay | yes, restores scores |
| `ml_report` | run the offline benchmark and store one aggregate report | yes |
| `cohort_report` | print a text summary of the cohort for the evaluation chapter | yes |

`seed_demo` refuses to run twice without `--reset` or `--append`, because a
silently doubled cohort looks like a rendering bug. It sets a designated
safeguarding lead before evaluating alerts, because urgent assignment needs a
named person at creation time. `backtest_alerts` recomputes historical windows
one as-of date at a time and then restores the current scores; it does not write
alerts.

## 5.11 Defects found and fixed

These are recorded because the process of finding them is part of the evidence
that the artefact was tested rather than assumed.

| Defect | Symptom | Fix |
|---|---|---|
| Consent revocation was not part of the relationship test | A guardianship whose consent had been revoked still resolved to a guardian relation, so the gate stayed open after withdrawal | `resolve_relation` now requires `consent_revoked_at__isnull=True`; permission and messaging tests revoke consent and assert 403 |
| Four-week delta used the wrong reference window | The ML feature labelled "change over four weeks" compared the latest score with a window three weeks back, overstating or understating the trend | The delta now uses the fifth-from-last weekly score, which is exactly four weeks earlier, and the feature test pins the vector length and reference point |
| A resolved alert could be recreated by a later run on the same day | A mentor resolved a case in the morning; an afternoon evaluation recreated the same alert for the same period and undid the decision | The engine refuses to create an alert when a closed row already exists for `(child, rule_key, period_end)`; covered by `test_a_resolved_alert_is_not_recreated_by_a_later_run_same_day` |
| `/children/<id>/wellness/` collided with the generic domain route | The domain slug pattern matched `wellness` and returned a 404 from the domain registry instead of the trend page | The trend route is declared under the child prefix before the generic domain route; the comment in `children/urls.py` records why |
| Scripted sign-in to the live HTTPS host returned 403 | The CSRF token and cookie were valid, but Django also enforces the `Referer` check over HTTPS, and the script sent none | Live verification sends `Referer: https://maaz2006.pythonanywhere.com/login/`; documented in `DEPLOY.md` under Troubleshooting |

The last defect is worth a sentence more. The failure looked exactly like a bad
CSRF token because `DEBUG=false` returns the same generic page, so the first
hypothesis was a trusted-origin mismatch. Testing both lowercase and capitalised
`Origin` headers showed the origin was irrelevant; adding the `Referer` made the
same request succeed. The lesson is recorded in the deploy guide because it will
recur for anyone who automates a check against the live site.

## 5.12 Code metrics

| Metric | Value |
|---|---|
| Django apps | 7 |
| Project models | 22 |
| Python files / lines | 108 / 13,495 |
| Templates / lines | 32 / 2,844 |
| CSS lines | 740 |
| JavaScript lines | 31 |
| Automated tests | 270 |
| Permission matrix entries / access grants / resources | 56 / 38 / 14 |
| Database migrations | 11 |

The test-to-code ratio is high because access rules, scoring arithmetic and alert
lifecycle are exactly the places where a plausible-looking implementation can be
quietly wrong. The next chapter turns those tests and the synthetic cohort into
measurements.

## 5.13 Summary

The implementation keeps each rule in one place: the matrix decides access, the
row gate decides visibility, the scoring module decides arithmetic, the rules
module decides findings, the engine decides persistence, and the services module
decides messaging. That structure is what made it possible to test the system's
claims directly rather than testing that pages merely return 200.
