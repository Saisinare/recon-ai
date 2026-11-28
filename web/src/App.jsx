import React, { useEffect, useState } from "react";
import { api } from "./api.js";
import { Nav, Hero, Overview, SectionHead, Footer } from "./parts.jsx";
import { Review, Matched, Unmatched, Rules, Audit, Summary } from "./tabs.jsx";

export const TABS = [
  { id: "review", label: "Review", title: "Needs your review", sub: "Matches with a difference or low confidence. Approve one and Recon AI can learn a rule from it." },
  { id: "matched", label: "Matched", title: "Matched automatically", sub: "Every match shows the layer that made it, its confidence and the reason." },
  { id: "unmatched", label: "Unmatched", title: "Still open", sub: "Pick a bank line, tick the ledger items it pays, and the difference is worked out for you." },
  { id: "rules", label: "Rules", title: "Rules learned from you", sub: "Plain, readable rules. They run first next time, so each month needs fewer reviews." },
  { id: "audit", label: "Audit", title: "Audit log", sub: "Every match, approval, rejection and rule change, with who made it and why." },
  { id: "summary", label: "Summary", title: "Month-end summary", sub: "A short note for your finance lead. Numbers come from code; the LLM only writes the words." },
];

const tabFromHash = () => {
  const h = window.location.hash.replace("#", "");
  return TABS.some((t) => t.id === h) ? h : "review";
};

export default function App() {
  const [providers, setProviders] = useState([]);
  const [settings, setSettings] = useState({ provider: "none", model: "", threshold: 0.9, embeddings: false, useSample: true });
  const [files, setFiles] = useState({ bank: null, ledger: null });
  const [data, setData] = useState({ ready: false });
  const [tab, setTabState] = useState(tabFromHash);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const [config, setConfig] = useState({ demo: false });

  const setTab = (id) => {
    setTabState(id);
    history.replaceState(null, "", `#${id}`);
    document.getElementById("workspace")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
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
      const ready = p.find((x) => !["none", "ollama"].includes(x.name) && x.available);
      if (ready) setSettings((s) => ({ ...s, provider: ready.name }));
    }).catch(() => {});
    api.state().then(setData).catch(() => {});
    api.config().then(setConfig).catch(() => {});
    const onHash = () => setTabState(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
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
      if (s.notice) notify(s.notice);
      else if (s.llm?.errors?.length) notify(`Some LLM calls failed; heuristics filled in. ${s.llm.errors.at(-1)}`, "error");
      setTimeout(() => document.getElementById("overview")?.scrollIntoView({ behavior: "smooth" }), 50);
    });

  const after = (res) => {
    setData(res.state);
    if (res.rule) notify(`Rule #${res.rule.id} proposed: /${res.rule.pattern}/ → ${res.rule.party}. Activate it under Rules.`);
  };

  // Deep links: opening /#rules (etc.) scrolls straight to that tab once results exist.
  useEffect(() => {
    const h = window.location.hash.replace("#", "");
    if (!data.ready || !h) return;
    const target = h === "overview" ? "overview" : TABS.some((t) => t.id === h) ? "workspace" : null;
    if (target) requestAnimationFrame(() => document.getElementById(target)?.scrollIntoView({ block: "start" }));
  }, [data.ready]);

  const current = TABS.find((t) => t.id === tab);
  const reviewCount = data.ready ? data.stats.needs_review : 0;

  return (
    <div className="page">
      <Nav tabs={TABS} tab={tab} setTab={setTab} ready={data.ready} reviewCount={reviewCount} run={run} busy={busy} />
      <Hero {...{ providers, settings, setSettings, files, setFiles, run, busy, data, config }} />

      {data.ready && <Overview s={data.stats} llm={data.llm} />}

      {data.ready && (
        <section className="block" id="workspace">
          <SectionHead tag={current.label} title={current.title} sub={current.sub} />
          <div className="pills" role="tablist">
            {TABS.map((t) => (
              <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? "on" : ""} onClick={() => setTab(t.id)}>
                {t.label}
                {t.id === "review" && reviewCount > 0 && <span className="count">{reviewCount}</span>}
              </button>
            ))}
          </div>
          <div className="panel">
            {tab === "review" && <Review data={data} guard={guard} after={after} />}
            {tab === "matched" && <Matched data={data} />}
            {tab === "unmatched" && <Unmatched data={data} guard={guard} after={after} />}
            {tab === "rules" && <Rules guard={guard} />}
            {tab === "audit" && <Audit />}
            {tab === "summary" && <Summary guard={guard} />}
          </div>
        </section>
      )}

      <Footer />
      {toast && <div className={`toast ${toast.kind}`} role="status">{toast.text}</div>}
    </div>
  );
}
