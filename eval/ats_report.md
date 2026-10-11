# ATS-readiness checker: defect-injection evaluation

> SYNTHETIC clean resume with one defect injected at a time. Shows internal consistency of the checklist; it does NOT measure agreement with any real company ATS.

Clean resume score: **97.98**. Detection rate: **1.000**. Score drops for every defect: **True**.

| Injected defect | Check expected to fire | Status | Score | Drop |
|---|---|---|---|---|
| no_email | email | fail | 94.06 | 3.92 |
| no_phone | phone | fail | 95.04 | 2.94 |
| no_skills_section | core_sections | warn | 82.75 | 15.23 |
| no_projects_section | core_sections | warn | 69.02 | 28.96 |
| no_bullets | bullet_usage | fail | 78.37 | 19.61 |
| emojis | special_chars | fail | 96.21 | 1.77 |
| first_person | first_person | warn | 90.63 | 7.35 |
| no_numbers | quantified | fail | 89.55 | 8.43 |
| mixed_date_formats | date_consistency | fail | 97.19 | 0.79 |
| too_long | length | fail | 94.45 | 3.53 |
| scanned_pages | text_extractable | fail | 85.23 | 12.75 |
| two_columns | single_column | fail | 93.86 | 4.12 |
| photo_image | images | warn | 97.1 | 0.88 |
| few_skills | skills_breadth | fail | 82.75 | 15.23 |

With a job description (Required: React, Node.js, MongoDB, Kubernetes): score 95; 70% of JD skills present; missing: Kubernetes, AWS.