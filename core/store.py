"""SQLite store: learned rules, audit log and LLM cache."""
import json
import sqlite3
import threading
from datetime import datetime

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS rules(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, pattern TEXT, party TEXT,
  date_window INTEGER DEFAULT 45, tolerance_pct REAL DEFAULT 0, status TEXT DEFAULT 'pending',
  example TEXT, hits INTEGER DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, run_id TEXT, event TEXT, actor TEXT,
  bank_ids TEXT, ledger_ids TEXT, layer TEXT, confidence REAL, reason TEXT);
CREATE TABLE IF NOT EXISTS llm_cache(key TEXT PRIMARY KEY, value TEXT);
"""


class Store:
    def __init__(self, path="recon.db"):
        self.path = path
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def _x(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    # cache
    def cache_get(self, key):
        r = self._x("SELECT value FROM llm_cache WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else None

    def cache_put(self, key, value):
        self._x("INSERT OR REPLACE INTO llm_cache VALUES(?,?)", (key, json.dumps(value)))

    # rules
    def add_rule(self, rule: dict, status="pending") -> int:
        cur = self._x(
            "INSERT INTO rules(name,pattern,party,date_window,tolerance_pct,status,example,created) VALUES(?,?,?,?,?,?,?,?)",
            (rule["name"], rule["pattern"], rule["party"], rule.get("date_window", 45),
             rule.get("tolerance_pct", 0), status, rule.get("example", ""), _now()))
        return cur.lastrowid

    def rules(self, status=None) -> list[dict]:
        sql, args = "SELECT * FROM rules", ()
        if status:
            sql, args = sql + " WHERE status=?", (status,)
        return [dict(r) for r in self._x(sql + " ORDER BY id", args).fetchall()]

    def set_rule_status(self, rule_id, status):
        self._x("UPDATE rules SET status=? WHERE id=?", (status, rule_id))

    def bump_rule(self, rule_id):
        self._x("UPDATE rules SET hits=hits+1 WHERE id=?", (rule_id,))

    # audit
    def log(self, event, match=None, actor="system", run_id="", reason=""):
        m = match
        self._x(
            "INSERT INTO audit(ts,run_id,event,actor,bank_ids,ledger_ids,layer,confidence,reason) VALUES(?,?,?,?,?,?,?,?,?)",
            (_now(), run_id, event, actor,
             ";".join(m.bank_ids) if m else "", ";".join(m.ledger_ids) if m else "",
             m.layer if m else "", m.confidence if m else None, reason or (m.reason if m else "")))

    def audit_df(self, limit=1000) -> pd.DataFrame:
        return pd.read_sql_query(f"SELECT * FROM audit ORDER BY id DESC LIMIT {int(limit)}", self.db)


def _now():
    return datetime.now().isoformat(timespec="seconds")
