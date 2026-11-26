"""Layer 3: same amount, different spelling of the name.

Uses rapidfuzz plus abbreviation tricks by default. Turn on use_embeddings to add a
local sentence-transformers model (downloads ~90 MB the first time, then runs offline).
"""
from functools import lru_cache

from .model import Ctx, Match, Option
from .text import name_sim

_model = None


def _embed_sim(a, b):
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return float(_cos(a.upper(), b.upper()))


@lru_cache(maxsize=4096)
def _cos(a, b):
    va, vb = _model.encode([a, b], normalize_embeddings=True)
    return (va * vb).sum()


def sim(ctx: Ctx, a, b):
    s = name_sim(a, b)
    if ctx.cfg.use_embeddings and a and b:
        s = max(s, _embed_sim(a, b))
    return s


def run(ctx: Ctx):
    led = ctx.open_ledger()
    for bid, b in ctx.open_bank().iterrows():
        payee = ctx.extracted.get(bid, {}).get("payee", "")
        if bid in ctx.used_b or not payee:
            continue
        cands = sorted(((sim(ctx, payee, l.party), lid) for lid, l in led.iterrows()
                        if lid not in ctx.used_l and l.amount_cents == b.amount_cents
                        and ctx.in_window(b.date, l.date)), reverse=True)
        cands = [c for c in cands if c[0] >= 0.6]
        if not cands:
            continue
        best, lid = cands[0]
        clear = len(cands) == 1 or cands[1][0] < best - 0.1
        if best >= 0.7 and clear:
            l = led.loc[lid]
            ctx.add(Match([bid], [lid], "L3 fuzzy name", min(0.95, 0.7 + 0.25 * best),
                          f"Same amount; bank payee '{payee}' matches '{l.party}' (similarity {best:.2f})"))
        else:
            for s, lid in cands[:4]:
                ctx.add_option(bid, Option([lid], 0, f"same amount, name similarity {s:.2f}", s))
