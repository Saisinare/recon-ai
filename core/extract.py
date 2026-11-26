"""Layer 2: the LLM reads messy bank descriptions and returns structured fields.

Each description is cached, so the same text is never sent twice. Without an
LLM (or if a call fails) the regex heuristics fill in.
"""
import hashlib

from .model import Ctx
from .rules import ref_matches
from .text import heuristic_extract, norm_key

SYSTEM = """You extract fields from bank transaction descriptions (Indian and international banks).
Return JSON: {"items":[{"i":<int>,"payee":<str>,"refs":[<str>],"kind":<str>}]}
- payee: the counterparty business or person, in plain words. Expand obvious abbreviations
  (AMZN MKTP -> Amazon, TCS -> Tata Consultancy Services). Empty string if none.
- refs: invoice, bill or PO numbers written as PREFIX+digits, e.g. INV1044, BILL2207. Never
  include UTR numbers, card numbers, phone numbers or UPI handles.
- kind: one of payment, payout, bank_fee, interest, refund, other.
Only JSON, no commentary."""


def _key(desc):
    return "x:" + hashlib.sha1(desc.encode()).hexdigest()


def extract_all(descs: dict, llm, store=None, batch=20) -> dict:
    """descs: {bank_id: description} -> {bank_id: {payee, refs, kind, source}}"""
    out, todo = {}, []
    for bid, d in descs.items():
        h = heuristic_extract(d)
        cached = store.cache_get(_key(d)) if store else None
        if cached:
            out[bid] = _merge(h, cached, "cache")
        else:
            out[bid] = dict(h, source="heuristic")
            todo.append(bid)
    if not (llm and llm.available and todo):
        return out
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        user = "\n".join(f"{n}: {descs[b]}" for n, b in enumerate(chunk))
        res = llm.json(SYSTEM, user)
        for item in (res or {}).get("items", []) if isinstance(res, dict) else []:
            try:
                bid = chunk[int(item["i"])]
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            clean = {"payee": str(item.get("payee") or "")[:80],
                     "refs": [norm_key(r) for r in (item.get("refs") or []) if norm_key(r)][:10],
                     "kind": str(item.get("kind") or "")}
            if store:
                store.cache_put(_key(descs[bid]), clean)
            out[bid] = _merge(out[bid], clean, "llm")
    return out


def _merge(h, llm_vals, source):
    return {"payee": llm_vals.get("payee") or h["payee"],
            "refs": list(dict.fromkeys(h["refs"] + llm_vals.get("refs", []))),
            "kind": llm_vals.get("kind") or h["kind"], "source": source}


def run(ctx: Ctx):
    descs = {bid: b.description for bid, b in ctx.bank.iterrows()}
    open_ids = set(ctx.open_bank().index)
    ctx.extracted = extract_all({b: d for b, d in descs.items() if b in open_ids}, ctx.llm, ctx.store)
    for bid in descs:
        ctx.extracted.setdefault(bid, dict(heuristic_extract(descs[bid]), source="heuristic"))
    ref_matches(ctx, {b: e["refs"] for b, e in ctx.extracted.items() if e["source"] != "heuristic"},
                "L2 LLM extract", 0.96)
