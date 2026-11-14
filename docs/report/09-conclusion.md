# 8. Conclusion

## 8.1 Objectives revisited

| ID | Objective | Outcome |
|---|---|---|
| O1 | Derive requirements from guidance, safeguarding practice and a single-school workflow | Met. 42 functional and 14 non-functional requirements, each traced to a test or measured behaviour (Section 6.10). The derivation is documented, but it was not co-designed with users; this is stated in 7.5. |
| O2 | Design access around why a user is connected to a child, not only their role | Met. 56 matrix entries, 38 of them access grants, over 14 resources; fail-closed, rendered from the enforcing code, and exercised by 128 access-focused tests plus live role checks. |
| O3 | Implement structured capture and a transparent, versioned scoring method across four domains | Met. Four capture modules with validation, eight rolling windows, per-cadence confidence, a 28-day personal baseline and `method_version = 1.0`. Gaps produce no row. |
| O4 | Implement explainable early-warning alerts with an owner, case workflow and safeguarding routing | Met. Nine deterministic rules, one rolling alert per rule per child, escalation without downgrade, append-only timeline, named owner, urgent routing to the designated lead. |
| O5 | Implement adult-to-adult communication and an offline evaluation of the structured features | Met. Child-scoped append-only threads with relationship-derived audiences, and a 13-feature leave-one-child-out benchmark stored as aggregate metrics only. |
| O6 | Evaluate with automated tests, synthetic measurements, live checks and explicit limits | Met. 270 tests, rule backtest, ML benchmark, request timings, deploy check and a live four-role verification, with threats to validity in 6.11 and limitations in 7.5. |

## 8.2 What was built

Kito is a Django application for a single school that brings emotional wellness,
academic progress, social development and healthy habits into one role-aware
view. Children and adults both contribute structured observations. A versioned
scoring method turns those observations into gap-aware trends. Deterministic
rules turn the trends into a small number of explainable alerts, each owned by a
named person and tracked through an append-only case timeline. Adults coordinate
through child-scoped messages that the child and the administrator cannot read.
An offline classifier measures whether the structured features carry signal and
is deliberately kept out of every care decision.

The artefact is live at `https://Maaz2006.pythonanywhere.com`, deploys without a
build step, and runs 270 passing tests.

## 8.3 What was learned

Three lessons are worth carrying forward.

**Access control is a design activity, not a middleware setting.** The hard
questions were not "how do I check a role?" but "who is this person to this
child, for how long, and what may they see inside a page they are allowed to
open?". Answering those questions in a declarative matrix made the rest of the
system simpler and the tests meaningful.

**Honesty about missing data is a safety property.** The easiest way to produce a
complete dashboard is to treat absence as zero. That choice would systematically
disadvantage the children whose data is thinnest, which is often the group that
most needs attention. The no-row rule, the two-domain minimum and the gap-aware
rules cost some visual completeness and are the right trade.

**A model that is not connected to a decision is still a claim.** Even an offline
benchmark can be presented as a prediction engine. Keeping the labels, the
validation method, the confusion matrix and the limitations next to the metrics
is what makes the benchmark an evaluation rather than marketing.

## 8.4 Future work

In rough order of value:

1. **A supervised pilot.** Ethics approval, a DPIA, guardian consent and child
   assent, a small number of families, and a pre-registered set of measures:
   completion rate, time on task, comprehension of the family page, mentor trust
   in the queue, and the proportion of alerts that lead to a documented action.
2. **Threshold review with the safeguarding lead.** Make the rule thresholds
   configurable per school and record the rationale for each change, so the
   configuration is auditable rather than hidden in code.
3. **Calibration and fairness audit of the benchmark.** Before any ranking use,
   measure calibration by subgroup, report confidence intervals, and repeat
   across generator seeds. If the model cannot be calibrated on real outcomes, it
   should stay offline.
4. **PostgreSQL and retention automation.** Move off SQLite before concurrent
   write load matters, and implement the retention schedule described in the
   ethics statement rather than leaving deletion as a manual task.
5. **A minimal MIS import.** Attendance and marks are the most duplicated data.
   A CSV import with validation is a smaller and safer step than a live
   integration.
6. **Accessibility testing with assistive technology.** The current review is
   against WCAG guidance. The next step is testing with a screen reader and with
   users who have cognitive or motor access needs.
7. **Notification without leakage.** A mentor should not have to poll the queue,
   but email or push must not carry emotional content or a child's name. A
   content-free "you have a case" nudge, with the detail behind authentication,
   is the design constraint.

## 8.5 Closing statement

The project set out to show that a school can notice change early without turning
a child into a data point. The artefact does not prove that it improves outcomes;
that requires a pilot the project could not ethically run. It does show, in
working and tested code, that the two goals need not conflict: access can be
expressed as a relationship-aware rule, scoring can refuse to invent data, alerts
can end in a named human, and a model can be measured without being trusted with a
decision. That is a modest contribution, and it is defensible.
