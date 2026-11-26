"""One small client for every provider. All of them speak the OpenAI chat format.

Switch provider with RECON_PROVIDER (or the app sidebar). Keys come from .env.
Calls are cached in SQLite, retried on rate limits, and any failure returns None so
the pipeline falls back to its deterministic heuristics instead of stopping.
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path

import requests

PROVIDERS = {
    # name: (base_url, api-key env var, default model)
    "none": (None, None, None),
    "ollama": ("http://localhost:11434/v1", None, "qwen2.5:7b"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-120b"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "gemini-2.5-flash"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "meta-llama/llama-3.3-70b-instruct:free"),
}


def load_env(path=Path(__file__).resolve().parent.parent / ".env"):
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)\s*$", line)
            if m and not line.lstrip().startswith("#"):
                os.environ.setdefault(m.group(1), m.group(2).strip().strip('"').strip("'"))


class LLM:
    def __init__(self, provider=None, model=None, store=None, timeout=60):
        load_env()
        self.provider = (provider or os.getenv("RECON_PROVIDER") or "none").lower()
        if self.provider not in PROVIDERS:
            raise ValueError(f"Unknown provider {self.provider}. Choose from {list(PROVIDERS)}")
        self.base, key_env, default_model = PROVIDERS[self.provider]
        self.model = model or os.getenv(f"RECON_MODEL_{self.provider.upper()}") or default_model
        self.key = os.getenv(key_env) if key_env else None
        self.store, self.timeout = store, timeout
        self.calls, self.cache_hits, self.errors = 0, 0, []

    @property
    def available(self):
        if self.provider == "none":
            return False
        return self.provider == "ollama" or bool(self.key)

    def status(self):
        if self.provider == "none":
            return "Offline heuristics (no LLM)"
        if not self.available:
            return f"{self.provider}: missing API key in .env"
        return f"{self.provider} / {self.model}"

    def json(self, system: str, user: str):
        if not self.available:
            return None
        key = "llm:" + hashlib.sha1(f"{self.provider}|{self.model}|{system}|{user}".encode()).hexdigest()
        if self.store and (hit := self.store.cache_get(key)) is not None:
            self.cache_hits += 1
            return hit
        body = {"model": self.model, "temperature": 0,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "response_format": {"type": "json_object"}}
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        for attempt in range(4):
            try:
                self.calls += 1
                r = requests.post(f"{self.base}/chat/completions", json=body, headers=headers, timeout=self.timeout)
                if r.status_code == 429 or r.status_code >= 500:
                    wait = float(r.headers.get("retry-after") or 2 ** attempt * 2)
                    time.sleep(min(wait, 30))
                    continue
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
                data = _parse(text)
                if data is not None and self.store:
                    self.store.cache_put(key, data)
                return data
            except Exception as e:  # network, auth, bad JSON: fall back to heuristics
                self.errors.append(f"{type(e).__name__}: {str(e)[:200]}")
                if attempt >= 1:
                    return None
        return None


def _parse(text):
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None
