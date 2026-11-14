# Report and submission pack

This folder holds the written deliverables for the Kito final-year project:

- the report, split into one file per chapter so it can be edited and assembled
  in Word or Google Docs;
- the ethics statement and the participant documents for a future pilot;
- the submission checklist, demo script and viva preparation.

Everything here is a **draft for you to own**. Read it, correct anything that
does not match your module handbook, and put it in your own voice. Most
universities treat submitting generated text as academic misconduct, so treat
these files as a structured argument and a set of measured facts to rewrite, not
as a final document to hand in unchanged.

## Fill these in before you assemble

| Placeholder | Value |
|---|---|
| `[STUDENT NAME]` | your full name |
| `[STUDENT ID]` | your student number |
| `[MODULE CODE]` | e.g. `CS3999` |
| `[PROGRAMME]` | e.g. BSc (Hons) Computer Science |
| `[SUPERVISOR]` | your supervisor's name |
| `[UNIVERSITY]` | your institution |
| `[SUBMISSION DATE]` | the date on the handbook |
| `[WORD LIMIT]` | the limit from the handbook |
| `[ETHICS REFERENCE]` | your ethics approval reference, if issued |

The report body (abstract through conclusion, excluding references and
appendices) is roughly **18,500 words as drafted**. That is long for most
undergraduate modules, so treat the "Suggested words" column below as a target,
not a description, and cut before submitting. A cut that reaches about 12,000
words without losing the argument:

| Cut | Approximate saving |
|---|---:|
| Chapter 4: remove the route table, the design-alternatives table and the prose around them; keep the matrix, scoring, alerts and lifecycle diagrams | 1,400 |
| Chapter 6: compress the per-file test inventory, the performance table and the traceability table into short paragraphs | 1,100 |
| Chapter 5: summarise messaging, ML and front-end detail instead of walking through each module | 1,000 |
| Chapter 7: keep the trade-offs and limitations; compress the ethics reflection and implications sections | 1,000 |
| Chapter 3: group the Could/Should requirements and shorten the scenario prose | 700 |
| Chapter 2: trim the literature review to the sources the argument actually uses | 500 |
| Chapter 8: keep the objectives table and future work; cut the closing rhetoric | 350 |
| Chapter 1 and abstract: tighten the contributions list and the motivation | 300 |

Do **not** cut the access-control tests, the alert backtest, the ML confusion
matrix, the limitations or the live verification. Those are what separate an
evaluated artefact from a demo.

## File map

| File | Contents | Suggested words |
|---|---|---|
| `report/00-assembly-guide.md` | structure, figures, formatting, assembly order | 500 |
| `report/01-abstract.md` | abstract | 300 |
| `report/02-introduction.md` | context, problem, aims, objectives, contributions | 1,000 |
| `report/03-background.md` | literature, existing systems, standards, gap | 1,400 |
| `report/04-requirements.md` | stakeholders, functional and non-functional requirements | 1,400 |
| `report/05-design.md` | architecture, data model, permissions, scoring, alerts, messaging, ML, UX, security | 2,600 |
| `report/06-implementation.md` | how each part was built, bugs found, code metrics | 1,700 |
| `report/07-evaluation.md` | tests, access checks, alert backtest, ML benchmark, performance, live deployment | 2,000 |
| `report/08-discussion.md` | interpretation, trade-offs, ethics, limitations | 1,000 |
| `report/09-conclusion.md` | objectives met, future work | 600 |
| `report/10-references.md` | Harvard reference list | — |
| `report/11-appendices.md` | permission matrix, formulas, rules, test inventory, glossary | — |
| `ethics/ethics-statement.md` | full ethics statement and DPIA summary | 1,800 |
| `ethics/participant-documents.md` | information sheet, consent form, child assent template | 900 |
| `submission/submission-pack.md` | checklist, demo script, viva questions, marking map | 1,600 |

## Assembly order

1. Title page (university template).
2. Abstract.
3. Acknowledgements (optional).
4. Table of contents, list of figures, list of tables.
5. Chapters 1–8 in file order.
6. References.
7. Appendices.
8. Ethics statement as an appendix or separate submission, following your
   handbook.

## Figures

The design chapter contains Mermaid diagrams. GitHub renders them directly. For
Word, paste each diagram into <https://mermaid.live>, export PNG at 2x, and
insert it with a numbered caption. Keep the Mermaid source in the appendix so
the diagram can be regenerated if a marker asks.

Number figures and tables by chapter (`Figure 5.2`, `Table 7.1`) and refer to
them in the text. A figure that is never mentioned is decoration.

## Keeping the numbers honest

Every figure in the evaluation chapter can be regenerated from the repository:

```bash
python manage.py test
python manage.py seed_demo --reset
python manage.py backtest_alerts --weeks 8
python manage.py ml_report
python manage.py cohort_report
python manage.py check --deploy
```

If you reseed or change a threshold, re-run the command and update the number in
both the chapter and the appendix. Do not quote a figure you cannot reproduce.

## What this project did *not* do

State this plainly in the report; it is a strength, not a gap to hide:

- no real children, families or staff were involved;
- no usability study or interviews were run;
- the machine-learning layer is an offline benchmark, not a deployed predictor;
- the alert thresholds were not clinically validated;
- accessibility was reviewed against WCAG guidance, not tested with disabled
  users.

The ethics statement explains why: the artefact was evaluated on a synthetic
cohort, and a real pilot would need approval, a DPIA and school sign-off first.
