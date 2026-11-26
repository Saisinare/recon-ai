async function call(path, opts = {}) {
  const res = await fetch(`/api${path}`, opts);
  const isJson = res.headers.get("content-type")?.includes("json");
  const body = isJson ? await res.json() : await res.text();
  if (!res.ok) throw new Error(body?.detail || body || res.statusText);
  return body;
}

const post = (path, data) =>
  call(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data ?? {}) });

export const api = {
  providers: () => call("/providers"),
  state: () => call("/state"),
  run: (form) => call("/run", { method: "POST", body: form }),
  approve: (id, learn) => post(`/matches/${id}/approve`, { learn }),
  reject: (id) => post(`/matches/${id}/reject`),
  manual: (bank_id, ledger_ids, learn) => post("/matches/manual", { bank_id, ledger_ids, learn }),
  rules: () => call("/rules"),
  ruleStatus: (id, status) => post(`/rules/${id}/status`, { status }),
  audit: () => call("/audit"),
  summary: () => post("/summary"),
};

export const money = (n) =>
  Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
