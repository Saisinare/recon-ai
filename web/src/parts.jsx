import React from "react";
import { money } from "./api.js";

export function Logo() {
  return (
    <span className="logo">
      <span className="dots" aria-hidden="true"><i /><i /></span>
      Recon AI
    </span>
  );
}

export function Nav({ tabs, tab, setTab, ready, reviewCount, run, busy }) {
  return (
    <header className="nav">
      <Logo />
      <nav>
        {tabs.map((t) => (
          <button key={t.id} className={ready && tab === t.id ? "on" : ""} disabled={!ready} onClick={() => setTab(t.id)}>
            {t.label}
            {t.id === "review" && reviewCount > 0 && <span className="count">{reviewCount}</span>}
          </button>
        ))}
      </nav>
      <div className="nav-cta">
        {ready && <a className="btn ghost sm" href="/api/export.csv">Export CSV</a>}
        <button className="btn lime sm" onClick={run} disabled={busy}>{busy ? "Working…" : "Run reconciliation"}</button>
      </div>
    </header>
  );
}

export function Tag({ children }) {
  return <span className="tag-lime">{children}</span>;
}

export function SectionHead({ tag, title, sub }) {
  return (
    <div className="section-head">
      <Tag>{tag}</Tag>
      <h2>{title}</h2>
      {sub && <p>{sub}</p>}
    </div>
  );
}

export function Hero({ providers, settings, setSettings, files, setFiles, run, busy, data }) {
  const s = data.ready ? data.stats : null;
  return (
    <section className="hero">
      <div className="hero-copy">
        <div className="proof">
          <span className="stack" aria-hidden="true"><i>L1</i><i>L2</i><i>L3</i><i>L4</i><i>L5</i></span>
          <span>
            <b>5 matching layers</b>
            <small>Code does the math. The LLM judges the rest.</small>
          </span>
        </div>
        <h1>Reconcile your books without the guesswork.</h1>
        <p className="lead">
          Recon AI matches bank lines to ledger entries, finds split payments, explains fee and TDS differences,
          and turns every correction you make into a rule.
        </p>
        <div className="hero-cta">
          <button className="btn dark" onClick={run} disabled={busy}>{busy ? "Working…" : "Run reconciliation"}</button>
          <a className="btn ghost" href="https://github.com/Saisinare/recon-ai" target="_blank" rel="noreferrer">View on GitHub</a>
        </div>
        {s && (
          <div className="balance">
            <small>Bank lines matched</small>
            <strong>{s.bank_rows_matched_pct}%</strong>
            <Bars byLayer={s.by_layer} />
          </div>
        )}
      </div>
      <Settings {...{ providers, settings, setSettings, files, setFiles, run, busy }} />
    </section>
  );
}

function Bars({ byLayer }) {
  const order = ["L1 exact", "L1 learned rule", "L2 LLM extract", "L3 fuzzy name", "L4 split solver", "L5 LLM judge", "L5 judge (heuristic)", "manual"];
  const rows = order.filter((k) => byLayer[k]).map((k) => [k, byLayer[k]]);
  const max = Math.max(1, ...rows.map((r) => r[1]));
  return (
    <div className="bars" role="img" aria-label="Matches by layer">
      {rows.map(([k, v], i) => (
        <div key={k} className="bar-col" title={`${k}: ${v}`}>
          <span className={`bar ${i === 0 ? "hi" : ""}`} style={{ height: `${Math.max(8, (v / max) * 100)}%` }} />
          <em>{k.split(" ")[0]}</em>
        </div>
      ))}
    </div>
  );
}

function Settings({ providers, settings, setSettings, files, setFiles, run, busy }) {
  const set = (k) => (e) => setSettings({ ...settings, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const p = providers.find((x) => x.name === settings.provider);
  const cloud = ["groq", "gemini", "openrouter"].includes(settings.provider);
  return (
    <div className="settings card">
      <div className="settings-head">
        <b>Run a reconciliation</b>
        <small>Sample data or your own CSV / Excel files</small>
      </div>
      <div className="seg">
        <button className={settings.useSample ? "on" : ""} onClick={() => setSettings({ ...settings, useSample: true })}>Sample data</button>
        <button className={!settings.useSample ? "on" : ""} onClick={() => setSettings({ ...settings, useSample: false })}>Upload files</button>
      </div>
      {!settings.useSample && (
        <div className="row2">
          <label>Bank statement<input type="file" accept=".csv,.xlsx,.xls" onChange={(e) => setFiles({ ...files, bank: e.target.files[0] })} /></label>
          <label>Ledger / open items<input type="file" accept=".csv,.xlsx,.xls" onChange={(e) => setFiles({ ...files, ledger: e.target.files[0] })} /></label>
        </div>
      )}
      <div className="row2">
        <label>
          LLM provider
          <select value={settings.provider} onChange={set("provider")}>
            {(providers.length ? providers : [{ name: "none" }]).map((x) => <option key={x.name} value={x.name}>{x.name}</option>)}
          </select>
        </label>
        <label>
          Model
          <input value={settings.model} onChange={set("model")} placeholder={p?.default_model || "default"} />
        </label>
      </div>
      {p && <div className={`status ${p.available ? "ok" : "warn"}`}><span className="dot" />{p.status}</div>}
      {cloud && <p className="hint">Free tiers may use prompts for training. Send sample or anonymised data only.</p>}
      <label>
        <span className="between">Auto-match threshold <b>{Number(settings.threshold).toFixed(2)}</b></span>
        <input type="range" min="0.5" max="0.99" step="0.01" value={settings.threshold} onChange={set("threshold")} />
      </label>
      <label className="check">
        <input type="checkbox" checked={settings.embeddings} onChange={set("embeddings")} />
        Local embeddings for names
      </label>
      <button className="btn lime wide" onClick={run} disabled={busy}>{busy ? "Working…" : "Run reconciliation"}</button>
    </div>
  );
}

export function Overview({ s, llm }) {
  const items = [
    ["Auto-matched", s.auto, s.approved ? `+${s.approved} approved by you` : "no review needed"],
    ["Needs review", s.needs_review, s.needs_review ? "waiting for you" : "all clear"],
    ["Open items", `${s.unmatched_bank} / ${s.unmatched_ledger}`, "bank lines / ledger items"],
    ["Duplicates", s.duplicates, "set aside before matching"],
    ["Fees & TDS", money(s.difference_total), "differences on matches"],
    ["LLM answers", llm.calls + llm.cache_hits, `${llm.cache_hits} from cache · ${llm.status}`],
  ];
  return (
    <section className="block" id="overview">
      <SectionHead tag="Overview" title="Everything reconciled. All in one place." />
      <div className="features">
        {items.map(([k, v, sub]) => (
          <div className="feature card" key={k}>
            <b>{k}</b>
            <strong>{v}</strong>
            <small>{sub}</small>
          </div>
        ))}
      </div>
    </section>
  );
}

export function Footer() {
  return (
    <footer className="foot">
      <Logo />
      <small>Exact math in code · LLM for messy text and judgement · every decision in the audit log</small>
    </footer>
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
      <div className="side-box">
        <div className="side">Bank</div>
        {bank.map((b) => (
          <div className="line" key={b.id}><Line date={b.date} desc={b.description} amount={b.amount} /></div>
        ))}
      </div>
      <div className="side-box">
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
