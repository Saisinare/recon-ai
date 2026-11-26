import React from "react";
import { money } from "./api.js";

export function Sidebar({ providers, settings, setSettings, files, setFiles, run, busy }) {
  const set = (k) => (e) => setSettings({ ...settings, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const p = providers.find((x) => x.name === settings.provider);
  const cloud = ["groq", "gemini", "openrouter"].includes(settings.provider);
  return (
    <aside>
      <h2>Settings</h2>
      <label>
        LLM provider
        <select value={settings.provider} onChange={set("provider")}>
          {(providers.length ? providers : [{ name: "none" }]).map((x) => (
            <option key={x.name} value={x.name}>
              {x.name}
            </option>
          ))}
        </select>
      </label>
      {p && <div className={`status ${p.available ? "ok" : "warn"}`}>{p.status}</div>}
      {cloud && <p className="hint">Free tiers may use prompts for training. Send sample or anonymised data only.</p>}
      <label>
        Model
        <input value={settings.model} onChange={set("model")} placeholder={p?.default_model || "default"} />
      </label>
      <label>
        Auto-match threshold <b>{Number(settings.threshold).toFixed(2)}</b>
        <input type="range" min="0.5" max="0.99" step="0.01" value={settings.threshold} onChange={set("threshold")} />
      </label>
      <label className="check">
        <input type="checkbox" checked={settings.embeddings} onChange={set("embeddings")} />
        Local embeddings for names
      </label>

      <h2>Data</h2>
      <div className="seg">
        <button className={settings.useSample ? "on" : ""} onClick={() => setSettings({ ...settings, useSample: true })}>
          Sample
        </button>
        <button className={!settings.useSample ? "on" : ""} onClick={() => setSettings({ ...settings, useSample: false })}>
          Upload
        </button>
      </div>
      {!settings.useSample && (
        <>
          <label>
            Bank statement (CSV / Excel)
            <input type="file" accept=".csv,.xlsx,.xls" onChange={(e) => setFiles({ ...files, bank: e.target.files[0] })} />
          </label>
          <label>
            Ledger / open items
            <input type="file" accept=".csv,.xlsx,.xls" onChange={(e) => setFiles({ ...files, ledger: e.target.files[0] })} />
          </label>
        </>
      )}
      <button className="btn primary wide" onClick={run} disabled={busy}>
        {busy ? "Working…" : "Run reconciliation"}
      </button>
    </aside>
  );
}

export function Empty() {
  return (
    <div className="empty">
      <p>
        Pick a data source and press <b>Run reconciliation</b>.
      </p>
      <p className="muted">
        The sample data has split payments, fee and TDS short-payments, abbreviated names, a duplicate line and items that should stay open.
      </p>
    </div>
  );
}

export function Kpis({ s, llm }) {
  const items = [
    ["Bank lines matched", `${s.bank_rows_matched_pct}%`, `${s.bank_rows} lines`],
    ["Auto-matched", s.auto, s.approved ? `+${s.approved} approved` : "no review needed"],
    ["Needs review", s.needs_review, s.needs_review ? "waiting for you" : "all clear"],
    ["Open items", `${s.unmatched_bank} / ${s.unmatched_ledger}`, "bank / ledger"],
    ["Duplicates", s.duplicates, "set aside"],
    ["LLM calls", s.llm_calls, llm.status],
  ];
  return (
    <div className="kpis">
      {items.map(([k, v, sub]) => (
        <div className="kpi" key={k}>
          <div className="k">{k}</div>
          <div className="v">{v}</div>
          <div className="sub">{sub}</div>
        </div>
      ))}
    </div>
  );
}

export function Line({ date, desc, amount }) {
  return (
    <>
      <span className="date">{date}</span>
      <span className="desc">{desc}</span>
      <span className={`amt ${amount < 0 ? "neg" : ""}`}>{money(amount)}</span>
    </>
  );
}

export function Rows({ bank, ledger }) {
  return (
    <div className="pair">
      <div>
        <div className="side">Bank</div>
        {bank.map((b) => (
          <div className="line" key={b.id}>
            <Line date={b.date} desc={b.description} amount={b.amount} />
          </div>
        ))}
      </div>
      <div>
        <div className="side">Ledger</div>
        {ledger.map((l) => (
          <div className="line" key={l.id}>
            <Line date={l.date} desc={<>{l.party} <span className="muted">{l.doc_no}</span></>} amount={l.amount} />
          </div>
        ))}
      </div>
    </div>
  );
}

export function Conf({ v }) {
  const tone = v >= 0.9 ? "hi" : v >= 0.75 ? "mid" : "lo";
  return <span className={`conf ${tone}`} title="Confidence">{v.toFixed(2)}</span>;
}
