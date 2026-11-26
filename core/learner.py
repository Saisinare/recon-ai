"""Turn a person's correction into a small, readable rule.

The rule is data, not code: a regex on the bank description, the ledger party, a date
window and an optional fee tolerance. It only becomes active after someone approves it.
"""
import re

from .text import heuristic_payee

SYSTEM = """You write one matching rule for a bank reconciliation system.
Given a bank description that a person matched to ledger party P, write a case-insensitive
Python regex that matches the STABLE part of the description identifying this payer
(company name, product words like PAYOUT), and NOT ids, dates, amounts, UTR or card numbers.
Keep it short and simple: no nested quantifiers, under 60 characters.
Return JSON: {"name": "<short rule name>", "pattern": "<regex>"}"""

_DANGEROUS = re.compile(r"\([^)]*[+*][^)]*\)[+*{]")


def safe_pattern(p: str, example: str) -> bool:
    if not p or len(p) > 80 or _DANGEROUS.search(p):
        return False
    try:
        return re.search(p, example, re.I) is not None
    except re.error:
        return False


def fallback_pattern(desc: str) -> str:
    words = re.findall(r"[A-Za-z]{2,}", heuristic_payee(desc))[:2]
    if "PAYOUT" in desc.upper() and "PAYOUT" not in [w.upper() for w in words]:
        words.append("PAYOUT")
    if not words:
        words = re.findall(r"[A-Za-z]{3,}", desc)[:2]
    return r"\b" + r"\W+".join(re.escape(w) for w in words) + r"\b"


def propose(bank_row, ledger_rows, llm=None, all_descriptions=()):
    parties = [r.party for r in ledger_rows]
    party = max(set(parties), key=parties.count)
    total = sum(abs(int(r.amount_cents)) for r in ledger_rows)
    amt = abs(int(bank_row.amount_cents))
    diff_pct = (total - amt) / amt * 100 if amt else 0
    tol = round(diff_pct + 0.5, 1) if diff_pct > 0 else 0.0

    name, pattern = f"{party} payments", None
    if llm and llm.available:
        res = llm.json(SYSTEM, f"Description: {bank_row.description}\nParty P: {party}")
        if isinstance(res, dict) and safe_pattern(str(res.get("pattern", "")), bank_row.description):
            pattern, name = res["pattern"], str(res.get("name") or name)[:60]
    if not pattern:
        pattern = fallback_pattern(bank_row.description)
        if not safe_pattern(pattern, bank_row.description):
            pattern = re.escape(bank_row.description[:30])
    rx = re.compile(pattern, re.I)
    hits = sum(1 for d in all_descriptions if rx.search(d))
    return {"name": name, "pattern": pattern, "party": party, "date_window": 45,
            "tolerance_pct": tol, "example": bank_row.description, "hits_now": hits}
