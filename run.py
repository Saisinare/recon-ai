"""Command-line run with scoring against the answer key.

  python run.py                         # sample data, offline heuristics
  python run.py --provider groq         # same, with an LLM
  python run.py --bank my.csv --ledger gl.csv --no-truth
"""
import argparse
import csv
from pathlib import Path

from core import ingest, pipeline, summary
from core.model import Config
from core.store import Store
from llm.gateway import LLM, PROVIDERS

ROOT = Path(__file__).parent
SAMPLE = ROOT / "data" / "sample"


def score(result, truth_path):
    truth = {r["bank_id"]: r["ledger_ids"] for r in csv.DictReader(open(truth_path, encoding="utf-8"))}
    pred = {m.bank_ids[0]: m for m in result.live()}
    dups = {d[1] for d in result.ctx.duplicates if d[0] == "bank"}
    expected = {b: set(v.split(";")) for b, v in truth.items() if v and v != "DUP"}
    correct = {b for b, m in pred.items() if expected.get(b) == set(m.ledger_ids)}
    auto = [b for b, m in pred.items() if m.status == "auto"]
    wrong = [(b, pred[b].ledger_ids, sorted(expected.get(b, [])), pred[b].layer) for b in pred if b not in correct]
    missed = sorted(set(expected) - set(pred))
    print(f"\nScore vs answer key")
    print(f"  recall     {len(correct)}/{len(expected)} expected matches found")
    print(f"  precision  {len(correct)}/{len(pred)} proposed matches correct")
    print(f"  auto-match precision {sum(b in correct for b in auto)}/{len(auto)}")
    print(f"  duplicates found {len(dups & {b for b, v in truth.items() if v == 'DUP'})}"
          f"/{sum(v == 'DUP' for v in truth.values())}")
    for w in wrong:
        print(f"  WRONG  {w[0]} -> {w[1]} (expected {w[2]}) via {w[3]}")
    for b in missed:
        print(f"  MISSED {b} expected {sorted(expected[b])}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=None, choices=list(PROVIDERS))
    ap.add_argument("--model", default=None)
    ap.add_argument("--bank", default=SAMPLE / "bank.csv")
    ap.add_argument("--ledger", default=SAMPLE / "ledger.csv")
    ap.add_argument("--truth", default=SAMPLE / "truth.csv")
    ap.add_argument("--no-truth", action="store_true")
    ap.add_argument("--db", default=ROOT / "recon.db")
    ap.add_argument("--embeddings", action="store_true")
    a = ap.parse_args()

    store = Store(str(a.db))
    llm = LLM(a.provider, a.model, store)
    bank = ingest.normalize_bank(ingest.read_any(a.bank))
    ledger = ingest.normalize_ledger(ingest.read_any(a.ledger))
    res = pipeline.run(bank, ledger, Config(use_embeddings=a.embeddings), llm, store)

    print(f"LLM: {llm.status()} | calls {llm.calls}, cache hits {llm.cache_hits}, errors {len(llm.errors)}")
    for m in res.matches:
        print(f"{m.id} {m.status:9} {m.layer:22} {m.confidence:.2f}  {','.join(m.bank_ids)} -> "
              f"{','.join(m.ledger_ids):18} diff {m.difference_cents / 100:>9,.2f}  {m.reason[:90]}")
    print()
    print(summary.write(res, None))
    if not a.no_truth and Path(a.truth).exists():
        score(res, a.truth)


if __name__ == "__main__":
    main()
