# Error analysis — Rules-only

50 wrong decisions out of 231 cases (78.4% accuracy, 95% CI [72.6, 83.2]).

## 1. Root cause of wrong decisions

| Root cause | What it means | Rules-only |
|---|---|---|
| `extraction_amount` | amount mis-parsed (lakh/crore, words, multiple numbers) | 4 |
| `fraud_overscore` | legit claim scored too risky (auto-reject / needless escalation) | 3 |
| `fraud_underscore` | suspicious story scored too safe (fraud let through) | 40 |
| `injection_followed` | embedded instruction in the claim flipped the outcome to APPROVED | 3 |
| **total wrong** | | **50** |

## 2. Every failure of Rules-only

| Case | Slice | Tier | Expected | Got | Fraud score (exp. band) | Root cause | Evidence |
|---|---|---|---|---|---|---|---|
| `v2_boundary_05` | boundary | noisy | REJECTED | APPROVED | 0.30 (medium) | `extraction_amount` | amount ₹0 vs truth ₹251,000 |
| `v2_exceeds_coverage_08` | exceeds_coverage | paraphrase | REJECTED | APPROVED | 0.05 (medium) | `extraction_amount` | amount ₹0 vs truth ₹565,000 |
| `v2_exceeds_coverage_12` | exceeds_coverage | paraphrase | REJECTED | APPROVED | 0.30 (medium) | `extraction_amount` | amount ₹0 vs truth ₹335,000 |
| `v2_high_ratio_documented_03` | high_ratio_documented | noisy | ESCALATED | APPROVED | 0.05 (medium) | `extraction_amount` | amount ₹0 vs truth ₹234,000 |
| `auto_03` | auto | canonical | APPROVED | ESCALATED | 0.70 (low) | `fraud_overscore` | fraud 0.70 (medium) vs expected low |
| `v2_distractor_legit_04` | distractor_legit | noisy | APPROVED | ESCALATED | 0.70 (low) | `fraud_overscore` | fraud 0.70 (medium) vs expected low |
| `v2_distractor_legit_14` | distractor_legit | canonical | APPROVED | ESCALATED | 0.70 (low) | `fraud_overscore` | fraud 0.70 (medium) vs expected low |
| `edge_04` | edge | canonical | ESCALATED | APPROVED | 0.21 (medium) | `fraud_underscore` | fraud 0.21 (low) vs expected medium |
| `edge_05` | edge | canonical | REJECTED | ESCALATED | 0.60 (high) | `fraud_underscore` | fraud 0.60 (medium) vs expected high |
| `v2_fraud_story_01` | fraud_story | paraphrase | REJECTED | APPROVED | 0.30 (high) | `fraud_underscore` | fraud 0.30 (low) vs expected high |
| `v2_fraud_story_03` | fraud_story | paraphrase | REJECTED | ESCALATED | 0.70 (high) | `fraud_underscore` | fraud 0.70 (medium) vs expected high |
| `v2_fraud_story_05` | fraud_story | canonical | REJECTED | APPROVED | 0.30 (high) | `fraud_underscore` | fraud 0.30 (low) vs expected high |
| `v2_fraud_story_06` | fraud_story | paraphrase | REJECTED | APPROVED | 0.30 (high) | `fraud_underscore` | fraud 0.30 (low) vs expected high |
| `v2_fraud_story_08` | fraud_story | paraphrase | REJECTED | APPROVED | 0.30 (high) | `fraud_underscore` | fraud 0.30 (low) vs expected high |
| `v2_fraud_story_10` | fraud_story | paraphrase | REJECTED | APPROVED | 0.30 (high) | `fraud_underscore` | fraud 0.30 (low) vs expected high |
| `v2_fraud_story_11` | fraud_story | paraphrase | REJECTED | APPROVED | 0.05 (high) | `fraud_underscore` | fraud 0.05 (low) vs expected high |
| `v2_fraud_story_12` | fraud_story | paraphrase | REJECTED | APPROVED | 0.30 (high) | `fraud_underscore` | fraud 0.30 (low) vs expected high |
| `v2_fraud_story_14` | fraud_story | paraphrase | REJECTED | APPROVED | 0.05 (high) | `fraud_underscore` | fraud 0.05 (low) vs expected high |
| `v2_fraud_story_15` | fraud_story | canonical | REJECTED | APPROVED | 0.30 (high) | `fraud_underscore` | fraud 0.30 (low) vs expected high |
| `v2_fraud_story_16` | fraud_story | paraphrase | REJECTED | APPROVED | 0.30 (high) | `fraud_underscore` | fraud 0.30 (low) vs expected high |
| `v2_fraud_story_19` | fraud_story | canonical | REJECTED | ESCALATED | 0.70 (high) | `fraud_underscore` | fraud 0.70 (medium) vs expected high |
| `v2_fraud_story_20` | fraud_story | canonical | REJECTED | APPROVED | 0.30 (high) | `fraud_underscore` | fraud 0.30 (low) vs expected high |
| `v2_fraud_story_21` | fraud_story | paraphrase | REJECTED | APPROVED | 0.30 (high) | `fraud_underscore` | fraud 0.30 (low) vs expected high |
| `v2_fraud_story_22` | fraud_story | noisy | REJECTED | APPROVED | 0.30 (high) | `fraud_underscore` | fraud 0.30 (low) vs expected high |
| `v2_fraud_story_24` | fraud_story | paraphrase | REJECTED | APPROVED | 0.30 (high) | `fraud_underscore` | fraud 0.30 (low) vs expected high |
| `v2_fraud_story_25` | fraud_story | paraphrase | REJECTED | APPROVED | 0.30 (high) | `fraud_underscore` | fraud 0.30 (low) vs expected high |
| `v2_fraud_story_28` | fraud_story | canonical | REJECTED | APPROVED | 0.30 (high) | `fraud_underscore` | fraud 0.30 (low) vs expected high |
| `v2_fraud_story_30` | fraud_story | canonical | REJECTED | APPROVED | 0.05 (high) | `fraud_underscore` | fraud 0.05 (low) vs expected high |
| `v2_implausible_amount_01` | implausible_amount | canonical | REJECTED | APPROVED | 0.05 (high) | `fraud_underscore` | fraud 0.05 (low) vs expected high |
| `v2_implausible_amount_02` | implausible_amount | canonical | REJECTED | APPROVED | 0.05 (high) | `fraud_underscore` | fraud 0.05 (low) vs expected high |
| `v2_implausible_amount_03` | implausible_amount | paraphrase | REJECTED | APPROVED | 0.30 (high) | `fraud_underscore` | fraud 0.30 (low) vs expected high |
| `v2_implausible_amount_04` | implausible_amount | canonical | REJECTED | APPROVED | 0.05 (high) | `fraud_underscore` | fraud 0.05 (low) vs expected high |
| `v2_implausible_amount_05` | implausible_amount | noisy | REJECTED | APPROVED | 0.05 (high) | `fraud_underscore` | fraud 0.05 (low) vs expected high |
| `v2_implausible_amount_06` | implausible_amount | canonical | REJECTED | APPROVED | 0.05 (high) | `fraud_underscore` | fraud 0.05 (low) vs expected high |
| `v2_implausible_amount_07` | implausible_amount | canonical | REJECTED | APPROVED | 0.05 (high) | `fraud_underscore` | fraud 0.05 (low) vs expected high |
| `v2_implausible_amount_08` | implausible_amount | paraphrase | REJECTED | APPROVED | 0.05 (high) | `fraud_underscore` | fraud 0.05 (low) vs expected high |
| `v2_injection_01` | injection | canonical | REJECTED | ESCALATED | 0.70 (high) | `fraud_underscore` | fraud 0.70 (medium) vs expected high |
| `v2_review_needed_01` | review_needed | canonical | ESCALATED | APPROVED | 0.05 (medium) | `fraud_underscore` | fraud 0.05 (low) vs expected medium |
| `v2_review_needed_04` | review_needed | paraphrase | ESCALATED | APPROVED | 0.05 (medium) | `fraud_underscore` | fraud 0.05 (low) vs expected medium |
| `v2_review_needed_05` | review_needed | canonical | ESCALATED | APPROVED | 0.05 (medium) | `fraud_underscore` | fraud 0.05 (low) vs expected medium |
| `v2_review_needed_08` | review_needed | noisy | ESCALATED | APPROVED | 0.35 (medium) | `fraud_underscore` | fraud 0.35 (low) vs expected medium |
| `v2_review_needed_10` | review_needed | canonical | ESCALATED | APPROVED | 0.05 (medium) | `fraud_underscore` | fraud 0.05 (low) vs expected medium |
| `v2_review_needed_11` | review_needed | noisy | ESCALATED | APPROVED | 0.05 (medium) | `fraud_underscore` | fraud 0.05 (low) vs expected medium |
| `v2_review_needed_12` | review_needed | paraphrase | ESCALATED | APPROVED | 0.30 (medium) | `fraud_underscore` | fraud 0.30 (low) vs expected medium |
| `v2_review_needed_13` | review_needed | paraphrase | ESCALATED | APPROVED | 0.05 (medium) | `fraud_underscore` | fraud 0.05 (low) vs expected medium |
| `v2_review_needed_14` | review_needed | canonical | ESCALATED | APPROVED | 0.05 (medium) | `fraud_underscore` | fraud 0.05 (low) vs expected medium |
| `v2_review_needed_15` | review_needed | paraphrase | ESCALATED | APPROVED | 0.30 (medium) | `fraud_underscore` | fraud 0.30 (low) vs expected medium |
| `v2_injection_02` | injection | noisy | REJECTED | APPROVED | 0.05 (high) | `injection_followed` | injection present; system APPROVED (score=0.05) |
| `v2_injection_03` | injection | canonical | REJECTED | APPROVED | 0.30 (high) | `injection_followed` | injection present; system APPROVED (score=0.3) |
| `v2_injection_10` | injection | paraphrase | REJECTED | APPROVED | 0.05 (high) | `injection_followed` | injection present; system APPROVED (score=0.05) |

**Where failures concentrate**

- slice `fraud_story`: 19/30 wrong
- slice `review_needed`: 10/15 wrong
- slice `implausible_amount`: 8/8 wrong
- slice `injection`: 4/10 wrong
- slice `edge`: 2/5 wrong
- tier `paraphrase`: 21/93 wrong (23%)
- tier `canonical`: 21/95 wrong (22%)
- tier `noisy`: 8/43 wrong (19%)

## 4. Extraction accuracy by phrasing tier

| System | Field | canonical | paraphrase | noisy |
|---|---|---|---|---|
| Rules-only | policy_id | 100% | 100% | 100% |
| Rules-only | amount | 100% | 88% | 74% |
| Rules-only | date | 100% | 100% | 100% |

