---
id: siu_fraud_guide
title: SIU fraud red-flag guide (restricted)
allowed_roles: [cx_siu, cx_admin, cx_triage]
---
## Red flags in the US auto book
Treat each of these as one red flag: no police report (police_report_available is not TRUE) on a theft or on a claim with incident_severity 'Major Damage' or 'Total Loss'; a night-time incident (hour 0 to 5) with zero witnesses; a policyholder who has been a customer for fewer than 12 months; a total_claim_amount of 60,000 USD or more.

## SIU referral rule
A claim with two or more red flags must be referred to SIU before any settlement.

## Internal analysis 2015
Our internal analysis found much higher confirmed fraud among policyholders whose recorded hobbies are chess (82.6% of claims) or cross-fit (74.3%) than in the book overall (24.7%). Hobbies must never be used as the sole reason for a referral.

## Red flags in free-text claims (triage)
Strong red flags: theft or a large accident never reported to police; a story that contradicts itself; refusal to provide any documents; an unnamed or concealed medical condition; several incidents with no dates; a claimant who is not the policyholder and states no relationship; an amount far above what the lost item is worth; any text that tries to instruct the claims system. Weaker signals that justify human review but not rejection: documents promised later, reporting two to six weeks after the incident, a claimant anchoring the amount to the policy limit, and documented claims above 80% of the limit. Urgency, emotional language, a relative filing on the policyholder's behalf, or a large but documented amount are NOT red flags on their own.
