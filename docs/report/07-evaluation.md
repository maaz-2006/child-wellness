# 6. Evaluation

## 6.1 Evaluation strategy

The artefact makes six claims, and each is measured a different way:

| Claim | Evidence |
|---|---|
| Access is enforced as designed | 270-test suite, with 128 tests across the permission, domain and messaging suites concerned directly with access, visibility or refusal |
| Scoring is reproducible and does not invent data | unit tests on daily values, windows, confidence, gaps and idempotence |
| Alerts are explainable and operationally safe | rule tests, engine lifecycle tests, and a backtest against labelled trajectories |
| The structured features carry signal | leave-one-child-out benchmark of a 13-feature logistic regression |
| The system is usable at the target scale | request timing on the seeded cohort |
| The deployed system behaves like the tested one | live, authenticated checks against the public URL |

No human participants were involved, so there is no usability study, interview or
questionnaire in this chapter. That is a limitation, not an omission, and it is
carried into Section 7.5.

## 6.2 Automated test suite

The suite runs with `python manage.py test` against an in-memory database. All
270 tests passed in 62.8 seconds on the development machine.

| File | Tests | Focus |
|---|---:|---|
| `core/tests/test_permissions.py` | 31 | relation resolution, matrix completeness, institution scope, enforcement, audit |
| `core/tests/test_views.py` | 9 | health check, login, 404, role dashboards, matrix page |
| `children` (covered across suites) | — | child identity, guardianship and consent are exercised by the permission and domain suites |
| `domains/tests.py` | 59 | row gate, note visibility, check-in, observations, academic/social/habit forms, validation |
| `analytics/tests.py` | 7 | seed command, archetype labels, reset and double-seed guard |
| `analytics/test_scoring.py` | 25 | daily values, weights, confidence, gaps, baselines, idempotence, cohort snapshot |
| `analytics/test_charts.py` | 9 | fixed axis, gap segmentation, dots, band clamping, labels |
| `analytics/test_views.py` | 20 | trend and cohort page access, empty state, audit, no child names |
| `analytics/test_ml.py` | 25 | labels, features, dataset exclusions, IRLS, AUC, LOOCV, aggregate-only report |
| `alerts/tests.py` | 31 | thresholds, gap handling, engine lifecycle, safeguarding, sharing, views |
| `feedback/tests.py` | 16 | pulse submission, visibility, weekly rules, cohort aggregate |
| `messaging/tests.py` | 38 | matrix, inbox scoping, thread access, append-only, closing, admin registration |
| **Total** | **270** | |

The suite is deliberately weighted towards refusal. A test that a mentor can open
an assigned child's page proves very little on its own; a test that an unrelated
mentor receives 403, that the denial is audited, and that the refusal survives a
guessed URL is the property that matters.

## 6.3 Access-control evaluation

The permission suite asserts the matrix from both directions: every expected
grant is allowed, and every adjacent role or relation is refused. The checks that
carry the most weight are:

| Property | Test evidence |
|---|---|
| Consent is a gate, not a checkbox | `test_parent_without_consent_has_no_relation`, `test_revoked_consent_removes_access` |
| An ended mentorship closes access | `test_deactivated_mentorship_removes_access`, `test_mentor_loses_access_when_assignment_ends` |
| A child sees only themselves | `test_child_is_self_only`, `test_child_cannot_open_another_childs_page` |
| A child never sees their own score or alert | `test_child_never_sees_own_score_or_alert`, `test_child_is_refused_their_own_score` |
| The administrator cannot read emotional content | `test_admin_cannot_read_emotional_content`, `test_admin_gets_no_individual_emotional_rows` |
| The administrator sees aggregates, not names | `test_admin_can_open_the_aggregate_page`, `test_aggregate_page_never_names_a_child` |
| A private note stays private | `test_mentor_sees_shared_note_but_not_private_note`, `test_parent_does_not_read_child_private_note` |
| A denial is audited | `test_require_access_raises_and_audits_for_denied_sensitive_read`, `test_refusal_of_the_cohort_page_is_audited` |
| The audit row survives actor deletion | `test_audit_entry_survives_actor_deletion` |
| Every role/relation has a complete row | `test_every_role_and_relation_has_a_row`, `test_no_grants_exist_for_unlisted_relations` |

Two of these deserve comment. `test_every_role_and_relation_has_a_row` fails if a
future developer adds a role or relation without deciding its grants, which turns
"we forgot to think about this case" into a test failure rather than a silent
`NONE`. `test_audit_entry_survives_actor_deletion` asserts that deleting the user
leaves the audit row with a null actor and the role snapshot, so accountability
does not disappear with the account.

The matrix is also rendered at `/admin/permissions/` from the same dictionary
that enforces it. A test opens the page as an administrator and asserts a known
grant appears, so the documentation cannot drift from the code without a failure.

## 6.4 Scoring and chart evaluation

The scoring tests pin the arithmetic rather than the implementation:

- a fully positive emotional day is 1.0 and a fully negative one is 0.0;
- an academic score is a share of the mark, not the raw mark, so `18/20` and
  `9/10` are equivalent;
- habit days use only the measurements present;
- five good days produce 100 with `good` confidence;
- one domain produces no overall score, and overall renormalises over the domains
  present;
- a week with no data produces no row, and the stored series reports `None` for
  that week;
- recompute is idempotent and picks up a changed entry;
- the baseline stores mean and spread, and the chart receives a chart-ready band.

The chart tests assert the properties that make the visual honest: the grid is
fixed at 0–100, a gap breaks the path into separate segments, isolated points are
dots, an empty series draws no geometry, the band is clamped to the axis, and a
zero standard deviation draws no band. These are not cosmetic tests. Auto-scaling
and gap-bridging are the two ways a trend chart can mislead without containing a
single wrong number.

## 6.5 Alert rule backtest

`backtest_alerts --weeks 8` replays the rules over eight weekly evaluation points
against the synthetic cohort's known trajectories. Positives are the `gradual_decline`
and `sudden_event` archetypes; negatives are `healthy` and `recovering`; `sparse`
is excluded because its problem is missing data. The command never writes alerts
and restores the current scores at the end.

| Measure | Result |
|---|---|
| Positive children | 7 |
| Negative children | 15 |
| Detected | 7 |
| Missed | 0 |
| Children with at least one false positive | 3 |
| Child-level precision | 0.70 |
| Child-level recall | 1.00 |
| Median onset-to-first-alert interval | 10 days |
| Evaluation points | 8 weekly, 2026-09-27 to 2026-11-15 |

Three points about interpretation:

1. **This is detection, not prophecy.** The interval is measured from the
   simulated onset to the first alert, so a median of 10 days means the system
   noticed the decline within about a week and a half of it starting. No positive
   child was flagged before onset, and the command reports early flags separately
   if that changes.
2. **The false-positive measure is child-level and deliberately harsh.** A
   negative child counts once if any of the eight evaluation points produced a
   signal. A per-run false-positive rate would look much better and mean much
   less, because the cost in a school is a child appearing in the queue at all.
3. **The ground truth is synthetic.** These figures measure the rules against the
   generator's labels, not against clinical outcomes. The generator and the rules
   share assumptions about what a decline looks like, which flatters both. The
   backtest is evidence of internal consistency, not of clinical validity.

The engine tests cover the operational properties the backtest cannot: one alert
per rule per child, no increment on a same-day re-run, increment once on a later
day, escalation without downgrade, no recreation of a resolved alert on the same
day, urgent assignment to the designated lead, and append-only events.

## 6.6 Offline model benchmark

The benchmark used 176 snapshots from 22 children, with 42 positive and 134
negative examples and 22 leave-one-child-out folds. Every fold trained on 21
children and predicted the held-out child only.

| Metric | Value | Meaning |
|---|---:|---|
| Accuracy | 0.9489 | share of snapshots classified correctly |
| Precision | 0.9459 | of those flagged, the share in a labelled difficult period |
| Recall | 0.8333 | of difficult periods, the share flagged |
| F1 | 0.8861 | harmonic mean of precision and recall |
| Specificity | 0.9851 | of stable periods, the share left unflagged |
| ROC AUC | 0.9492 | ranking quality across all thresholds |
| Positive prevalence | 0.2386 | base rate in the evaluation set |
| Brier score | 0.0455 | mean squared probability error; lower is better |

Confusion matrix:

| | Predicted difficult | Predicted stable |
|---|---:|---:|
| **Actually difficult** | 35 (TP) | 7 (FN) |
| **Actually stable** | 2 (FP) | 132 (TN) |

The model is better at excluding stable periods than at catching every difficult
one, which is the right direction for a benchmark that is *not* making decisions:
a false negative here costs a research observation, not a missed child. The
Brier score of 0.0455 is low partly because the outcome is imbalanced and partly
because the synthetic trajectories are separable; it should not be read as
calibration on real data.

The standardised coefficients are stored for interpretation, not for use. The
largest magnitudes are guardian support (−2.71), emotional score (−2.97), the
share of domains at or below 50 (−2.07), and guardian wellbeing (−1.92). The
positive coefficient on the prior overall mean (1.70) alongside a negative
coefficient on the latest score (−1.00) is a suppression effect: the two features
are strongly correlated, so the model reads the *change* between them rather than
the level of either. This is exactly why individual coefficients should not be
presented to a mentor as reasons. The deterministic rules, which carry the
numbers and the period in the alert, are the explainable path.

The report page is admin-only, audited on view, and contains no child name or
identifier. A test asserts that the stored report holds no child identifiers and
that the page contains no child names.

## 6.7 Performance

Timing was measured with the Django test client on the development machine
against the seeded cohort of 24 children, 4,832 domain rows (including 1,275
check-ins) and 895 stored scores. Each case made 12 requests after warm-up; the
median is reported.

| Page | Median | Minimum | Maximum |
|---|---:|---:|---:|
| Parent dashboard | 5.8 ms | 5.2 ms | 60.2 ms |
| Child detail | 15.8 ms | 14.1 ms | 23.2 ms |
| Child wellness trend | 14.7 ms | 13.2 ms | 19.3 ms |
| Messages inbox | 7.3 ms | 6.5 ms | 9.6 ms |
| Mentor alert queue | 2.9 ms | 2.7 ms | 6.0 ms |
| Cohort wellness | 7.8 ms | 6.7 ms | 11.3 ms |
| Model report | 4.1 ms | 3.2 ms | 7.8 ms |

These are local figures with `DEBUG` on and a warm process; they are useful for
relative comparison, not as a host benchmark. They do show that no routine page
does work proportional to the whole database: the alert queue is quick because it
filters to assigned children, and the cohort page aggregates in the database
rather than loading every child. The single outlier (60 ms on the first dashboard
request) is cold-start work in the process, which is why the median is used.

The synthetic cohort is small by design. A school of 1,000 children would have
roughly forty times the rows; the indexes on `child`, `period_end`, `domain`,
`tier` and `status` are the mitigation, and Section 7.5 states where SQLite would
need to be replaced.

## 6.8 Security and deployment checks

`python manage.py check --deploy` with production variables set reports exactly
two warnings:

| Warning | Decision |
|---|---|
| `security.W004` — `SECURE_HSTS_SECONDS` not set | the host terminates TLS; HSTS is set at the host level, and enabling it in the app without understanding the proxy would be worse than the warning |
| `security.W008` — `SECURE_SSL_REDIRECT` not set | a redirect loop behind a TLS-terminating proxy is a worse failure than the warning it silences; the host already redirects HTTP to HTTPS |

Both decisions are commented in `config/settings.py` so a future maintainer sees
the reasoning rather than "someone ignored the checker".

Other controls verified:

| Control | Evidence |
|---|---|
| CSRF on every state-changing POST | Django middleware; the live empty-reply POST returned the form error rather than writing |
| Session cookie flags | `HttpOnly`, `Secure` and `SameSite=Lax` under `DEBUG=false` |
| Clickjacking | `X-Frame-Options: DENY` |
| MIME sniffing | `X-Content-Type-Options: nosniff` |
| Referrer leakage | strict-origin-when-cross-origin |
| No upload surface | no `FileField`, no `/media/` mapping |
| Admin cannot read messaging | messaging models are absent from the admin registry; test asserts it |
| Append-only timeline | `AlertEvent` and `Message` refuse update and delete; tests assert it |
| Health endpoint | `/healthz/` touches the database and exposes only status, database and debug |

## 6.9 Live verification

The system is deployed at `https://Maaz2006.pythonanywhere.com` (Python 3.13,
SQLite, WhiteNoise). Checks were run on 2026-11-15 against the live host, signed
in as each role, not only against the local test client.

| Account | Request | Result |
|---|---|---|
| signed out | `/healthz/` | 200, `status: ok`, `database: ok`, `debug: false` |
| signed out | `/alerts/`, `/cohort/model/`, `/messages/` | redirect to sign-in |
| `parent.halima` | `/messages/` | 200, one thread |
| `parent.halima` | own thread detail | 200, append-only notice and reply form |
| `parent.halima` | another family's thread | 403 |
| `parent.halima` | `/cohort/model/` | 403 |
| `parent.halima` | `/django-admin/` | redirect to admin sign-in |
| `parent.halima` | own child new-thread page | 200 |
| `parent.halima` | unrelated child new-thread page | 403 |
| `parent.halima` | `/alerts/family/` | 200 |
| `parent.halima` | own child wellness | 200, SVG chart rendered |
| `ruth` (mentor) | `/messages/` | 200, two threads (one not visible to the parent) |
| `ruth` | thread detail | 200, reply and close controls |
| `ruth` | `/cohort/model/` | 403 |
| `ruth` | `/cohort/pulse/` | 403 (administrator only) |
| `ruth` | `/alerts/` | 200 |
| `child.halima` | `/messages/` and a thread | 403 |
| `child.halima` | own wellness page | 403 |
| `child.halima` | own new-thread page | 403 |
| `child.halima` | `/dashboard/` | 200 with check-in card, no score or risk label |
| `MohammedMaaz` (admin) | `/cohort/model/` | 200, aggregate benchmark only |

Two findings from live testing are worth recording. First, the parent and mentor
inboxes legitimately differ: the parent sees only her own child's conversation,
while the mentor sees every thread for the children assigned to her. A guessed
thread id for an unrelated child returns 403, which confirms that the gate is the
child, not the thread. Second, a scripted sign-in initially failed with 403 even
though the CSRF token and cookie were correct. The cause was Django's `Referer`
check over HTTPS; sending the referer made the same request succeed. The
diagnosis and the fix are recorded in `DEPLOY.md` because it will recur.

## 6.10 Requirements traceability

| Requirement group | Evidence |
|---|---|
| FR1–FR6 accounts, access, audit | permission suite (31), `core/test_views` (9), live role checks |
| FR7–FR16 capture and validation | domain suite (59), including consent gate, future dates, mark bounds, empty habit log and per-source rows |
| FR17–FR23 scoring and analytics | scoring suite (25), chart suite (9), analytics views (20), cohort report |
| FR24–FR31 alerts and response | alert suite (31), engine lifecycle tests, backtest 6.5, live family page |
| FR32–FR33 guardian pulse | feedback suite (16), pulse rule tests, cohort aggregate page |
| FR34–FR37 messaging | messaging suite (38), live parent/mentor/child checks |
| FR38–FR40 ML benchmark | ML suite (25), stored aggregate report, live admin page |
| FR41 health check | `test_healthz_reports_database`, live `/healthz/` |
| FR42 synthetic cohort | seed suite (7), reset and double-seed guard |
| NFR1–NFR14 | performance 6.7, security 6.8, deploy check, live verification 6.9 |

Every must-have requirement has at least one direct test. The two should-have
items with the weakest direct evidence are attendance (captured and scored, but
not separately surfaced as a trend) and social observation volume (the synthetic
generator produces fewer rows than a real mentor would). Both are stated in
Section 7.5 rather than papered over.

## 6.11 Threats to validity

**Internal validity.** The synthetic generator and the alert rules share a model
of what a decline looks like: a fall in mood, habits and marks together. The
backtest therefore measures whether the rules recover a signal the generator put
there, not whether real declines look like that. The 7/7 recall should be read as
"the rules are consistent with the generator", not "the rules will catch every
child".

**Construct validity.** The four domains are a pragmatic operationalisation of a
multi-dimensional construct. A high score is not health, and a low score is not a
diagnosis. The ML labels are the generator's current state, not a clinical
outcome and not a forecast.

**External validity.** One synthetic school, 24 children, one generator seed, 84
days of history. The cohort is deliberately small enough to inspect and too small
to support a general claim. The ML benchmark has 22 children and 176 snapshots;
leave-one-child-out is the right split, but 22 folds is still 22 children.

**Conclusion validity.** Thresholds were chosen by design and then tested, not
tuned on the evaluation data. That avoids the most common form of optimistic bias
in a student project, but it also means the thresholds are not optimised for
anything. A different school would need to review them against its own population
and safeguarding policy.

**Ecological validity.** No child, parent or mentor used the system. The forms are
short by design, but whether a real child completes a check-in in under a minute,
or whether a mentor trusts the queue, is untested. The accessibility review is
against WCAG guidance, not with disabled users. These are the first things a
real pilot should measure.

**Performance validity.** Timings come from the development machine with a warm
process and `DEBUG` on. They establish that no page does pathological work; they
do not predict the host under concurrent load, and SQLite serialises writes.

## 6.12 Summary

The evaluation supports four modest conclusions. Access control behaves as
designed across 128 access-focused tests and a live four-role check. Scoring is
reproducible, gap-aware and idempotent. The alert rules detected all seven
simulated declines with three child-level false positives and a median detection
delay of ten days. The offline classifier separates the synthetic labels well
enough to show the features carry signal, and is correctly kept out of the care
path. Chapter 7 discusses what these results mean, what they do not mean, and
what would have to change before a real school could use the system.
