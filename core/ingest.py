"""Load bank and ledger files (CSV / Excel) and map them onto one clean schema.

Amounts are stored as integer cents (paise) so every comparison is exact.
Sign convention: + money in, - money out. Ledger rows use the sign of the
bank movement they expect (customer invoice +, vendor bill -).
"""
import io
import re
import pandas as pd

from .text import norm_key

BANK_COLS = {
    "id": ["id", "txn id", "transaction id"],
    "date": ["date", "txn date", "transaction date", "value date", "posting date"],
    "description": ["description", "narration", "details", "particulars", "remarks", "memo"],
    "amount": ["amount", "amt", "net amount"],
    "credit": ["credit", "deposit", "deposits", "cr amount"],
    "debit": ["debit", "withdrawal", "withdrawals", "dr amount"],
    "reference": ["reference", "ref", "ref no", "cheque no", "utr", "chq/ref no"],
}
LEDGER_COLS = {
    "id": ["id", "entry id", "line id"],
    "date": ["date", "invoice date", "doc date", "posting date", "bill date"],
    "party": ["party", "customer", "vendor", "name", "counterparty", "payee", "account name"],
    "doc_no": ["doc_no", "invoice_no", "invoice no", "doc no", "document no", "bill no", "number"],
    "amount": ["amount", "total", "open amount", "balance", "value"],
    "type": ["type", "doc type"],
    "description": ["description", "memo", "narration"],
}


def read_any(src, name: str = "") -> pd.DataFrame:
    name = (name or getattr(src, "name", "") or str(src)).lower()
    if isinstance(src, (bytes, bytearray)):
        src = io.BytesIO(src)
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(src, dtype=str)
    return pd.read_csv(src, dtype=str, keep_default_na=False)


def _col(df: pd.DataFrame, names: list[str]):
    lookup = {c.strip().lower(): c for c in df.columns}
    for n in names:
        if n in lookup:
            return lookup[n]
    return None


def to_cents(v) -> int:
    s = str(v or "").strip()
    if not s:
        return 0
    neg = s.startswith("(") and s.endswith(")") or s.endswith("-") or s.upper().endswith("DR")
    s = re.sub(r"[^0-9.\-]", "", s)
    if s in ("", "-", "."):
        return 0
    val = round(float(s) * 100)
    return -abs(val) if neg else val


def normalize_bank(raw: pd.DataFrame) -> pd.DataFrame:
    c = {k: _col(raw, v) for k, v in BANK_COLS.items()}
    if not c["date"] or not c["description"] or not (c["amount"] or c["credit"] or c["debit"]):
        raise ValueError(f"Bank file needs date, description and amount (or credit/debit) columns. Found: {list(raw.columns)}")
    out = pd.DataFrame()
    out["id"] = raw[c["id"]].astype(str) if c["id"] else [f"B{i + 1:03d}" for i in range(len(raw))]
    out["date"] = pd.to_datetime(raw[c["date"]], dayfirst=False, errors="coerce")
    out["description"] = raw[c["description"]].astype(str).str.strip()
    out["reference"] = raw[c["reference"]].astype(str) if c["reference"] else ""
    if c["amount"]:
        out["amount_cents"] = raw[c["amount"]].map(to_cents)
    else:
        cr = raw[c["credit"]].map(to_cents) if c["credit"] else 0
        dr = raw[c["debit"]].map(lambda x: abs(to_cents(x))) if c["debit"] else 0
        out["amount_cents"] = cr - dr
    out["text"] = (out["description"] + " " + out["reference"]).str.upper()
    out = out[out["amount_cents"] != 0].dropna(subset=["date"])
    return out.set_index("id", drop=False)


def normalize_ledger(raw: pd.DataFrame) -> pd.DataFrame:
    c = {k: _col(raw, v) for k, v in LEDGER_COLS.items()}
    if not c["date"] or not c["party"] or not c["amount"]:
        raise ValueError(f"Ledger file needs date, party and amount columns. Found: {list(raw.columns)}")
    out = pd.DataFrame()
    out["id"] = raw[c["id"]].astype(str) if c["id"] else [f"L{i + 1:03d}" for i in range(len(raw))]
    out["date"] = pd.to_datetime(raw[c["date"]], errors="coerce")
    out["party"] = raw[c["party"]].astype(str).str.strip()
    out["doc_no"] = raw[c["doc_no"]].astype(str).str.strip() if c["doc_no"] else ""
    out["description"] = raw[c["description"]].astype(str) if c["description"] else ""
    amt = raw[c["amount"]].map(to_cents)
    if c["type"]:  # bills / payables are money out
        is_out = raw[c["type"]].str.lower().str.contains("bill|payable|expense|vendor", na=False)
        amt = amt.where(~is_out, -amt.abs())
    out["amount_cents"] = amt
    out["doc_key"] = out["doc_no"].map(norm_key)
    out = out[out["amount_cents"] != 0].dropna(subset=["date"])
    return out.set_index("id", drop=False)


def fmt(cents: int) -> str:
    return f"{cents / 100:,.2f}"
