# Submission pack

Everything needed to hand in, demonstrate and defend the project. Replace every
`[SQUARE BRACKET]` placeholder before submitting.

## 1. Submission checklist

### Documents

- [ ] Abstract, chapters 1–8 assembled in the university template.
- [ ] Title page uses the correct programme, module code, supervisor and date.
- [ ] Word count inserted and within the handbook limit (body only if that is the
      rule).
- [ ] Table of contents, list of figures and list of tables generated from
      heading styles, not typed by hand.
- [ ] Every Mermaid diagram exported to PNG at 2x and inserted with a numbered
      caption.
- [ ] Every figure and table is referred to in the text.
- [ ] Harvard reference list checked: alphabetical, every in-text citation
      present, every listed work cited.
- [ ] British spelling checked (`organisation`, `behaviour`, `recognise`).
- [ ] `[STUDENT NAME]`, `[STUDENT ID]`, `[MODULE CODE]`, `[PROGRAMME]`,
      `[SUPERVISOR]`, `[UNIVERSITY]`, `[SUBMISSION DATE]`, `[WORD LIMIT]` and
      `[ETHICS REFERENCE]` replaced everywhere.
- [ ] Ethics statement included as an appendix or separate submission, following
      the handbook.
- [ ] Participant documents included **only** if the handbook asks for them, and
      the "templates only" banner left visible.
- [ ] Report rewritten in your own voice. Do not submit the drafts unchanged.

### Artefact

- [ ] Repository is public (or shared with the marker) at
      <https://github.com/maaz-2006/child-wellness>.
- [ ] `README.md` explains how to run the project from a clean clone.
- [ ] `DEPLOY.md` matches the live host configuration.
- [ ] No `.env`, secret key, real password or personal data is committed.
- [ ] `python manage.py test` passes (270 tests).
- [ ] `python manage.py makemigrations --check` reports no changes.
- [ ] `python manage.py check --deploy` reports only the two documented warnings.
- [ ] `python scripts/check_compat.py` passes.
- [ ] `python manage.py seed_demo --reset` rebuilds the demo without errors.
- [ ] Live URL responds: <https://Maaz2006.pythonanywhere.com/healthz/>.
- [ ] Live sign-in works for each role.
- [ ] Demo accounts documented, with the demo password clearly marked as demo
      only.
- [ ] Uptime pinger points at `/healthz/`, not `/health`.
- [ ] Screenshots use synthetic names only and crop browser chrome.

### Viva

- [ ] Laptop charged; charger packed.
- [ ] Two browsers or one normal and one private window, pre-signed-in as
      different roles.
- [ ] Live URL bookmarked; local copy running as a fallback.
- [ ] Printed binder: URL, accounts, architecture diagram, permission matrix,
      alert rules, evaluation summary, ethics statement.
- [ ] Demo script rehearsed to ten minutes.
- [ ] Answers to the questions in Section 4 rehearsed aloud.

## 2. Ten-minute demo script

The aim is to show the design argument, not every page. Pre-open four windows:
child, parent, mentor, admin. Do not sign in and out during the demo.

| Time | Window | Action | Point to make |
|---|---|---|---|
| 0:00–0:45 | — | One sentence on the problem and the artefact | four domains, one school, role-aware access |
| 0:45–2:00 | Child | Open `/checkin/`, submit a check-in | one minute, optional note, no score or risk label anywhere on the child's page |
| 2:00–3:15 | Parent | Open the child page and wellness trend | trend, baseline band, gap, "no data" state; the parent sees their own child only |
| 3:15–3:45 | Parent | Open `/messages/` and a thread | append-only notice; reply form; no delete or edit |
| 3:45–5:15 | Mentor | Open `/alerts/`, then a case | queue is small; evidence, tier, named owner, append-only timeline; acknowledge, then show that an urgent alert has no share button |
| 5:15–6:15 | Mentor | Open a child's emotional page | observations and shared check-ins only; private note is filtered; the row gate is separate from the page gate |
| 6:15–7:00 | Mentor | Open a message thread | adult-to-adult; the child and admin are refused |
| 7:00–8:15 | Admin | `/cohort/wellness/`, `/cohort/model/` | aggregates and distributions only; no child names; model page states it is offline and not a decision system |
| 8:15–9:00 | Admin | `/admin/permissions/` | the matrix rendered from the code that enforces it; 56 entries, 38 access grants, 14 resources |
| 9:00–9:30 | Child | Type a mentor URL directly | 403, not a redirect; refusal is the feature |
| 9:30–10:00 | — | Numbers and limits | 270 tests, backtest 7/7 with 3 child-level false positives, AUC 0.949 offline, no real participants |

If a page is slow, narrate the design while it loads. If the live site fails,
switch to the local copy and say so; a fallback is professionalism, not failure.

## 3. Numbers to have on one card

| Fact | Value |
|---|---|
| Tests | 270, all passing, 62.8 s |
| Apps / models | 7 / 22 |
| Python | 108 files, 13,495 lines |
| Templates / CSS / JS | 32 / 740 lines / 31 lines |
| Permission matrix | 56 entries, 38 access grants, 14 resources, 4 role/relationship rows |
| Stored scores (demo) | 895 |
| Alerts (demo) | 17: 3 urgent, 13 concern, 1 watch |
| Backtest | 7/7 detected, 0 missed, 3 child-level false positives, precision 0.70, recall 1.00, median 10 days from onset |
| ML | 176 snapshots, 22 children, accuracy 0.9489, AUC 0.9492, recall 0.8333, specificity 0.9851, Brier 0.0455 |
| Confusion | TP 35, FP 2, TN 132, FN 7 |
| Deploy check | 2 warnings, both intentional (HSTS and SSL redirect at the proxy) |
| Live checks | all four roles verified, 2026-11-15 |

## 4. Viva questions and answer skeletons

**"Why not just use a commercial platform?"**
Because the interesting question is the access model, and a closed product cannot
be inspected or tested. The project is an argument about governance, not a claim
to out-build a vendor.

**"Why Django?"**
Authentication, ORM, migrations, forms, CSRF and templates are coherent and
tested. The week went on permissions, scoring and alerts rather than on session
handling. The cost is a larger dependency and some framework conventions to learn.

**"Why not Flask or FastAPI?"**
They are good frameworks, but they would have required assembling auth, admin,
forms and CSRF from parts. That is more code to defend in the time available, and
more places for a security bug.

**"Why not scikit-learn?"**
It would add a compiled dependency to a free host and hide the numerical method.
IRLS on 13 standardised features is small enough to audit and fast enough for an
offline command. For a production model, a library would be the right choice.

**"Is the ML real, or is it decoration?"**
It is a real benchmark with real leave-one-child-out validation, and it is
deliberately not connected to care. It answers whether the features carry signal;
it does not claim to predict a child's future.

**"How do you know the permissions work?"**
128 tests across the permission, domain and messaging suites, plus live checks as
all four roles. The strongest tests are the refusals: unrelated mentor, revoked
consent, administrator reading emotional content, child reading a message thread.

**"Why can't a child see their own score?"**
A risk label can harm the child and the child cannot contest it. The child can see
their own check-ins and habits and can ask an adult. This is a deliberate
paternalism with a narrow scope.

**"Why can't the head see everything?"**
Because a head does not need a child's diary to run the school, and an
all-powerful administrator undermines the promise that makes children disclose.
The head can govern the cohort through aggregates and configuration.

**"What happens when data is missing?"**
No row, no zero. The chart shows a gap, the table says "no data", and the rules
treat a gap as a gap. `no_recent_data` is a watch for a human, not a decline.

**"Why seven-day rolling windows?"**
A calendar week creates a Monday cliff and delays feedback. Rolling windows end
today, so a new entry is visible immediately. Eight windows give 56 days of trend
without an unbounded query.

**"Why those weights?"**
Emotional 0.40, academic 0.25, habits 0.20, social 0.15, renormalised over the
domains present. They express the project's judgement that emotional wellbeing is
the primary dimension. They are configurable in one place, not scattered.

**"How do you prevent alert fatigue?"**
One rolling alert per rule per child, severity gated by confidence, only the most
severe overall finding kept, no duplicate on a same-day re-run, no auto-resolve,
and a named owner. The backtest's three false positives are stated openly.

**"What about a false positive?"**
It costs a conversation. The design makes the alert non-punitive, requires a note
to close, and never shares an urgent alert with a family through the platform. The
right response is threshold review with the safeguarding lead, not pretending the
cost is zero.

**"How would this scale to 1,000 children?"**
PostgreSQL, pagination, a background job for recompute and evaluation, and
indexes on the hot paths. The ORM makes the database a configuration change; the
background job is the real work. SQLite is a documented limitation.

**"What is the lawful basis under GDPR?"**
For a real pilot, public task for the school's pastoral function and explicit
consent for research analysis, with a special-category condition. The ethics
statement sets this out; the submitted project processes no real data.

**"What would you do with another month?"**
A supervised pilot with a pre-registered protocol, threshold review, calibration
and fairness audit, PostgreSQL, retention automation, and accessibility testing
with assistive technology.

**"What is the biggest weakness?"**
No real users. The design is argued, not observed. The access model and scoring
are tested; usability, trust and effect are not. The ethics statement is the
protocol that would close that gap.

**"What is novel here?"**
Not the algorithm. The contribution is the combination: a declarative
relationship-aware matrix rendered from the enforcing code, gap-aware scoring, a
human-owned alert lifecycle, a safeguarding screen that does not copy the text,
and an ML layer that is measured but not deployed.

**"Why are messages append-only?"**
Because a message thread about a child is a record that may matter later. Editing
or deleting destroys the shared account of what was said. Corrections are new
messages.

**"Why no email or push notifications?"**
They would move sensitive content into an unlogged channel. A content-free nudge
is possible future work; the detail must stay behind authentication.

**"Why 403 rather than a redirect?"**
A redirect hides the refusal and makes an access-control bug look like navigation.
A 403 is auditable and unambiguous. The trade-off is that an authenticated user
can infer a child exists; within one school that is low risk.

**"Did you do a usability study?"**
No. That is stated as a limitation, not hidden. The forms are short by design, but
completion time and trust are untested.

**"How do I know the numbers are not made up?"**
Every figure can be regenerated: the test suite, `seed_demo`, `backtest_alerts`,
`ml_report`, `cohort_report` and `check --deploy`. The commands are in the
appendix.

## 5. Marking map

Use this to point a marker at the strongest evidence for each criterion.

| Criterion | Where to look |
|---|---|
| Problem definition and context | Chapter 1; Section 2.2; the four-domain rationale in 2.1 |
| Requirements and analysis | Chapter 3; FR1–FR42, NFR1–NFR14, scenarios S1–S8, traceability 6.10 |
| Design | Chapter 4: context, containers, ER, permission matrix, scoring, alerts, messaging, ML, security, alternatives |
| Implementation quality | Chapter 5; the repository structure; one authority per rule; 13,495 lines with no vendored front end |
| Testing | Section 6.2–6.4; 270 tests; refusal-weighted suite |
| Evaluation | Sections 6.5–6.9: backtest, ML benchmark, timings, deploy check, live verification |
| Critical reflection | Chapter 7; limitations table; threats to validity 6.11 |
| Ethics and professionalism | Ethics statement; participant templates; privacy-by-design in 4.5 and 7.4 |
| Communication | This pack; demo script; report structure; assembly guide |
| Reproducibility | Appendix H; `README.md`; `DEPLOY.md`; management commands |

## 6. Quality-assurance commands

Run these before submitting and paste the output into your evidence log.

```bash
# 1. All tests
python manage.py test

# 2. No missing migrations
python manage.py makemigrations --check --dry-run

# 3. Production configuration check
#    Windows PowerShell:
$env:DJANGO_DEBUG="false"
$env:DJANGO_SECRET_KEY="deploy-check-only-key-that-is-long-enough-0123456789abcdef"
$env:DJANGO_ALLOWED_HOSTS="maaz2006.pythonanywhere.com"
$env:DJANGO_CSRF_TRUSTED_ORIGINS="https://maaz2006.pythonanywhere.com"
python manage.py check --deploy

# 4. Host-interpreter compatibility
python scripts/check_compat.py

# 5. Rebuild the demo and the derived data
python manage.py seed_demo --reset

# 6. Reproduce the evaluation numbers
python manage.py backtest_alerts --weeks 8
python manage.py ml_report
python manage.py cohort_report

# 7. Live health
curl -s https://Maaz2006.pythonanywhere.com/healthz/
```

Expected: 270 tests pass; no migration changes; exactly `security.W004` and
`security.W008` warnings; compatibility OK; seed prints 24 children; backtest
prints 7 positives, 15 negatives, 7 detected, 3 false positives, precision 0.70,
recall 1.00, median 10 days; health returns `{"status": "ok", "database": "ok",
"debug": false}`.

## 7. Emergency fallbacks

| Problem | Fallback |
|---|---|
| Live site down | run locally, use `python manage.py runserver`, narrate that the same code is deployed |
| Live sign-in fails | use the pre-signed-in local windows; do not debug in front of the marker |
| A page is slow | narrate the design; the local copy is the backup |
| A demo account is locked | use another account with the same role; the seeded password is `kito-demo-2026` |
| Projector fails | printed binder has the architecture, matrix, rules and numbers |
| A question you cannot answer | say what you measured, what you did not, and what you would test next. Do not invent a number. |

## 8. Final honesty check

Before you submit, read these three sentences and make sure you are comfortable
saying them aloud:

1. "No real children, families or staff were involved; the cohort is synthetic."
2. "The alert thresholds are not clinically validated, and the ML model is an
   offline benchmark, not a deployed predictor."
3. "The access model and scoring are tested; usability and effect are not."

If you can say those without hedging, the rest of the defence is straightforward.
