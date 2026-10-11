# Tailoring hallucination evaluation

> SYNTHETIC fixtures (3 resumes x 3 job descriptions). The model is SIMULATED: it measures the validator, not a real LLM.
> Runs per pair: 10. Each JD contains skills the candidate lacks ('traps').

| Condition | n | Unsupported claim rate | Fabricated bullet rate | Trap capture | Extractive ratio | JD coverage |
|---|---|---|---|---|---|---|
| A. Extractive selection (no model) | 9 | 0.000 | 0.000 | 0.000 | 1.000 | 0.230 |
| B. Simulated model (fabrication prob. 0.5), no validator | 90 | 0.058 | 0.530 | 0.478 | 0.470 | 0.319 |
| C. Simulated model (fabrication prob. 0.5) + validator (ours) | 90 | 0.000 | 0.000 | 0.000 | 1.000 | 0.230 |

## Validator detection test (injected fabrications)

| Fabrication kind | Detected / injected | Recall |
|---|---|---|
| skill_in_skills | 9/9 | 1.000 |
| skill_in_bullet | 9/9 | 1.000 |
| number | 9/9 | 1.000 |
| inflated_qualifier | 9/9 | 1.000 |
| entity_title | 9/9 | 1.000 |
| date | 9/9 | 1.000 |
| untraceable | 9/9 | 1.000 |
| unseen_token | 9/9 | 1.000 |

Overall recall: **1.000**. False-positive rate on clean extractive outputs: **0.000**.

Limits: the validator checks skills, numbers, dates, titles/organisations, leadership/scale wording and source traceability. It does not prove a rewritten sentence keeps its exact meaning. Fixtures are tiny and synthetic; do not report these numbers as real-world accuracy.