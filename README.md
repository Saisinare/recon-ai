# Recon AI

Bank-to-ledger reconciliation where **code does all the math, the LLM only reads messy text and
judges unclear cases, and every correction you make becomes a reusable rule.**

## How it works

Each layer only sees what the earlier layers left open.

| Layer | What it does | AI? |
|---|---|---|
| 0. Ingest | CSV/Excel to one schema, amounts as integer paise, duplicate lines set aside | no |
| 1. Rules | invoice/bill numbers in the bank text, your learned rules, unique amounts | no |
| 2. Extract | LLM turns `UPI/AMZN MKTP/...` into payee, invoice refs, kind (cached per description) | yes |
| 3. Fuzzy names | same amount, different spelling (`AMZN` = Amazon, `TCS`, truncation) | optional local embeddings |
| 4. Split solver | which open items add up exactly to one deposit; near-sums for fees/TDS | no |
| 5. Judge | LLM picks between the remaining candidates, gives confidence and a reason | yes |

- Anything below the auto-match threshold, and any match with a difference (fee, TDS), goes to **Needs review**.
- **Approve and learn a rule** turns a correction into a pattern, party, date window and tolerance rule.
  Activate it and it runs in layer 1 next time, so later months need fewer LLM calls and fewer reviews.
- Every match, approval, rejection and rule change is written to the audit log (`recon.db`).
- With provider `none`, everything still runs on regex and scoring heuristics.

## Run it

```powershell
pip install -r requirements.txt
python data\make_sample.py        # made-up test data with the tricky cases
python run.py                     # CLI run, scored against data\sample\truth.csv

cd web; npm install; npm run build; cd ..
python -m uvicorn api:app --port 8000   # API + React review screen at http://localhost:8000
```

For frontend work, run `npm run dev` in `web/` (port 5173, proxies `/api` to port 8000) next to the uvicorn server.

Sample results (30 bank lines, 35 ledger items): 27/27 matches found, 0 wrong, 24 auto-matched.
With Groq (`openai/gpt-oss-120b`) that took 4 LLM calls, and the judge explains fee and TDS differences.

## LLM providers (free options)

| Provider | Setup | Notes |
|---|---|---|
| `none` | nothing | offline heuristics |
| `ollama` | install Ollama, `ollama pull qwen2.5:7b` | runs on your PC; use this for real financial data |
| `groq` | `GROQ_API_KEY` in `.env` | fast; default model `openai/gpt-oss-120b`; free tier is rate-limited per model |
| `gemini` | `GEMINI_API_KEY` in `.env` | free tier may use prompts for training |
| `openrouter` | `OPENROUTER_API_KEY` in `.env` | `:free` models, about 50 requests a day |

Copy `.env.example` to `.env`. Free cloud tiers can train on your prompts, so send them sample or
anonymised data only.

## Your own files

The bank file needs date, description and either amount or credit/debit columns. The ledger needs
date, party and amount, plus optional doc_no and type (rows typed bill or payable count as money out).
Common column names (narration, particulars, withdrawal, customer, vendor, invoice no...) are
recognised automatically.

## Layout

```
api.py            FastAPI: runs the pipeline, review actions, rules, audit, export
web/              React (Vite) review screen
run.py            CLI + scoring
core/ingest.py    parsing and normalising
core/rules.py     layer 1 + learned rules
core/extract.py   layer 2
core/fuzzy.py     layer 3
core/solver.py    layer 4
core/judge.py     layer 5
core/learner.py   corrections -> rules
core/summary.py   month-end note
core/store.py     SQLite: rules, audit, LLM cache
llm/gateway.py    one client for Ollama / Groq / Gemini / OpenRouter
```
