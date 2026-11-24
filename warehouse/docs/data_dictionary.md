---
id: data_dictionary
title: Claims warehouse data dictionary
allowed_roles: [public]
---
## Schemas
Schema ins holds the historical US auto book: ins.policies (one row per policy), ins.policyholders, ins.insured_vehicles and ins.claims (one claim per policy, amounts in USD). Schema triage holds the triage agent's retail book (triage.policies, amounts in INR) and its decision log (triage.decisions).

## Combined single limit
policy_csl such as '250/500' means bodily-injury cover of 250,000 USD per person and 500,000 USD per accident. These are also stored as bi_limit_per_person and bi_limit_per_accident.

## Claim amounts
total_claim_amount = injury_claim + property_claim + vehicle_claim, in USD.

## Unknown values
In ins.claims, NULL in collision_type, property_damage or police_report_available means the value was not recorded. authorities_contacted = 'None' means nobody was contacted.

## Triage decision log
triage.decisions has one row per claim decided by the triage service: decision (APPROVED, REJECTED, ESCALATED), reason (a short code, see the triage runbook), fraud_score (0 to 1), claimed_amount and payout in INR, system (which triage system produced it) and decided_at.
