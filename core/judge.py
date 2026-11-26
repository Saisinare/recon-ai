"""Layer 5: the LLM chooses between the candidate options the earlier layers left.

It returns a choice, a confidence and a reason. It never computes amounts: every
difference it sees was calculated in code. Without an LLM a scoring heuristic is used,
and its answers are always sent to review.
"""
import json

from .ingest import fmt
from .model import Ctx, Match

SYSTEM = """You are a careful accountant reconciling a bank statement against open ledger items.
You get one bank transaction and numbered candidate options (each one or more ledger items).
All amounts and differences are already calculated; do not recompute them.
Pick the option that is the true match, or -1 if none is convincing.
Typical legitimate differences: payment processor fees (2-3%), TDS deducted at source (1-2% or 10%),
bank charges. Unrelated parties or large unexplained gaps mean -1.
Return JSON: {"choice": <int>, "confidence": <0..1>, "reason": "<one sentence>"}"""


def _describe(ctx, bid, opts):
    b = ctx.bank.loc[bid]
    ex = ctx.extracted.get(bid, {})
    lines = [f"BANK {bid}: {b.date.date()} amount {fmt(b.amount_cents)} | \"{b.description}\" | "
             f"payee guess: {ex.get('payee', '')} | kind: {ex.get('kind', '')}", "OPTIONS:"]
    for n, o in enumerate(opts):
        items = "; ".join(f"{ctx.ledger.at[l, 'party']} {ctx.ledger.at[l, 'doc_no']} "
                          f"{ctx.ledger.at[l, 'date'].date()} {fmt(ctx.ledger.at[l, 'amount_cents'])}"
                          for l in o.ledger_ids)
        lines.append(f"{n}: [{items}] difference (ledger - bank) {fmt(o.diff_cents)} | {o.note}")
    return "\n".join(lines)


def _heuristic(ctx, bid, opts):
    amt = abs(ctx.bank.at[bid, "amount_cents"])
    scored = []
    for n, o in enumerate(opts):
        gap = min(1.0, abs(o.diff_cents) / max(amt, 1) * 10)
        bonus = 0.1 if "references" in o.note else 0
        scored.append((0.6 * o.name_sim + 0.4 * (1 - gap) + bonus, n))
    scored.sort(reverse=True)
    best, n = scored[0]
    margin = best - scored[1][0] if len(scored) > 1 else 1
    if best < 0.55 or margin < 0.05:
        return -1, 0, ""
    conf = min(0.85, best) if margin >= 0.1 else min(0.6, best)
    return n, conf, f"Heuristic pick: {opts[n].note}"


def run(ctx: Ctx):
    for bid, opts in list(ctx.options.items()):
        if bid in ctx.used_b:
            continue
        opts = [o for o in opts if not any(l in ctx.used_l for l in o.ledger_ids)][:5]
        if not opts:
            continue
        choice, conf, reason, layer = -1, 0.0, "", "L5 judge (heuristic)"
        if ctx.llm and ctx.llm.available:
            res = ctx.llm.json(SYSTEM, _describe(ctx, bid, opts))
            if isinstance(res, dict) and "choice" in res:
                try:
                    choice = int(res["choice"])
                    conf = max(0.0, min(0.95, float(res.get("confidence", 0))))
                    reason = str(res.get("reason", ""))[:300]
                    layer = "L5 LLM judge"
                except (TypeError, ValueError):
                    choice = -1
        if layer == "L5 judge (heuristic)":
            choice, conf, reason = _heuristic(ctx, bid, opts)
            conf = min(conf, ctx.cfg.auto_threshold - 0.01)   # heuristic picks always get reviewed
        if 0 <= choice < len(opts):
            o = opts[choice]
            ctx.add(Match([bid], o.ledger_ids, layer, conf, reason or o.note, difference_cents=o.diff_cents))
