---
id: kpi_definitions
title: Claims KPI definitions (official glossary)
allowed_roles: [public]
---
## Reporting period
The US auto book in the warehouse covers incidents from 2015-01-01 to 2015-03-01 (ins.claims.incident_date). All "current" or "this period" figures refer to that window. Do not use now().

## Region
A claim's region is the state where the POLICY was written (ins.policies.state: OH, IL or IN), not the state where the incident happened (ins.claims.incident_state). "Ohio claims" therefore means claims on policies with state = 'OH'.

## Large loss
A large loss is a claim with total_claim_amount of 60,000 USD or more.

## Serious claim
A serious claim is one whose incident_severity is 'Major Damage' or 'Total Loss'.

## Documented claim
A claim is documented when police_report_available is TRUE. Unknown values (NULL) count as not documented.

## Fraud rate
Fraud rate is the share of claims with fraud_reported = TRUE (an SIU determination), expressed as a percentage of all claims in scope.

## Night-time incident
An incident is night-time when incident_hour is between 0 and 5 inclusive.

## Injury share
Injury share is sum(injury_claim) divided by sum(total_claim_amount), as a percentage.

## Triage auto-decision rate
For the triage agent's decision log (triage.decisions), the auto-decision rate is the share of decisions that are APPROVED or REJECTED, i.e. not ESCALATED to a human.
