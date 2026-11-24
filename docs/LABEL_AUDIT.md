# Label audit and code-review fixes (v1 → v2)

## Relabeled v1 cases (3 of 25)

| Case | Old label | New label | Why |
|---|---|---|---|
| `auto_05` | REJECTED / high | **ESCALATED / medium** | The old note said the label was "accepted as correct behaviour" because the model kept scoring it 0.90–0.98. That fits the label to the model. A theft with a same-day FIR at 98% of the limit is a textbook escalate. The model's high score is the failure, and the README already listed it as a "known calibration gap". |
| `auto_02` | ESCALATED / low | ESCALATED / **medium** | A documented claim above 80% of the limit is "medium" under the agent's own fraud prompt. `prop_02` was already labeled that way, so the three cases contradicted each other. |
| `health_02` | ESCALATED / low | ESCALATED / **medium** | Same as `auto_02`. |

**Consequence:** the old headline (24/25 = 96%) is not comparable with v2 numbers. Under
the corrected labels, the v1 run would have scored `auto_05` as a failure: about 23/25.

Not relabeled, but noted: `auto_03` claims ₹8,500 against a ₹10,000 deductible. It is
labeled APPROVED with a ₹0 payout. Many insurers would call that "nothing payable". The
rubric doesn't cover it, and the generator never produces a claim at or below the deductible.

## Agent fixes made during code review, before any v2 run

These were found by reading the code, not by tuning on v2 results:

1. **Policy-ID normalization** (`agents/tools.py`). The lookup did `strip().upper()`, so
   `pol012`, `POL 12` or `POL-12` all came back "not found" and were rejected. All three
   now resolve to `POL-012`.
2. **Policy-status check** (`agents/nodes.py`). The `status` column was never read. A
   lapsed or cancelled policy would have been approved.
3. **Start-date check** (`agents/nodes.py`). Only `end_date` was checked, so an incident
   *before* the policy started was treated as covered.

## Risks flagged, not changed

* The router's "documentation cap" (`agents/graph.py`) keyword-matches hospital names
  (`apollo`, `fortis`, `aiims`, `max hospital`), the same hospitals that appear in v1.
  That is a form of overfitting to the eval set. v2 uses 13 hospitals, so the
  per-slice results show whether the cap generalizes.
* The same router treats "no police" / "no FIR" as negative context. A legitimate claim
  saying "No police report was needed as no other vehicle was involved" loses the cap.
  `distractor_legit` contains these cases.
* `_check_policy_expired` fails open: if the date can't be parsed, the policy is treated
  as in force.

## Baseline changes after the first v2 run (1)

* `baselines/rules_only.py`: the sentence splitter broke "Rs. 7,67,000/-" after "Rs.". The
  baseline scored **73.2%** before the fix and **78.4%** after. This was a parsing bug,
  fixed so the comparison isn't made against a weakened baseline. The keyword lists and
  thresholds were not touched.
