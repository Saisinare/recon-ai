"""Runs the five layers in order. Each layer only sees what the earlier ones left open."""
import uuid
from collections import Counter
from dataclasses import dataclass

import pandas as pd

from . import extract, fuzzy, judge, rules, solver
from .model import Config, Ctx
from .text import norm_key

LIVE = ("auto", "suggested", "approved")


@dataclass
class Result:
    ctx: Ctx

    @property
    def matches(self):
        return self.ctx.matches

    def live(self):
        return [m for m in self.matches if m.status in LIVE]

    def matched_bank(self):
        return {b for m in self.live() for b in m.bank_ids}

    def matched_ledger(self):
        return {l for m in self.live() for l in m.ledger_ids}

    def unmatched_bank(self):
        dups = {d[1] for d in self.ctx.duplicates if d[0] == "bank"}
        b = self.ctx.bank
        return b[~b.index.isin(self.matched_bank() | dups)]

    def unmatched_ledger(self):
        dups = {d[1] for d in self.ctx.duplicates if d[0] == "ledger"}
        l = self.ctx.ledger
        return l[~l.index.isin(self.matched_ledger() | dups)]

    def matches_df(self):
        return pd.DataFrame([m.as_row() for m in self.matches])

    def stats(self):
        live = self.live()
        n_bank = len(self.ctx.bank)
        return {
            "bank_rows": n_bank, "ledger_rows": len(self.ctx.ledger),
            "auto": sum(m.status == "auto" for m in live),
            "approved": sum(m.status == "approved" for m in live),
            "needs_review": sum(m.status == "suggested" for m in live),
            "rejected": sum(m.status == "rejected" for m in self.matches),
            "unmatched_bank": len(self.unmatched_bank()), "unmatched_ledger": len(self.unmatched_ledger()),
            "duplicates": len(self.ctx.duplicates),
            "bank_rows_matched_pct": round(100 * len(self.matched_bank()) / max(n_bank, 1), 1),
            "by_layer": dict(Counter(m.layer for m in live)),
            "llm_calls": getattr(self.ctx.llm, "calls", 0),
            "difference_total": sum(m.difference_cents for m in live) / 100,
        }


def find_duplicates(ctx: Ctx):
    seen = {}
    for bid, b in ctx.bank.iterrows():
        k = (b.date, b.amount_cents, norm_key(b.description))
        if k in seen:
            ctx.duplicates.append(("bank", bid, seen[k]))
            ctx.used_b.add(bid)
        else:
            seen[k] = bid
    seen = {}
    for lid, l in ctx.ledger.iterrows():
        if not l.doc_key:
            continue
        k = (norm_key(l.party), l.doc_key, l.amount_cents)
        if k in seen:
            ctx.duplicates.append(("ledger", lid, seen[k]))
            ctx.used_l.add(lid)
        else:
            seen[k] = lid


def run(bank: pd.DataFrame, ledger: pd.DataFrame, cfg: Config | None = None, llm=None, store=None) -> Result:
    ctx = Ctx(bank=bank, ledger=ledger, cfg=cfg or Config(), llm=llm, store=store,
              run_id=uuid.uuid4().hex[:8])
    find_duplicates(ctx)
    for layer in (rules, extract, fuzzy, solver, judge):
        layer.run(ctx)
    if store:
        store.log("run", reason=f"{len(bank)} bank / {len(ledger)} ledger rows, "
                                f"{len(ctx.matches)} matches", run_id=ctx.run_id)
        for m in ctx.matches:
            store.log(f"match:{m.status}", m, run_id=ctx.run_id)
        for kind, dup, orig in ctx.duplicates:
            store.log("duplicate", reason=f"{kind} {dup} duplicates {orig}", run_id=ctx.run_id)
    return Result(ctx)
