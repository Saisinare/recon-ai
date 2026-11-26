"""Shared types and the per-run context."""
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Config:
    auto_threshold: float = 0.90      # at or above: auto-matched; below: sent to review
    date_window_days: int = 45        # how far a payment may lag its invoice
    date_lead_days: int = 5           # how far a payment may come before its invoice date
    fee_tolerance_pct: float = 3.5    # payouts / TDS short-payments the solver will consider
    max_subset: int = 6               # most invoices one payment may cover
    max_candidates: int = 18          # open items the solver searches per payment
    use_embeddings: bool = False      # local sentence-transformers model for layer 3


@dataclass
class Match:
    bank_ids: list
    ledger_ids: list
    layer: str
    confidence: float
    reason: str
    status: str = "auto"             # auto | suggested | approved | rejected
    difference_cents: int = 0        # ledger total minus bank amount (fees, TDS)
    id: str = ""

    def as_row(self):
        return {"match": self.id, "status": self.status, "layer": self.layer,
                "confidence": self.confidence, "bank": ";".join(self.bank_ids),
                "ledger": ";".join(self.ledger_ids),
                "difference": self.difference_cents / 100, "reason": self.reason}


@dataclass
class Option:
    """A candidate answer the judge (layer 5) chooses between."""
    ledger_ids: list
    diff_cents: int
    note: str
    name_sim: float = 0.0


@dataclass
class Ctx:
    bank: pd.DataFrame
    ledger: pd.DataFrame
    cfg: Config
    llm: object
    store: object
    run_id: str = ""
    used_b: set = field(default_factory=set)
    used_l: set = field(default_factory=set)
    matches: list = field(default_factory=list)
    options: dict = field(default_factory=dict)       # bank_id -> [Option]
    extracted: dict = field(default_factory=dict)     # bank_id -> {payee, refs, kind}
    duplicates: list = field(default_factory=list)    # (kind, dup_id, original_id)

    def add(self, m: Match, force_status: str | None = None):
        if any(b in self.used_b for b in m.bank_ids) or any(l in self.used_l for l in m.ledger_ids):
            return False
        m.confidence = round(float(m.confidence), 2)
        if force_status:
            m.status = force_status
        elif m.difference_cents != 0:
            m.status = "suggested"   # a difference needs a person and an adjusting entry
        else:
            m.status = "auto" if m.confidence >= self.cfg.auto_threshold else "suggested"
        m.id = f"M{len(self.matches) + 1:03d}"
        self.matches.append(m)
        self.used_b.update(m.bank_ids)
        self.used_l.update(m.ledger_ids)
        return True

    def open_bank(self):
        return self.bank[~self.bank.index.isin(self.used_b)]

    def open_ledger(self):
        return self.ledger[~self.ledger.index.isin(self.used_l)]

    def in_window(self, bank_date, ledger_date, window=None):
        w = window or self.cfg.date_window_days
        d = (bank_date - ledger_date).days
        return -self.cfg.date_lead_days <= d <= w

    def add_option(self, bid, opt: Option):
        lst = self.options.setdefault(bid, [])
        if not any(set(o.ledger_ids) == set(opt.ledger_ids) for o in lst):
            lst.append(opt)
