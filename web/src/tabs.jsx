import React, { useEffect, useState } from "react";
import { api, money } from "./api.js";
import { Conf, Line, Rows } from "./parts.jsx";

export function Review({ data, guard, after }) {
  const pending = data.matches.filter((m) => m.status === "suggested");
  if (!pending.length) return <p className="ok-msg">Nothing waiting for review.</p>;
  return pending.map((m) => (
    <article className="card" key={m.id}>
      <div className="card-head">
        <b>{m.id}</b>
        <span className="tag">{m.layer}</span>
        <Conf v={m.confidence} />
        {m.difference !== 0 && <span className="diff">difference {money(m.difference)}</span>}
      </div>
      <Rows bank={m.bank} ledger={m.ledger} />
      <p className="reason">{m.reason}</p>
      <div className="actions">
        <button className="btn primary" onClick={() => guard(async () => after(await api.approve(m.id, true)))}>
          Approve and learn a rule
        </button>
        <button className="btn" onClick={() => guard(async () => after(await api.approve(m.id, false)))}>
          Approve
        </button>
        <button className="btn danger" onClick={() => guard(async () => after(await api.reject(m.id)))}>
          Reject
        </button>
      </div>
    </article>
  ));
}

export function Matched({ data }) {
  const rows = data.matches.filter((m) => ["auto", "approved"].includes(m.status));
  return (
    <div className="scroll">
      <table>
        <thead>
          <tr>
            <th>Match</th><th>Status</th><th>Layer</th><th>Conf.</th><th>Bank</th><th>Ledger</th>
            <th className="num">Difference</th><th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m.id}>
              <td>{m.id}</td>
              <td><span className={`st ${m.status}`}>{m.status}</span></td>
              <td className="nowrap">{m.layer}</td>
              <td><Conf v={m.confidence} /></td>
              <td title={m.bank.map((b) => b.description).join("\n")}>{m.bank.map((b) => `${b.id} · ${money(b.amount)}`).join(", ")}</td>
              <td>{m.ledger.map((l) => `${l.party} ${l.doc_no}`).join(", ")}</td>
              <td className="num">{m.difference ? money(m.difference) : "—"}</td>
              <td className="reason-cell">{m.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Unmatched({ data, guard, after }) {
  const [bankId, setBankId] = useState("");
  const [picked, setPicked] = useState([]);
  const [learn, setLearn] = useState(true);
  const bank = data.unmatched_bank.find((b) => b.id === bankId);
  const options = data.unmatched_ledger.filter((l) => !bank || l.amount > 0 === bank.amount > 0);
  const total = options.filter((l) => picked.includes(l.id)).reduce((a, l) => a + l.amount, 0);
  const toggle = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const save = () =>
    guard(async () => {
      after(await api.manual(bankId, picked, learn));
      setBankId("");
      setPicked([]);
    });

  return (
    <>
      <p className="muted">Pick one bank line, tick the ledger items it pays, then save. The difference is calculated for you.</p>
      <div className="two">
        <div>
          <h3>Bank lines ({data.unmatched_bank.length})</h3>
          {data.unmatched_bank.map((b) => (
            <label key={b.id} className={`pick ${bankId === b.id ? "on" : ""}`}>
              <input type="radio" name="bank" checked={bankId === b.id} onChange={() => { setBankId(b.id); setPicked([]); }} />
              <Line date={b.date} desc={b.description} amount={b.amount} />
            </label>
          ))}
        </div>
        <div>
          <h3>Ledger items ({data.unmatched_ledger.length})</h3>
          {!bank && <p className="muted small">Choose a bank line first.</p>}
          {options.map((l) => (
            <label key={l.id} className={`pick ${picked.includes(l.id) ? "on" : ""} ${!bank ? "off" : ""}`}>
              <input type="checkbox" disabled={!bank} checked={picked.includes(l.id)} onChange={() => toggle(l.id)} />
              <Line date={l.date} desc={<>{l.party} <span className="muted">{l.doc_no}</span></>} amount={l.amount} />
            </label>
          ))}
        </div>
      </div>
      {bank && picked.length > 0 && (
        <div className="savebar">
          <span>
            Selected {money(total)} · difference <b>{money(total - bank.amount)}</b>
          </span>
          <label className="check">
            <input type="checkbox" checked={learn} onChange={(e) => setLearn(e.target.checked)} /> Learn a rule from this
          </label>
          <button className="btn primary" onClick={save}>Save match</button>
        </div>
      )}
      {data.duplicates.length > 0 && (
        <p className="muted small">
          Set aside as duplicates: {data.duplicates.map((d) => `${d.kind} ${d.id} (same as ${d.original})`).join(", ")}
        </p>
      )}
    </>
  );
}

export function Rules({ guard }) {
  const [rules, setRules] = useState(null);
  useEffect(() => { api.rules().then(setRules); }, []);
  if (!rules) return <p className="muted">Loading…</p>;
  if (!rules.length) return <p className="muted">No rules yet. Use “Approve and learn a rule” on a suggested match to create one.</p>;
  const setStatus = (id, s) => guard(async () => setRules(await api.ruleStatus(id, s)));
  return (
    <>
      <p className="muted">Rules are plain data and run first on the next reconciliation. Nothing runs until you activate it.</p>
      {rules.map((r) => (
        <article className="card" key={r.id}>
          <div className="card-head">
            <b>#{r.id} {r.name}</b>
            <span className={`st ${r.status}`}>{r.status}</span>
            <span className="muted small">used {r.hits} times</span>
          </div>
          <code className="rule">
            description matches /{r.pattern}/ → party “{r.party}”, within {r.date_window} days, tolerance {r.tolerance_pct}%
          </code>
          <p className="muted small">Learned from: {r.example}</p>
          <div className="actions">
            {r.status !== "active" && <button className="btn primary" onClick={() => setStatus(r.id, "active")}>Activate</button>}
            {r.status !== "disabled" && <button className="btn" onClick={() => setStatus(r.id, "disabled")}>Disable</button>}
          </div>
        </article>
      ))}
    </>
  );
}

export function Audit() {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.audit().then(setRows); }, []);
  if (!rows) return <p className="muted">Loading…</p>;
  return (
    <div className="scroll">
      <table>
        <thead>
          <tr><th>Time</th><th>Event</th><th>Actor</th><th>Bank</th><th>Ledger</th><th>Layer</th><th>Detail</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="nowrap">{String(r.ts).replace("T", " ")}</td>
              <td className="nowrap">{r.event}</td>
              <td>{r.actor}</td>
              <td>{r.bank_ids}</td>
              <td>{r.ledger_ids}</td>
              <td className="nowrap">{r.layer}</td>
              <td className="reason-cell">{r.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Summary({ guard }) {
  const [text, setText] = useState("");
  return (
    <>
      <button className="btn primary" onClick={() => guard(async () => setText((await api.summary()).text))}>
        Write month-end summary
      </button>
      {text && <Markdown text={text} />}
    </>
  );
}

// Small renderer for the summary: headings, bullets and **bold**.
function Markdown({ text }) {
  const bold = (s) => s.split(/\*\*(.+?)\*\*/g).map((p, i) => (i % 2 ? <b key={i}>{p}</b> : p));
  const blocks = [];
  let list = [];
  const flush = () => {
    if (list.length) blocks.push(<ul key={blocks.length}>{list.map((l, i) => <li key={i}>{bold(l)}</li>)}</ul>);
    list = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (/^[-*] /.test(line)) list.push(line.slice(2));
    else {
      flush();
      if (/^#+ /.test(line)) blocks.push(<h3 key={blocks.length}>{line.replace(/^#+ /, "")}</h3>);
      else if (/^\*\*[^*]+\*\*:?$/.test(line)) blocks.push(<h3 key={blocks.length}>{line.replace(/\*\*|:$/g, "")}</h3>);
      else if (line) blocks.push(<p key={blocks.length}>{bold(line)}</p>);
    }
  }
  flush();
  return <div className="md">{blocks}</div>;
}
