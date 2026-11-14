# 2. Background and related work

## 2.1 Wellbeing as a multi-dimensional construct

"Wellbeing" is not a single measurable quantity. The World Health Organization
(2020) treats adolescent mental health as the product of individual capacity,
relationships, community and structural conditions, not as the absence of a
diagnosis. In education, social and emotional learning frameworks describe
competencies such as self-awareness, self-management, social awareness and
responsible decision-making (CASEL, 2024). Developmental psychology adds the
ecological view that a child is shaped by nested systems — family, school,
peers, community — and that change in one system shows up in another
(Bronfenbrenner, 1979). Self-determination theory contributes a complementary
mechanism: wellbeing depends on feeling competent, connected and autonomous
(Deci and Ryan, 2000).

This project operationalises that literature into four domains rather than one
score:

| Domain | Why it is included | Typical source |
|---|---|---|
| Emotional wellbeing | The child's own account of mood, energy, sleep quality and connection | Child check-in; adult observation |
| Academic progress | Engagement and attainment are observable early signals, and school is where children spend most of their week | Assessment records; attendance |
| Social development | Peer relationships and participation are central to belonging | Structured adult observation |
| Healthy habits | Sleep, activity, screen time and nutrition are modifiable and affect mood and learning | Child, guardian or mentor log |

The four-domain choice is a design compromise. It is broad enough to reflect the
literature, narrow enough to be captured in under a minute a day, and concrete
enough to be scored reproducibly. It is **not** a clinical instrument, and the
report does not treat it as one.

## 2.2 Schools as settings for early response

Schools are the only universal service that sees almost every child every week.
That makes them an obvious setting for early identification, and government
guidance reflects it. The Department for Education (2021) recommends a
whole-school approach with a designated mental health lead, clear referral
pathways and staff training. Safeguarding guidance makes the designated
safeguarding lead a statutory role and requires concerns to be recorded and
acted on (Department for Education, 2024). Attendance guidance similarly treats
absence as a signal that requires investigation rather than a administrative
footnote (Department for Education, 2022).

The practical difficulty is that these duties are distributed across people who
each hold a fragment. A form tutor notices withdrawal; the attendance officer
notices a pattern of Mondays; the family notices sleeplessness. Integration is
therefore not a technical convenience but a precondition for the kind of early
response the guidance describes. At the same time, integration increases the
consequences of a mistake: the more complete the record, the more damage a
single over-broad access grant can do.

## 2.3 What existing approaches do

Three approaches dominate.

**Management information systems (MIS).** Products such as SIMS and Arbor are
built around attendance, assessment and statutory returns. They are excellent at
the record-keeping they were designed for, but wellbeing is usually a free-text
note or a pastoral flag rather than a structured, trended domain. Cross-domain
analysis is limited, and access is organised around staff roles and timetable
responsibilities rather than around a child's relationships.

**Commercial wellbeing platforms.** These often provide surveys, mood check-ins
and dashboards. Their weakness is architectural: a tenant-level administrator
frequently holds broad read access, the child may see a risk category about
themselves, and consent is recorded once rather than enforced continuously.
Because the products are closed, a school cannot inspect or test the access
model, which is precisely the part that matters when the data are sensitive.

**Spreadsheets and shared documents.** Cheap and immediately usable, but the
access rule lives in the head of the person who shared the folder. There is no
audit trail, no row-level separation between families, and no way to answer
"who saw this?" after a concern is raised.

| Capability | Typical MIS | Typical commercial platform | Spreadsheet | Kito |
|---|---|---|---|---|
| Structured capture across four domains | Partial | Partial | Manual | Yes |
| Versioned, reproducible scores | No | Sometimes | No | Yes |
| Access by relationship, not just role | Partial | Often tenant-wide | No | Yes |
| Consent enforced as an access gate | No | Sometimes | No | Yes |
| Child never sees own risk label | n/a | Often not guaranteed | n/a | Yes |
| Named owner for every alert | Partial | Sometimes | No | Yes |
| Append-only audit of reads and denials | Partial | Unknown | No | Yes |
| Open to inspection and testing | No | No | Yes | Yes |

The comparison is based on public documentation and common patterns, not on a
controlled product trial; it motivates the design rather than claiming a
benchmark.

## 2.4 Privacy, consent and children's rights

The legal context is the UK GDPR and the Data Protection Act 2018. Wellbeing
data can reveal health status and therefore falls into a special category,
requiring both a lawful basis and a special-category condition. The Information
Commissioner's Office (2020) Age Appropriate Design Code adds fifteen standards
for services likely to be accessed by children, including best interests, data
minimisation, transparency, high privacy by default and no detrimental use of
data. The United Nations Convention on the Rights of the Child adds a wider
frame: the child's right to privacy, to be heard, and to have their best
interests treated as a primary consideration (UNICEF, 1989).

Nissenbaum's (2009) concept of contextual integrity is useful here. Privacy is
not "keeping data secret"; it is ensuring that information flows according to the
norms of the context in which it was shared. A child telling a mentor that they
are anxious expects that mentor to act, but not expects the administrator to
read the sentence. A parent expects to know how their child is doing, but not to
read another family's thread. An access model that only checks role cannot
express these expectations; it has to know the relationship that justifies the
flow.

This project therefore treats consent as an **access condition**, not a stored
acknowledgement. A guardian link without current consent grants no access at all,
and revoking consent removes access immediately without deleting history. The
design is described in Section 4.5 and tested directly in the permission suite.

## 2.5 Machine learning in safeguarding

Machine learning is attractive in this domain because the signal is multivariate
and the outcome is rare. It is also risky. Predictive models trained on
institutional data reproduce the biases of that data (O'Neil, 2016; Eubanks,
2018; Noble, 2018), and a risk label can follow a child through their school
career. Complex models are hard to explain to the adult who has to act on them,
and post-hoc explanations can be misleading; Rudin (2019) argues that for
high-stakes decisions the model should be interpretable in the first place.

There is a second, more subtle risk: **label leakage and function creep**. A
model that predicts "is this child currently in difficulty" is not the same as a
model that predicts "will this child become unwell", yet both can be presented as
early warning. And a benchmark that is not connected to the care path can still
become one if a future maintainer exports its output and attaches it to a child.

The design response in this project is deliberately conservative:

- the production path is **deterministic rules**, not a classifier;
- the classifier is an **offline benchmark** that answers whether the structured
  features carry signal at all;
- validation is **leave-one-child-out**, so no child is scored by a model that
  saw them;
- the stored artefact contains **aggregate metrics and coefficients only**, with
  no child identifier and no per-child prediction;
- the benchmark page states, in the interface, that it is not a decision system.

This is not a rejection of machine learning. It is a decision about what can be
validated within the project's evidence base. With synthetic labels and no
clinical follow-up, a production classifier would be a claim the evaluation
cannot support.

## 2.6 Human factors: attention, alert fatigue and explanation

An alert is a request for a person's attention, and attention is the scarcest
resource in a school. Alert fatigue is well documented in clinical systems: when
too many low-value warnings fire, clinicians override them, including the ones
that matter (van der Sijs et al., 2006). A wellbeing system that flags every bad
week will be ignored within a term.

Three design consequences follow. First, severity must be gated by evidence
quality: a single thin week cannot become an urgent alert. Second, alerts must be
**explainable after the fact** — the rule, the numbers and the period should be
stored with the finding, so a mentor can answer "why did this fire?" without
re-running a model. Third, the queue must be **de-duplicated**: one rolling alert
per rule per child, with a count of occurrences rather than a new row every day.
These are requirements in Chapter 3 and design decisions in Section 4.8.

Usability guidance points in the same direction. Nielsen's (1994) heuristics
emphasise visibility of system status, error prevention and recognition over
recall; WCAG 2.2 (World Wide Web Consortium, 2023) requires perceivable, operable,
understandable and robust interfaces. A wellbeing tool used by children must meet
a higher bar than a staff dashboard: large touch targets, plain language, no
red-"risk" styling on a child's own page, and a chart that is never the only way
to read the data.

## 2.7 Synthesis and gap

The literature and guidance converge on five ideas:

1. wellbeing is multi-dimensional and contextual;
2. schools are the right setting for early response, but integration is
   incomplete;
3. sensitive data require purpose limitation and relationship-aware access;
4. automated risk labelling can harm the child it is meant to help;
5. alerts only work if they are few, explainable and owned.

Existing systems tend to satisfy (1) and (2) or (3)–(5), rarely all five. The
gap this project addresses is therefore not "build a dashboard". It is to show,
in working code, that integration and governance can be designed together:
access expressed as a declarative rule, scoring that refuses to invent data,
alerts that end in a named human, and an ML layer that is measured but not
deployed.

From this synthesis the project derives eight design principles, which become the
requirements in Chapter 3:

| ID | Principle | Consequence |
|---|---|---|
| P1 | Fail closed | anything not explicitly granted is denied and audited |
| P2 | Relationship, not role | access requires a current link to *this* child |
| P3 | Consent is a gate | revoked consent removes access immediately |
| P4 | No score without data | gaps stay gaps; no domain is averaged as zero |
| P5 | No child-facing risk label | the child never sees their own score or tier |
| P6 | Aggregate for administrators | no emotional content or case notes at institution scope |
| P7 | Human in the loop | every alert has a named owner and an append-only timeline |
| P8 | Measure, do not deploy | the ML layer is an offline, aggregate-only benchmark |

## 2.8 Summary

The background establishes both the need for integration and the reasons to be
cautious about it. Chapter 3 turns the need and the caution into a prioritised,
testable requirements set.
