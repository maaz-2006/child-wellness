# 1. Introduction

## 1.1 Context and motivation

Around one in five children aged 8–16 in England has a probable mental disorder
(NHS Digital, 2023), and schools are increasingly described as a front door to
support rather than a place where wellbeing is somebody else's responsibility.
The Department for Education (2021) asks schools to adopt a whole-school
approach: a named lead, clear referral routes, and staff who notice change early.
Safeguarding guidance goes further and requires every school to have a designated
safeguarding lead and a procedure for acting on concerns (Department for
Education, 2024).

In practice, the information needed to notice change is fragmented. A form tutor
may know that a child has become quiet; the attendance officer knows they have
missed four Mondays; the maths teacher knows their marks fell after half term;
the family knows they are not sleeping. Each fact is recorded somewhere, and
none of those places talks to the others. The result is a pattern that only
exists in the space between systems, which is exactly where nobody can query it.

Two responses are common. The first is to add another spreadsheet or a shared
document. That works for one diligent member of staff and fails as soon as they
leave, because the access rules exist only in their head. The second is to buy a
commercial monitoring platform. These can be effective, but they tend to
centralise sensitive data under an administrator account, present risk scores to
the child, and treat consent as a checkbox rather than an access condition.
Neither response is designed around the question this project starts from: **who
should be allowed to see this, and why?**

## 1.2 Problem statement

A single school needs one place where the four dimensions of a child's life can
be read together, so that change is visible before a crisis. It also needs that
place to be *safe to exist*: a system that centralises emotional data without
strict access control creates a new harm while trying to prevent one. The problem
is therefore twofold:

1. **Integration.** Structured information about emotional wellbeing, academic
   progress, social development and healthy habits is scattered across people
   and tools, and no role has a justified, coherent view across them.
2. **Governance.** A monitoring system concentrates sensitive data. Without an
   explicit, enforced and auditable access model, the system becomes a
   surveillance tool that can stigmatise children, exclude families and
   discourage the very disclosures it is meant to catch.

The project treats the second problem as a design constraint on the first, not as
an afterthought documented in a policy.

## 1.3 Aim

To design, implement and evaluate a secure, role-aware web platform that helps a
single school notice and respond to changes in a child's wellness, while
preserving the trust of the child, the family and the staff who use it.

## 1.4 Objectives

| ID | Objective | How it is evidenced |
|---|---|---|
| O1 | Derive requirements from published guidance, safeguarding practice and the realities of a single-school workflow | Chapter 3, traceability table 6.10 |
| O2 | Design an access model that expresses *why* a user is connected to a child, not merely *what role* they hold | Section 4.5, permission matrix (Appendix A), 24 permission tests |
| O3 | Implement structured capture and a transparent, versioned scoring method for four wellness domains | Sections 4.6–4.7, scoring tests, cohort report |
| O4 | Implement explainable early-warning alerts with a named owner, case workflow and safeguarding routing | Sections 4.8, 5.6, rule backtest 6.5 |
| O5 | Implement adult-to-adult communication and an offline evaluation of whether the structured features carry predictive signal | Sections 4.9–4.10, messaging tests, benchmark 6.6 |
| O6 | Evaluate the artefact with automated tests, synthetic-cohort measurements, live deployment checks and an explicit account of its limits | Chapter 6, live verification 6.9 |

The objectives are deliberately ordered so that governance (O2) is designed
before the features that depend on it (O3–O5). Retrofitting permissions onto a
finished data model is how systems end up with an administrator who can read
everything.

## 1.5 Scope

**In scope**

- one school, one database, four roles: parent/guardian, mentor, child,
  administrator;
- structured entry for emotional, academic, social and habit data;
- derived scores, trends, personal baselines and tiered alerts;
- guardian pulse, family updates and adult-to-adult messaging;
- an offline machine-learning benchmark, reported as aggregate metrics only;
- deployment to a public URL suitable for marking.

**Out of scope**

- multi-tenancy or cross-school federation;
- diagnosis, triage or any automated clinical decision;
- file uploads, attachments, email/SMS push, video or voice;
- a native mobile application;
- direct integration with a school MIS;
- real children's data: the evaluation uses a synthetic cohort.

The exclusions are design decisions, not unfinished work. File uploads would add
a content-moderation and malware surface that a one-week build cannot defend;
push notifications would move urgent safeguarding content off the platform and
into an unlogged channel; and a production classifier would require clinical
validation the project cannot provide.

## 1.6 Contributions

1. **A declarative, relationship-aware permission model** in which the protected
   resource is a first-class value and the access matrix is executable code,
   rendered into the UI and exhaustively tested (56 matrix entries, 38 access
   grants, 14 resources, four role/relationship rows).
2. **A scoring method that treats missing data as missing**, not as zero, and
   requires at least two domains before an overall score exists, with confidence
   labels tied to reporting cadence.
3. **An alert design that separates detection from response**: deterministic
   rules with embedded evidence, one rolling alert per rule per child, a named
   owner, escalation without downgrade, no auto-resolution, and urgent findings
   that cannot be shared.
4. **A safeguarding screen that does not copy the child's words**: the alert
   stores the matched category and an entry reference, never the note text.
5. **A privacy-preserving evaluation artefact**: an offline classifier whose
   stored output is aggregate metrics and coefficients, with no child identifier
   and no connection to the care path.
6. **A reproducible deployment and evidence trail**: 270 tests, a rule backtest,
   an ML benchmark, a live URL and a documented set of live access checks.

## 1.7 Report structure

Chapter 2 reviews the relevant literature, guidance and existing systems.
Chapter 3 turns that into stakeholders, requirements and constraints. Chapter 4
presents the design, including the access model, data model, scoring, alerts,
messaging and the ML benchmark. Chapter 5 describes the implementation and the
defects found during it. Chapter 6 evaluates the artefact with tests, synthetic
measurements, performance checks and live verification. Chapter 7 discusses the
trade-offs, ethics and limitations. Chapter 8 concludes and sets out future work.

## 1.8 Summary

The rest of the report defends one claim: that early-warning monitoring and
privacy are not opposing goals if access is designed as a relationship-aware
rule and every automated finding terminates in a named human. Kito is the
artefact that makes that claim testable.
