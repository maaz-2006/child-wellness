# Abstract

Schools hold more information about a child than any single member of staff can
see. Attendance, marks, behaviour notes and conversations with home sit in
separate systems, so a decline that is obvious across three of them can be
invisible in each one. Commercial monitoring products address this by
centralising sensitive data, but they often give administrators broad access,
label children with risk scores they can see themselves, and leave families out
of the loop.

This project designed, built and evaluated **Kito**, a web platform for a single
school that brings four dimensions of wellness into one view: emotional
wellbeing, academic progress, social development and healthy habits. Children
contribute daily check-ins and habit logs; mentors and guardians contribute
structured observations. A versioned scoring method converts entries into
rolling seven-day domain and overall scores, and deterministic, explainable rules
turn those scores into watch, concern and urgent alerts. Every alert is owned by
a named person and tracked through an append-only case timeline. Adults
communicate through child-scoped, append-only message threads; children and the
administrator cannot read them. The central design claim is that **access is a
declarative relationship-aware rule, not a role check**: 56 matrix entries (38
access grants) over 14 resources, fail-closed, with sensitive denials audited.

The artefact is a Django 5.2 application with server-rendered HTML, hand-written
CSS and 31 lines of JavaScript. It was evaluated with 270 automated tests, a
rule backtest on a synthetic cohort, a leave-one-child-out benchmark of a
13-feature logistic regression, and a live deployment on PythonAnywhere. The
backtest detected 7 of 7 labelled declines with 3 false positives (precision
0.70, recall 1.00, with a median of 10 days from simulated onset to the first
alert). The offline classifier reached
accuracy 0.949 and ROC AUC 0.949 on 176 held-out snapshots from 22 children, but
is deliberately not connected to any care decision. Live checks confirmed that
parents, mentors, children and the administrator receive the intended access and
nothing more.

The contribution is not a new prediction algorithm. It is an argument, made
concrete and testable, that a school wellbeing system can surface change early
while refusing to become a surveillance dashboard: gaps are not zeros, children
never see their own risk label, administrators see aggregates rather than
emotional content, and every automated finding ends with a human name. The
limits are equally explicit: the data are synthetic, the thresholds are not
clinically validated, no families were involved, and the model is an evaluation
artefact rather than a deployed decision tool.
