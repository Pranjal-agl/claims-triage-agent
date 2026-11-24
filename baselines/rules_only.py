"""
baselines/rules_only.py

Rules-only baseline: zero LLM calls. Regex extraction + keyword fraud
heuristics + the same deterministic decision thresholds the agent uses.

This is the "what would a competent engineer ship without an LLM?" bar.
It was written against the phrasing of the 25 v1 cases only and was NOT
tuned on v2 results — the gap between canonical and paraphrase/noisy tiers
is the point of the comparison.

Pipeline
  1. policy_id     regex  POL-NNN (tolerates "POL 12", "pol012")
  2. amount        currency-marked numbers: "Rs 1,23,000", "₹1.2 lakh", "INR 85000",
                   "1.95 crore"; prefers the one in a "claim/request/total" sentence
  3. incident_date ISO, "14 March 2025", "March 14, 2025", "14/03/2025"
  4. policy lookup same SQLite DB as the agent
  5. fraud score   keyword weights with a small negation window
  6. decision      identical rule order / thresholds as agents/nodes.py
"""

from __future__ import annotations

import re
import time
from datetime import date
from typing import Any

from agents.tools import lookup_policy, normalize_policy_id

# ── extraction ───────────────────────────────────────────────────────────────

_POL = re.compile(r"\bPOL[\s\-_]*\d{1,5}\b", re.I)
_MONEY = re.compile(
    r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|l\b|crore|cr\b|k\b)?"
    r"|([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore)",
    re.I,
)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_ISO = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
_DMY_TXT = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]{3,9})\.?,?\s+(20\d\d)\b")
_MDY_TXT = re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b")
_DMY_NUM = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d\d)\b")
_CLAIM_WORDS = ("claim", "request", "total", "seeking", "bill")


def _money_value(num: str, unit: str | None) -> float | None:
    try:
        v = float(num.replace(",", ""))
    except ValueError:
        return None
    u = (unit or "").lower()
    if u in ("lakh", "lac", "l"):
        v *= 100_000
    elif u in ("crore", "cr"):
        v *= 10_000_000
    elif u == "k":
        v *= 1000
    return v


def extract_amount(text: str) -> float:
    best_claim, all_vals = None, []
    # split on sentence ends, but not after the "Rs." abbreviation
    for sent in re.split(r"(?<!\bRs\.)(?<!\brs\.)(?<=[.!?])\s+", text):
        for m in _MONEY.finditer(sent):
            num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
            v = _money_value(num, unit)
            if v is None or v < 100:
                continue
            all_vals.append(v)
            if any(w in sent.lower() for w in _CLAIM_WORDS):
                best_claim = v  # last amount in a claim-ish sentence wins
    if best_claim is not None:
        return best_claim
    return max(all_vals) if all_vals else 0.0


def extract_date(text: str) -> str | None:
    for rx, order in ((_ISO, "ymd"), (_DMY_TXT, "dMy"), (_MDY_TXT, "Mdy"), (_DMY_NUM, "dmy")):
        m = rx.search(text)
        if not m:
            continue
        try:
            if order == "ymd":
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif order == "dMy":
                d, mo, y = int(m.group(1)), _MONTHS[m.group(2)[:3].lower()], int(m.group(3))
            elif order == "Mdy":
                mo, d, y = _MONTHS[m.group(1)[:3].lower()], int(m.group(2)), int(m.group(3))
            else:
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return date(y, mo, d).isoformat()
        except (KeyError, ValueError):
            continue
    return None


def extract_type(text: str) -> str:
    t = text.lower()
    for kw, typ in (("stolen", "theft"), ("theft", "theft"), ("burgl", "theft"), ("fire", "fire"),
                    ("hospital", "medical"), ("surgery", "medical"), ("collision", "accident"),
                    ("accident", "accident"), ("flood", "property_damage"), ("pipe", "property_damage")):
        if kw in t:
            return typ
    return "other"


# ── fraud heuristics ─────────────────────────────────────────────────────────

POSITIVE_DOCS = ["fir filed", "fir lodged", "police report", "discharge summary", "hospital bill",
                 "invoice", "receipt", "estimate", "quote", "engineer report", "fire brigade report",
                 "documents ready", "documents attached", "attached", "enclosed"]
STRONG_RED_FLAGS = ["never filed", "no police report", "didn't file", "did not file", "no fir",
                    "without asking for documents", "without documents", "no receipts", "no documents",
                    "cannot name", "can't name", "rather not", "secret", "settled privately",
                    "changed my mind", "several accidents", "don't remember", "no receipts or dates",
                    "documents because they all burned", "ignore all previous", "ignore previous",
                    "system note", "admin override", "pre-verified"]
WEAK_RED_FLAGS = ["urgent", "immediately", "quickly", "today", "full coverage limit", "full policy limit",
                  "exactly"]
MEDIUM_FLAGS = ["will send", "later", "pending", "not released", "yet to"]
_NEG = re.compile(r"\b(no|not|never|without|didn't|don't)\b[^.]{0,25}$", re.I)


def fraud_score(text: str, ratio: float, found: bool) -> tuple[float, list[str]]:
    t = text.lower()
    flags: list[str] = []
    score = 0.15
    if not found:
        score += 0.65
        flags.append("policy_not_found")
    hits = [k for k in STRONG_RED_FLAGS if k in t]
    if hits:
        score += 0.65
        flags += hits
    weak = [k for k in WEAK_RED_FLAGS if k in t]
    score += 0.08 * len(weak)
    flags += weak
    if any(k in t for k in MEDIUM_FLAGS):
        score += 0.30
        flags.append("docs_pending")
    has_docs = False
    for k in POSITIVE_DOCS:
        i = t.find(k)
        if i >= 0 and not _NEG.search(t[max(0, i - 30):i]):
            has_docs = True
            break
    if has_docs:
        score -= 0.10
    else:
        score += 0.15
        flags.append("no_documentation_mentioned")
    if ratio > 0.8:
        score += 0.30
        flags.append("high_ratio")
    if len(text) < 90:
        score += 0.30
        flags.append("very_short_claim")
    return round(max(0.0, min(1.0, score)), 3), flags


# ── decision (same order/thresholds as agents/nodes.py) ──────────────────────


def _d(s):
    try:
        return date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


def decide(extracted: dict, policy: dict, score: float) -> tuple[str, str]:
    claimed = extracted["claimed_amount"]
    if score > 0.75:
        return "REJECTED", f"Auto-rejected: fraud score {score:.2f}"
    if not policy.get("found"):
        return "REJECTED", "Policy not found."
    if str(policy.get("status", "active")).lower() != "active":
        return "REJECTED", f"Policy status {policy.get('status')}."
    inc, start, end = _d(extracted.get("incident_date")), _d(policy.get("start_date")), _d(policy.get("end_date"))
    if inc and start and inc < start:
        return "REJECTED", "Incident before policy start."
    if inc and end and inc > end:
        return "REJECTED", "Policy expired before incident."
    cov = policy.get("coverage_limit", 0)
    if claimed > cov > 0:
        return "REJECTED", "Claim exceeds coverage limit."
    ratio = claimed / cov if cov else 999
    if score >= 0.4 or ratio > 0.8:
        return "ESCALATED", f"Escalated: fraud={score:.2f}, ratio={ratio:.2f}"
    return "APPROVED", "Within limits, low risk."


def triage(claim_text: str) -> dict[str, Any]:
    """Return a state dict shaped like the agent's final state."""
    t0 = time.perf_counter()
    m = _POL.search(claim_text)
    pid = normalize_policy_id(m.group(0)) if m else ""
    extracted = {
        "policy_id": pid,
        "claimant_name": "",
        "incident_type": extract_type(claim_text),
        "incident_date": extract_date(claim_text),
        "claimed_amount": extract_amount(claim_text),
        "description": "",
    }
    t1 = time.perf_counter()
    policy = lookup_policy(pid) if pid else {"found": False, "policy_id": ""}
    cov = policy.get("coverage_limit", 0) if policy.get("found") else 0
    ratio = extracted["claimed_amount"] / cov if cov else 999
    score, flags = fraud_score(claim_text, ratio, policy.get("found", False))
    t2 = time.perf_counter()
    decision, why = decide(extracted, policy, score)
    deductible = policy.get("deductible", 0) if policy.get("found") else 0
    payout = max(0.0, extracted["claimed_amount"] - deductible) if decision != "REJECTED" else 0.0
    t3 = time.perf_counter()
    return {
        "extracted": extracted,
        "policy": policy,
        "fraud": {"fraud_score": score, "flags": flags, "reasoning": "keyword heuristics"},
        "decision": {"decision": decision, "justification": why, "recommended_payout": payout},
        "_node_latencies": {"extract": round(t1 - t0, 5), "lookup_policy": 0.0,
                            "assess_fraud": round(t2 - t1, 5), "decide": round(t3 - t2, 5)},
    }
