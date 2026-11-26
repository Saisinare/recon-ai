"""HTTP API for the React review screen.

  python -m uvicorn api:app --port 8000      (serves the built React app at / too)
"""
import threading
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import ingest, learner, pipeline, summary
from core.model import Config, Match
from core.store import Store
from llm.gateway import LLM, PROVIDERS, load_env

ROOT = Path(__file__).parent
SAMPLE = ROOT / "data" / "sample"
DIST = ROOT / "web" / "dist"

load_env()
store = Store(str(ROOT / "recon.db"))
lock = threading.Lock()
STATE = {"result": None, "llm": None}

app = FastAPI(title="Recon AI")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


# ---------- helpers ----------
def _result():
    r = STATE["result"]
    if r is None:
        raise HTTPException(409, "Run a reconciliation first.")
    return r


def _bank_row(ctx, i):
    b = ctx.bank.loc[i]
    return {"id": i, "date": str(b.date.date()), "description": b.description, "amount": b.amount_cents / 100}


def _ledger_row(ctx, i):
    l = ctx.ledger.loc[i]
    return {"id": i, "date": str(l.date.date()), "party": l.party, "doc_no": l.doc_no, "amount": l.amount_cents / 100}


def _match(ctx, m: Match):
    return {"id": m.id, "status": m.status, "layer": m.layer, "confidence": m.confidence,
            "difference": m.difference_cents / 100, "reason": m.reason,
            "bank": [_bank_row(ctx, i) for i in m.bank_ids],
            "ledger": [_ledger_row(ctx, i) for i in m.ledger_ids]}


def state():
    r = STATE["result"]
    if r is None:
        return {"ready": False}
    ctx = r.ctx
    llm = STATE["llm"]
    return {
        "ready": True,
        "llm": {"status": llm.status(), "calls": llm.calls, "cache_hits": llm.cache_hits, "errors": llm.errors[-3:]},
        "stats": r.stats(),
        "matches": [_match(ctx, m) for m in r.matches],
        "unmatched_bank": [_bank_row(ctx, i) for i in r.unmatched_bank().index],
        "unmatched_ledger": [_ledger_row(ctx, i) for i in r.unmatched_ledger().index],
        "duplicates": [{"kind": k, "id": d, "original": o} for k, d, o in ctx.duplicates],
    }


def _find(mid):
    r = _result()
    for m in r.matches:
        if m.id == mid:
            return r, m
    raise HTTPException(404, f"No match {mid}")


def _learn(r, m):
    ctx = r.ctx
    rule = learner.propose(ctx.bank.loc[m.bank_ids[0]], [ctx.ledger.loc[i] for i in m.ledger_ids],
                           STATE["llm"], ctx.bank["description"].tolist())
    rid = store.add_rule(rule)
    store.log("rule:proposed", m, actor="user", run_id=ctx.run_id,
              reason=f"rule #{rid} /{rule['pattern']}/ -> {rule['party']}")
    return {"id": rid, **rule}


# ---------- endpoints ----------
@app.get("/api/providers")
def providers():
    out = []
    for p in PROVIDERS:
        llm = LLM(p)
        out.append({"name": p, "available": llm.available or p == "none", "status": llm.status(),
                    "default_model": llm.model})
    return out


@app.get("/api/state")
def get_state():
    return state()


@app.post("/api/run")
async def run(provider: str = Form("none"), model: str = Form(""), threshold: float = Form(0.9),
              embeddings: bool = Form(False), use_sample: bool = Form(True),
              bank: UploadFile | None = File(None), ledger: UploadFile | None = File(None)):
    try:
        if use_sample:
            braw, lraw = ingest.read_any(SAMPLE / "bank.csv"), ingest.read_any(SAMPLE / "ledger.csv")
        else:
            if not (bank and ledger):
                raise HTTPException(400, "Upload both a bank file and a ledger file.")
            braw = ingest.read_any(await bank.read(), bank.filename)
            lraw = ingest.read_any(await ledger.read(), ledger.filename)
        b, l = ingest.normalize_bank(braw), ingest.normalize_ledger(lraw)
        llm = LLM(provider, model or None, store)
    except ValueError as e:
        raise HTTPException(400, str(e))
    with lock:
        STATE["result"] = pipeline.run(b, l, Config(auto_threshold=threshold, use_embeddings=embeddings), llm, store)
        STATE["llm"] = llm
    return state()


class Decision(BaseModel):
    learn: bool = False


@app.post("/api/matches/{mid}/approve")
def approve(mid: str, d: Decision):
    with lock:
        r, m = _find(mid)
        m.status = "approved"
        store.log("match:approved", m, actor="user", run_id=r.ctx.run_id)
        rule = _learn(r, m) if d.learn else None
    return {"rule": rule, "state": state()}


@app.post("/api/matches/{mid}/reject")
def reject(mid: str):
    with lock:
        r, m = _find(mid)
        m.status = "rejected"
        store.log("match:rejected", m, actor="user", run_id=r.ctx.run_id)
    return {"state": state()}


class Manual(BaseModel):
    bank_id: str
    ledger_ids: list[str]
    learn: bool = True


@app.post("/api/matches/manual")
def manual(body: Manual):
    with lock:
        r = _result()
        ub, ul = r.unmatched_bank(), r.unmatched_ledger()
        if body.bank_id not in ub.index or not body.ledger_ids or any(i not in ul.index for i in body.ledger_ids):
            raise HTTPException(400, "Pick one open bank line and one or more open ledger items.")
        total = int(ul.loc[body.ledger_ids, "amount_cents"].sum())
        diff = total - int(ub.at[body.bank_id, "amount_cents"])
        m = Match([body.bank_id], body.ledger_ids, "manual", 1.0, "Matched by hand", "approved", diff,
                  f"M{len(r.matches) + 1:03d}")
        r.matches.append(m)
        store.log("match:manual", m, actor="user", run_id=r.ctx.run_id)
        rule = _learn(r, m) if body.learn else None
    return {"rule": rule, "state": state()}


@app.get("/api/rules")
def rules():
    return store.rules()


class RuleStatus(BaseModel):
    status: str


@app.post("/api/rules/{rid}/status")
def rule_status(rid: int, body: RuleStatus):
    if body.status not in ("active", "disabled", "pending"):
        raise HTTPException(400, "status must be active, disabled or pending")
    store.set_rule_status(rid, body.status)
    store.log(f"rule:{body.status}", actor="user", reason=f"rule #{rid}")
    return store.rules()


@app.get("/api/audit")
def audit(limit: int = 300):
    return store.audit_df(limit).fillna("").to_dict(orient="records")


@app.post("/api/summary")
def write_summary():
    return {"text": summary.write(_result(), STATE["llm"])}


@app.get("/api/export.csv", response_class=PlainTextResponse)
def export():
    return PlainTextResponse(_result().matches_df().to_csv(index=False), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=matches.csv"})


# ---------- built React app ----------
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(DIST / "index.html")
