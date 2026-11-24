# System comparison — claims triage (n = 231 cases)

_Not yet run: agent, single_prompt — `python -m eval.runner --system <name>`._

| System | Decision accuracy (95% CI) | Macro-F1 | Fraud AUC | Injection resisted | Amount extraction | Tokens / claim | $ / 1k claims | p50 latency |
|---|---|---|---|---|---|---|---|---|
| Rules-only | 78.4% [72.6, 83.2] | 0.778 | 0.7634 | 7/10 | 90.5% | 0 | $0.00 | <10ms |

### Accuracy by phrasing tier

| System | canonical (n=95) | paraphrase (n=93) | noisy (n=43) |
|---|---|---|---|
| Rules-only | 77.9% | 77.4% | 81.4% |

### Accuracy by slice

| Slice | n | Rules-only |
|---|---|---|
| auto | 5 | 4/5 |
| boundary | 10 | 9/10 |
| clean_approve | 45 | 45/45 |
| distractor_legit | 15 | 13/15 |
| edge | 5 | 3/5 |
| exceeds_coverage | 15 | 13/15 |
| expired | 12 | 12/12 |
| fraud | 5 | 5/5 |
| fraud_story | 30 | 11/30 |
| health | 5 | 5/5 |
| high_ratio_documented | 20 | 19/20 |
| implausible_amount | 8 | 0/8 |
| inactive_policy | 8 | 8/8 |
| injection | 10 | 6/10 |
| pre_inception | 8 | 8/8 |
| property | 5 | 5/5 |
| review_needed | 15 | 5/15 |
| unknown_policy | 10 | 10/10 |

