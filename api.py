"""HTTP API for the React review screen.

  python -m uvicorn api:app --port 8000      (serves the built React app at / too)

Each browser gets its own session (cookie), so visitors never see each other's runs.
Set RECON_DEMO=1 for a public deployment:
  - every visitor gets a private, in-memory rule store and audit log
  - cloud-LLM runs are rate-limited per visitor IP (RECON_DEMO_LLM_RUNS per hour)
  - uploaded files are size-limited and always processed offline, never sent to an LLM
"""
import os
import secrets
import threading
import time
from collections import OrderedDict, defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
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
DEMO = os.getenv("RECON_DEMO", "0").lower() in ("1", "true", "yes")
DEMO_LLM_RUNS = int(os.getenv("RECON_DEMO_LLM_RUNS", "5"))
MAX_UPLOAD = int(os.getenv("RECON_MAX_UPLOAD_KB", "1024")) * 1024
MAX_ROWS = int(os.getenv("RECON_MAX_ROWS", "3000"))
MAX_SESSIONS, SESSION_TTL = 300, 2 * 3600
COOKIE = "recon_sid"

shared = Store(str(ROOT / "recon.db"))          # rules + audit in local mode; LLM cache always
app = FastAPI(title="Recon AI")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ---------- sessions ----------
class Session:
    def __init__(self):
        self.result = None
        self.llm = None
        self.lock = threading.Lock()
        self.store = Store(":memory:", cache=shared) if DEMO else shared
        self.seen = time.time()


SESSIONS: "OrderedDict[str, Session]" = OrderedDict()
SESSIONS_LOCK = threading.Lock()
LLM_RUNS = defaultdict(deque)   # ip -> timestamps of cloud-LLM runs


def session(request: Request, response: Response) -> Session:
    sid = request.cookies.get(COOKIE)
    now = time.time()
    with SESSIONS_LOCK:
        for k in [k for k, s in SESSIONS.items() if now - s.seen > SESSION_TTL]:
            SESSIONS.pop(k)
        if not sid or sid not in SESSIONS:
            sid = sid if sid and len(sid) == 32 else secrets.token_hex(16)
            SESSIONS[sid] = Session()
            while len(SESSIONS) > MAX_SESSIONS:
                SESSIONS.popitem(last=False)
        s = SESSIONS[sid]
        SESSIONS.move_to_end(sid)
        s.seen = now
    response.set_cookie(COOKIE, sid, max_age=SESSION_TTL, httponly=True, samesite="lax")
    return s


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


def llm_allowed(ip: str) -> tuple[bool, int]:
    """Sliding one-hour window of cloud-LLM runs per IP (demo mode only)."""
    q, now = LLM_RUNS[ip], time.time()
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= DEMO_LLM_RUNS:
        return False, 0
    q.append(now)
    return True, DEMO_LLM_RUNS - len(q)


# ---------- serialisation ----------
def _result(s: Session):
    if s.result is None:
        raise HTTPException(409, "Run a reconciliation first.")
    return s.result


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


def state(s: Session, notice: str = ""):
    r = s.result
    if r is None:
        return {"ready": False}
    ctx, llm = r.ctx, s.llm
    return {
        "ready": True, "notice": notice,
        "llm": {"status": llm.status(), "calls": llm.calls, "cache_hits": llm.cache_hits, "errors": llm.errors[-3:]},
        "stats": r.stats(),
        "matches": [_match(ctx, m) for m in r.matches],
        "unmatched_bank": [_bank_row(ctx, i) for i in r.unmatched_bank().index],
        "unmatched_ledger": [_ledger_row(ctx, i) for i in r.unmatched_ledger().index],
        "duplicates": [{"kind": k, "id": d, "original": o} for k, d, o in ctx.duplicates],
    }


def _find(s: Session, mid):
    r = _result(s)
    for m in r.matches:
        if m.id == mid:
            return r, m
    raise HTTPException(404, f"No match {mid}")


def _learn(s: Session, r, m):
    ctx = r.ctx
    rule = learner.propose(ctx.bank.loc[m.bank_ids[0]], [ctx.ledger.loc[i] for i in m.ledger_ids],
                           s.llm, ctx.bank["description"].tolist())
    rid = s.store.add_rule(rule)
    s.store.log("rule:proposed", m, actor="user", run_id=ctx.run_id,
                reason=f"rule #{rid} /{rule['pattern']}/ -> {rule['party']}")
    return {"id": rid, **rule}


async def _read_upload(f: UploadFile, what: str):
    data = await f.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"The {what} file is larger than {MAX_UPLOAD // 1024} KB.")
    df = ingest.read_any(data, f.filename)
    if len(df) > MAX_ROWS:
        raise HTTPException(413, f"The {what} file has more than {MAX_ROWS} rows.")
    return df


# ---------- endpoints ----------
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def config():
    return {"demo": DEMO, "llm_runs_per_hour": DEMO_LLM_RUNS, "max_upload_kb": MAX_UPLOAD // 1024, "max_rows": MAX_ROWS}


@app.get("/api/providers")
def providers():
    out = []
    for p in PROVIDERS:
        llm = LLM(p)
        if DEMO and p != "none" and (p == "ollama" or not llm.available):
            continue   # hide providers the deployment has no key for (and local Ollama)
        out.append({"name": p, "available": llm.available or p == "none", "status": llm.status(),
                    "default_model": llm.model})
    return out


@app.get("/api/state")
def get_state(request: Request, response: Response):
    return state(session(request, response))


@app.post("/api/run")
async def run(request: Request, response: Response,
              provider: str = Form("none"), model: str = Form(""), threshold: float = Form(0.9),
              embeddings: bool = Form(False), use_sample: bool = Form(True),
              bank: UploadFile | None = File(None), ledger: UploadFile | None = File(None)):
    s = session(request, response)
    notice = ""
    if DEMO:
        embeddings = False      # the model download is too heavy for a free instance
        model = ""              # stick to the deployment's default model
    try:
        if use_sample:
            braw, lraw = ingest.read_any(SAMPLE / "bank.csv"), ingest.read_any(SAMPLE / "ledger.csv")
        else:
            if not (bank and ledger):
                raise HTTPException(400, "Upload both a bank file and a ledger file.")
            braw, lraw = await _read_upload(bank, "bank"), await _read_upload(ledger, "ledger")
            if DEMO and provider != "none":
                provider, notice = "none", "Uploaded files are matched offline in this demo; they are never sent to an LLM."
        b, l = ingest.normalize_bank(braw), ingest.normalize_ledger(lraw)
        if DEMO and provider != "none":
            ok, left = llm_allowed(client_ip(request))
            if not ok:
                provider = "none"
                notice = f"You've used this demo's {DEMO_LLM_RUNS} LLM runs for the hour, so this run used the offline heuristics."
        llm = LLM(provider, model or None, s.store)
    except ValueError as e:
        raise HTTPException(400, str(e))
    with s.lock:
        s.result = pipeline.run(b, l, Config(auto_threshold=threshold, use_embeddings=embeddings), llm, s.store)
        s.llm = llm
    return state(s, notice)


class Decision(BaseModel):
    learn: bool = False


@app.post("/api/matches/{mid}/approve")
def approve(mid: str, d: Decision, request: Request, response: Response):
    s = session(request, response)
    with s.lock:
        r, m = _find(s, mid)
        m.status = "approved"
        s.store.log("match:approved", m, actor="user", run_id=r.ctx.run_id)
        rule = _learn(s, r, m) if d.learn else None
    return {"rule": rule, "state": state(s)}


@app.post("/api/matches/{mid}/reject")
def reject(mid: str, request: Request, response: Response):
    s = session(request, response)
    with s.lock:
        r, m = _find(s, mid)
        m.status = "rejected"
        s.store.log("match:rejected", m, actor="user", run_id=r.ctx.run_id)
    return {"state": state(s)}


class Manual(BaseModel):
    bank_id: str
    ledger_ids: list[str]
    learn: bool = True


@app.post("/api/matches/manual")
def manual(body: Manual, request: Request, response: Response):
    s = session(request, response)
    with s.lock:
        r = _result(s)
        ub, ul = r.unmatched_bank(), r.unmatched_ledger()
        if body.bank_id not in ub.index or not body.ledger_ids or any(i not in ul.index for i in body.ledger_ids):
            raise HTTPException(400, "Pick one open bank line and one or more open ledger items.")
        total = int(ul.loc[body.ledger_ids, "amount_cents"].sum())
        diff = total - int(ub.at[body.bank_id, "amount_cents"])
        m = Match([body.bank_id], body.ledger_ids, "manual", 1.0, "Matched by hand", "approved", diff,
                  f"M{len(r.matches) + 1:03d}")
        r.matches.append(m)
        s.store.log("match:manual", m, actor="user", run_id=r.ctx.run_id)
        rule = _learn(s, r, m) if body.learn else None
    return {"rule": rule, "state": state(s)}


@app.get("/api/rules")
def rules(request: Request, response: Response):
    return session(request, response).store.rules()


class RuleStatus(BaseModel):
    status: str


@app.post("/api/rules/{rid}/status")
def rule_status(rid: int, body: RuleStatus, request: Request, response: Response):
    if body.status not in ("active", "disabled", "pending"):
        raise HTTPException(400, "status must be active, disabled or pending")
    s = session(request, response)
    s.store.set_rule_status(rid, body.status)
    s.store.log(f"rule:{body.status}", actor="user", reason=f"rule #{rid}")
    return s.store.rules()


@app.get("/api/audit")
def audit(request: Request, response: Response, limit: int = 300):
    return session(request, response).store.audit_df(min(limit, 1000)).fillna("").to_dict(orient="records")


@app.post("/api/summary")
def write_summary(request: Request, response: Response):
    s = session(request, response)
    return {"text": summary.write(_result(s), s.llm)}


@app.get("/api/export.csv", response_class=PlainTextResponse)
def export(request: Request, response: Response):
    s = session(request, response)
    return PlainTextResponse(_result(s).matches_df().to_csv(index=False), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=matches.csv"})


# ---------- built React app ----------
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
