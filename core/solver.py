"""Layer 4: split payments. One bank line that pays several open items.

The search is exact integer math on cents. The LLM never adds numbers up.
"""
from .model import Ctx, Match, Option
from .text import name_sim


def solve_subsets(target, items, tol_pct=0.0, min_size=2, max_size=6, limit=10, budget=300_000):
    """Find groups of items whose absolute amounts sum to |target|, or up to tol_pct above it
    (a payout that had fees or TDS taken off). items = [(id, cents)]. Returns [(ids, total)]."""
    t = abs(target)
    hi = t + int(round(t * tol_pct / 100))
    items = sorted(items, key=lambda x: -abs(x[1]))
    vals = [abs(v) for _, v in items]
    suffix = [0] * (len(vals) + 1)
    for i in range(len(vals) - 1, -1, -1):
        suffix[i] = suffix[i + 1] + vals[i]
    out, steps = [], [0]

    def dfs(i, chosen, s):
        steps[0] += 1
        if len(out) >= limit or steps[0] > budget:
            return
        if t <= s <= hi and len(chosen) >= min_size:
            out.append(([items[k][0] for k in chosen], s))
            return
        if s > hi or len(chosen) == max_size or s + suffix[i] < t:
            return
        for k in range(i, len(items)):
            if s + vals[k] <= hi:
                dfs(k + 1, chosen + [k], s + vals[k])

    dfs(0, [], 0)
    return out


def run(ctx: Ctx):
    cfg = ctx.cfg
    led = ctx.open_ledger()
    for bid, b in ctx.open_bank().iterrows():
        if bid in ctx.used_b:
            continue
        amt = b.amount_cents
        payee = ctx.extracted.get(bid, {}).get("payee", "")
        cands = []
        for lid, l in led.iterrows():
            if lid in ctx.used_l or (l.amount_cents > 0) != (amt > 0):
                continue
            if abs(l.amount_cents) > abs(amt) * (1 + cfg.fee_tolerance_pct / 100) + 1:
                continue
            if not ctx.in_window(b.date, l.date):
                continue
            cands.append((lid, l.amount_cents, name_sim(payee, l.party) if payee else 0.0, abs((b.date - l.date).days)))
        if not cands:
            continue
        party = [c for c in cands if c[2] >= 0.6]
        same_party = len(party) >= 2
        pool = sorted(party if same_party else cands, key=lambda c: (-c[2], c[3]))[: cfg.max_candidates]
        sims = {c[0]: c[2] for c in cands}

        exact = solve_subsets(amt, [(c[0], c[1]) for c in pool], 0, 2, cfg.max_subset)
        if len(exact) == 1 and same_party:
            ids, _ = exact[0]
            names = sorted({led.at[i, "party"] for i in ids})
            ctx.add(Match([bid], ids, "L4 split solver", 0.92,
                          f"{len(ids)} open items from {', '.join(names)} add up exactly to this payment"))
            continue
        for ids, _ in exact:
            ctx.add_option(bid, Option(ids, 0, f"{len(ids)} open items add up exactly",
                                       sum(sims[i] for i in ids) / len(ids)))
        if party and not exact:
            near = solve_subsets(amt, [(c[0], c[1]) for c in party], cfg.fee_tolerance_pct, 1, cfg.max_subset)
            for ids, total in near:
                diff = total - abs(amt)
                if diff == 0:
                    continue
                ctx.add_option(bid, Option(ids, diff if amt > 0 else -diff,
                                           f"open items from the same party total {diff / 100:,.2f} more "
                                           f"({diff / abs(amt) * 100:.2f}%), possibly a fee or TDS deduction",
                                           sum(sims[i] for i in ids) / len(ids)))
