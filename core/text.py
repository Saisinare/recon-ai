"""Text helpers: reference keys, payee cleanup and name similarity. No AI here."""
import re
from rapidfuzz import fuzz

REF_RX = re.compile(r"\b(INV(?:OICE)?|BILL|PO)\s*(?:NO\.?|#)?\s*[-:/]?\s*(\d{3,})", re.I)

NOISE = {
    "NEFT", "IMPS", "RTGS", "UPI", "ACH", "POS", "ECOM", "TRF", "TRANSFER", "CR", "DR",
    "PAYMENT", "PMT", "REF", "TXN", "IN", "INR", "BY", "TO", "FROM", "ONLINE", "P2A",
    "P2M", "PAYOUT", "BATCH", "PART", "NO", "INV", "INVOICE", "BILL", "TDS", "ADJ",
}
STOP = {"LTD", "PVT", "PRIVATE", "LIMITED", "INDIA", "IN", "THE", "AND", "CO", "INC", "LLP"}


def norm_key(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def find_refs(text: str) -> list[str]:
    """Invoice / bill / PO numbers written as PREFIX+digits, e.g. INV1044."""
    out = []
    for prefix, num in REF_RX.findall(text or ""):
        p = prefix.upper()
        p = "INV" if p.startswith("INV") else p
        out.append(p + num)
    return list(dict.fromkeys(out))


def heuristic_payee(desc: str) -> str:
    best = ""
    for seg in re.split(r"[/|*:,]+| {2,}", desc or ""):
        words = [w for w in seg.split()
                 if not re.search(r"[\d@_]", w) and w.upper().strip(".-") not in NOISE
                 and len(w.strip(".-")) > 1]
        cand = " ".join(words).strip()
        if len(re.sub(r"[^A-Za-z]", "", cand)) >= 3 and len(cand) > len(best):
            best = cand
    return best


def heuristic_kind(desc: str) -> str:
    d = (desc or "").upper()
    if re.search(r"CHARGE|FEE|SMS ALERT|GST ON", d):
        return "bank_fee"
    if re.search(r"INTEREST|INT\.? ?CR", d):
        return "interest"
    if "PAYOUT" in d:
        return "payout"
    if "REFUND" in d or "REVERSAL" in d:
        return "refund"
    return "payment"


def heuristic_extract(desc: str) -> dict:
    return {"payee": heuristic_payee(desc), "refs": find_refs(desc), "kind": heuristic_kind(desc)}


def _tokens(name: str) -> list[str]:
    s = str(name or "").upper().replace("&", " AND ")
    return [t for t in re.findall(r"[A-Z]+", s) if t not in STOP]


def _skel(t: str) -> str:
    return t[0] + re.sub(r"[AEIOU]", "", t[1:])


def name_sim(a: str, b: str) -> float:
    """0..1 similarity that copes with bank truncation (TATA CONSULTANC),
    abbreviations (AMZN = AMAZON) and acronyms (TCS)."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    sa, sb = " ".join(ta), " ".join(tb)
    s = fuzz.token_set_ratio(sa, sb) / 100
    if min(len(sa), len(sb)) >= 5:
        s = max(s, fuzz.partial_ratio(sa, sb) / 100 * 0.95)
    if {_skel(t) for t in ta if len(t) >= 4} & {_skel(t) for t in tb if len(t) >= 4}:
        s = max(s, 0.85)
    acr_a, acr_b = "".join(t[0] for t in ta), "".join(t[0] for t in tb)
    if (len(acr_b) >= 2 and acr_b in ta) or (len(acr_a) >= 2 and acr_a in tb):
        s = max(s, 0.85)
    return round(s, 3)
