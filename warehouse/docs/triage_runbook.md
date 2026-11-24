---
id: triage_runbook
title: Triage agent runbook
allowed_roles: [public]
---
## What the triage agent does
The triage agent reads a free-text claim from the retail book, extracts the policy ID, amount and date, looks the policy up in triage.policies, scores fraud risk from 0 to 1 and decides APPROVED, REJECTED or ESCALATED. Every decision is logged in triage.decisions.

## Decision rules
A fraud score above 0.75 is auto-rejected. Otherwise the claim is rejected if the policy is not found, not active, not in force on the incident date, or the amount exceeds the coverage limit. It is escalated to a human if the fraud score is 0.40 or more or the amount is above 80% of the coverage limit. Everything else is approved with payout = claimed amount minus deductible.

## Reason codes
The reason column in triage.decisions uses these codes: fraud_high, policy_not_found, policy_not_active, before_policy_start, policy_expired, exceeds_coverage, fraud_medium, high_ratio, approved, degraded (a component failed and the claim was escalated safely).

## On-call
If more than 30% of decisions in an hour are degraded, page the on-call ML engineer.
