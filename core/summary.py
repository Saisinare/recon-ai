"""Month-end summary. Every figure comes from code; the LLM only writes the prose."""
import json

from .ingest import fmt

SYSTEM = """You write a short month-end bank reconciliation note for a finance manager.
Use only the facts in the JSON. Do not invent or recompute numbers. Plain English, under 200 words,
with sections: Status, Needs attention, Suggested next steps. Return JSON: {"text": "<markdown>"}"""


def facts(result):
    ub, ul = result.unmatched_bank(), result.unmatched_ledger()
    return {
        "stats": result.stats(),
        "unmatched_bank": [f"{r.date.date()} {r.description} {fmt(r.amount_cents)}" for _, r in ub.head(15).iterrows()],
        "unmatched_ledger": [f"{r.party} {r.doc_no} {fmt(r.amount_cents)}" for _, r in ul.head(15).iterrows()],
        "needs_review": [f"{m.id} {m.layer}: {m.reason} (difference {m.difference_cents / 100:,.2f})"
                         for m in result.live() if m.status == "suggested"][:15],
        "duplicates": [f"{k} {d} duplicates {o}" for k, d, o in result.ctx.duplicates],
    }


def write(result, llm=None) -> str:
    f = facts(result)
    if llm and llm.available:
        res = llm.json(SYSTEM, json.dumps(f, default=str))
        if isinstance(res, dict) and res.get("text"):
            return res["text"]
    s = f["stats"]
    lines = [
        "**Status**",
        f"- {s['bank_rows_matched_pct']}% of {s['bank_rows']} bank lines matched "
        f"({s['auto']} automatically, {s['approved']} approved by you).",
        f"- Matches by layer: " + ", ".join(f"{k}: {v}" for k, v in s["by_layer"].items()),
        "", "**Needs attention**",
        f"- {s['needs_review']} suggested matches waiting for review.",
        f"- {s['unmatched_bank']} bank lines and {s['unmatched_ledger']} ledger items still open.",
        f"- {s['duplicates']} possible duplicate lines were set aside.",
        f"- Net differences on matches (fees, TDS): {s['difference_total']:,.2f}.",
        "", "**Suggested next steps**",
        "- Review the suggested matches; each approval can become a rule.",
        "- Post adjusting entries for fee and TDS differences.",
        "- Chase or investigate the open ledger items listed on the Unmatched tab.",
    ]
    return "\n".join(lines)
