"""Layer 1: deterministic rules. Exact references, learned rules, unique amounts."""
import re
from collections import defaultdict

from .model import Ctx, Match, Option
from .solver import solve_subsets
from .text import find_refs, name_sim, norm_key


def ref_matches(ctx: Ctx, refs_by_bank: dict, layer: str, conf: float):
    """Bank text names one or more open documents. Amount must match exactly to auto-match;
    otherwise the pairing is kept as an option for the judge."""
    index = defaultdict(list)
    for lid, l in ctx.open_ledger().iterrows():
        if l.doc_key:
            index[l.doc_key].append(lid)
    for bid, refs in refs_by_bank.items():
        if bid in ctx.used_b or not refs:
            continue
        lids = []
        for r in dict.fromkeys(norm_key(x) for x in refs):
            for lid in index.get(r, []):
                if lid not in ctx.used_l and lid not in lids:
                    lids.append(lid)
        if not lids:
            continue
        amt = ctx.bank.at[bid, "amount_cents"]
        total = sum(int(ctx.ledger.at[l, "amount_cents"]) for l in lids)
        docs = ", ".join(ctx.ledger.at[l, "doc_no"] for l in lids)
        if total == amt:
            ctx.add(Match([bid], lids, layer, conf if len(lids) == 1 else conf - 0.01,
                          f"Bank text references {docs} and the amount matches exactly"))
        else:
            party = ctx.ledger.at[lids[0], "party"]
            ctx.add_option(bid, Option(lids, total - amt,
                                       f"bank text references {docs} but the amounts differ by {(total - amt) / 100:,.2f}",
                                       name_sim(ctx.extracted.get(bid, {}).get("payee", "") or ctx.bank.at[bid, 'description'], party)))


def apply_learned(ctx: Ctx, rules: list[dict]):
    for rule in rules:
        try:
            rx = re.compile(rule["pattern"], re.I)
        except re.error:
            continue
        for bid, b in ctx.open_bank().iterrows():
            if bid in ctx.used_b or not rx.search(b.description):
                continue
            cands = [(lid, l.amount_cents) for lid, l in ctx.open_ledger().iterrows()
                     if (l.amount_cents > 0) == (b.amount_cents > 0)
                     and name_sim(l.party, rule["party"]) >= 0.9
                     and ctx.in_window(b.date, l.date, rule.get("date_window") or None)]
            sols = solve_subsets(b.amount_cents, cands, rule.get("tolerance_pct") or 0, 1, ctx.cfg.max_subset)
            if len(sols) != 1:
                continue
            ids, total = sols[0]
            diff = total - abs(b.amount_cents)
            m = Match([bid], ids, "L1 learned rule", 0.96,
                      f"Learned rule #{rule['id']} '{rule['name']}' ({len(ids)} item(s) from {rule['party']})"
                      + (f", difference {diff / 100:,.2f} within the rule's {rule['tolerance_pct']}% tolerance" if diff else ""),
                      difference_cents=diff if b.amount_cents > 0 else -diff)
            if ctx.add(m, force_status="auto" if m.confidence >= ctx.cfg.auto_threshold else None) and ctx.store:
                ctx.store.bump_rule(rule["id"])


def unique_amount(ctx: Ctx):
    led, bank = ctx.open_ledger(), ctx.open_bank()
    for bid, b in bank.iterrows():
        if bid in ctx.used_b:
            continue
        c = [lid for lid, l in led.iterrows()
             if lid not in ctx.used_l and l.amount_cents == b.amount_cents and ctx.in_window(b.date, l.date)]
        if len(c) != 1:
            continue
        l = led.loc[c[0]]
        back = [x for x, bb in bank.iterrows()
                if x not in ctx.used_b and bb.amount_cents == l.amount_cents and ctx.in_window(bb.date, l.date)]
        if len(back) == 1:
            ctx.add(Match([bid], c, "L1 exact", 0.90,
                          f"Only open item with exactly {abs(b.amount_cents) / 100:,.2f} in the date window ({l.party} {l.doc_no})"))


def run(ctx: Ctx):
    ref_matches(ctx, {bid: find_refs(b.text) for bid, b in ctx.open_bank().iterrows()}, "L1 exact", 1.0)
    if ctx.store:
        apply_learned(ctx, ctx.store.rules("active"))
    unique_amount(ctx)
