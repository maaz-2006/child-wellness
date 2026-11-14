# Assembly guide

## Title page

> **Kito: a role-aware child wellness monitoring platform for a single school**
>
> Design, implementation and evaluation of an early-warning and communication
> system with privacy-preserving access control
>
> `[STUDENT NAME]` (`[STUDENT ID]`)
> `[PROGRAMME]`
> `[MODULE CODE]`
> Supervisor: `[SUPERVISOR]`
> `[UNIVERSITY]`
> `[SUBMISSION DATE]`
>
> Submitted in partial fulfilment of the requirements for the degree of
> `[PROGRAMME]`.
>
> Word count: `[WORD COUNT]` (excluding references and appendices)
>
> Source code: <https://github.com/maaz-2006/child-wellness>
> Live system: <https://Maaz2006.pythonanywhere.com>

## Structure and word budget

| Chapter | Purpose | Target |
|---|---|---|
| Abstract | problem, artefact, method, result, limits | 300 |
| 1 Introduction | why this matters, aim, objectives, scope | 1,000 |
| 2 Background | literature, existing systems, standards, gap | 1,400 |
| 3 Requirements | stakeholders, FR/NFR, constraints, traceability | 1,400 |
| 4 Design | architecture, data, permissions, algorithms, UX | 2,600 |
| 5 Implementation | build decisions, code, bugs, metrics | 1,700 |
| 6 Evaluation | tests, backtest, benchmark, performance, live checks | 2,000 |
| 7 Discussion | meaning, trade-offs, ethics, limitations | 1,000 |
| 8 Conclusion | objectives met, future work | 600 |

If your limit is lower, cut in this order: the route table in 4.11, the threat
table in 4.12, the sequence diagrams (keep one), the per-command detail in
5.10, and the requirements traceability table in 6.10. Do **not** cut the
limitations, the access-control tests or the live verification: those are what
separate a demo from an evaluated artefact.

The current drafts run longer than the targets above (about 18,500 words in the
body). `docs/README.md` has a prioritised cut list that reaches roughly 12,000
words without removing the evaluation.

## Front matter

- Abstract (no citations, no abbreviations that are not defined).
- Acknowledgements: supervisor, school contact if any, and anyone who read a
  draft. Do not thank people who did not consent to be named.
- Table of contents, list of figures, list of tables. Generate these in Word
  from heading styles; do not hand-type page numbers.
- Abbreviations: API, CSRF, DPIA, GDPR, ICO, IRLS, LOOCV, MFA, MIS, RBAC, SD,
  SQLite, SVG, WCAG.

## Figures to include

| Figure | Source | Caption idea |
|---|---|---|
| 4.1 | Mermaid context diagram | System context: four roles, one school, one database |
| 4.2 | Mermaid container diagram | Django apps and the two access gates |
| 4.3 | Mermaid ER diagram | Identity, consent and wellness entities |
| 4.4 | Mermaid state diagram | Alert lifecycle |
| 4.5 | screenshot | Child check-in page |
| 4.6 | screenshot | Wellness trend with baseline band and gap |
| 4.7 | screenshot | Mentor alert case with timeline |
| 4.8 | screenshot | Guardian family page |
| 4.9 | screenshot | Messaging thread |
| 4.10 | Mermaid sequence | Entry → score → alert → human review |

Screenshots must not show real names. Use the seeded demo cohort only, and crop
the browser chrome.

## Tables to include

- 2.1 comparison of existing approaches.
- 3.1 stakeholders; 3.2 functional requirements; 3.3 non-functional requirements.
- 4.1 apps and responsibilities; 4.2 entities; 4.3 permission matrix (full version
  in Appendix A); 4.4 scoring weights; 4.5 alert rules; 4.6 design alternatives.
- 5.1 code metrics; 5.2 defects found and fixed.
- 6.1 test inventory; 6.2 access-control checks; 6.3 alert backtest;
  6.4 ML metrics and confusion matrix; 6.5 response times; 6.6 traceability.
- 7.1 limitations and mitigations.

## Formatting

- Harvard referencing, alphabetical by author surname.
- Code excerpts in a monospaced font, no more than 15 lines each, with the file
  path in the caption. Full listings go in the appendix or the repository.
- British spelling throughout (`organisation`, `behaviour`, `recognise`).
- Define every acronym at first use.
- Write in the past tense for what was built and the present tense for what the
  system does.
- Avoid "obviously", "simply" and "just"; they hide the work and alienate a
  reader who did not find it simple.

## Viva binder

Print and tab, in this order: the live URL and demo accounts; the one-page
architecture diagram; the permission matrix; the alert rule table; the
evaluation summary; the ethics statement; the risk register. A marker who asks
"show me" should get a tab, not a laptop search.
