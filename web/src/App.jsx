import React, { useEffect, useState } from "react";
import { api } from "./api.js";
import { Sidebar, Empty, Kpis } from "./parts.jsx";
import { Review, Matched, Unmatched, Rules, Audit, Summary } from "./tabs.jsx";

const TABS = ["Needs review", "Matched", "Unmatched", "Rules", "Audit log", "Summary"];

export default function App() {
  const [providers, setProviders] = useState([]);
  const [settings, setSettings] = useState({ provider: "none", model: "", threshold: 0.9, embeddings: false, useSample: true });
  const [files, setFiles] = useState({ bank: null, ledger: null });
  const [data, setData] = useState({ ready: false });
  const [tab, setTab] = useState(TABS[0]);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);

  const notify = (text, kind = "info") => {
    setToast({ text, kind });
    setTimeout(() => setToast(null), 5000);
  };
  const guard = async (fn) => {
    try {
      setBusy(true);
      await fn();
    } catch (e) {
      notify(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    api.providers().then((p) => {
      setProviders(p);
      const ready = p.find((x) => x.name !== "none" && x.name !== "ollama" && x.available);
      if (ready) setSettings((s) => ({ ...s, provider: ready.name }));
    }).catch(() => {});
    api.state().then(setData).catch(() => {});
  }, []);

  const run = () =>
    guard(async () => {
      const f = new FormData();
      f.append("provider", settings.provider);
      f.append("model", settings.model);
      f.append("threshold", settings.threshold);
      f.append("embeddings", settings.embeddings);
      f.append("use_sample", settings.useSample);
      if (!settings.useSample) {
        if (!files.bank || !files.ledger) throw new Error("Choose both a bank file and a ledger file.");
        f.append("bank", files.bank);
        f.append("ledger", files.ledger);
      }
      const s = await api.run(f);
      setData(s);
      if (s.llm?.errors?.length) notify(`Some LLM calls failed; heuristics filled in. ${s.llm.errors.at(-1)}`, "error");
    });

  const after = (res) => {
    setData(res.state);
    if (res.rule) notify(`Rule #${res.rule.id} proposed: /${res.rule.pattern}/ → ${res.rule.party}. Activate it on the Rules tab.`);
  };

  return (
    <div className="shell">
      <Sidebar {...{ providers, settings, setSettings, files, setFiles, run, busy }} />
      <main>
        <header className="top">
          <div>
            <h1>Recon AI</h1>
            <p className="muted">Code does the math. The LLM reads messy text and judges unclear cases. Your corrections become rules.</p>
          </div>
          {data.ready && (
            <a className="btn ghost" href="/api/export.csv">
              Export matches
            </a>
          )}
        </header>

        {!data.ready ? (
          <Empty />
        ) : (
          <>
            <Kpis s={data.stats} llm={data.llm} />
            <nav className="tabs" role="tablist">
              {TABS.map((t) => (
                <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
                  {t}
                  {t === "Needs review" && data.stats.needs_review > 0 && <span className="pill">{data.stats.needs_review}</span>}
                </button>
              ))}
            </nav>
            <section className="panel">
              {tab === "Needs review" && <Review data={data} guard={guard} after={after} />}
              {tab === "Matched" && <Matched data={data} />}
              {tab === "Unmatched" && <Unmatched data={data} guard={guard} after={after} />}
              {tab === "Rules" && <Rules guard={guard} />}
              {tab === "Audit log" && <Audit />}
              {tab === "Summary" && <Summary guard={guard} />}
            </section>
          </>
        )}
      </main>
      {toast && <div className={`toast ${toast.kind}`} role="status">{toast.text}</div>}
    </div>
  );
}
