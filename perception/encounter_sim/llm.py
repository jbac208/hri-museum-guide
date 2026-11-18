"""LLM clients for the encounter conversation: every one is a callable fn(system, user) -> str. Standard library only.

  FakeLLM       default for tests: deterministic, no network. Selection = first allowed id; extraction = option names
                found as keywords in the answer. Emits the same JSON as a real model, so the guards run on the real path.
  OllamaLLM     local Ollama (http://127.0.0.1:11434), JSON mode, temperature 0, fixed seed.
  RecordingLLM  wraps another client and appends {key, model, raw} lines to a file (key = sha256(system, user)).
  ReplayLLM     answers from such a file; a missing key is an ERROR (never a silent fallback), so a replay is the run
                that was recorded or nothing.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request


def key(system, user):
    return hashlib.sha256(json.dumps([system, user]).encode("utf-8")).hexdigest()


class FakeLLM:
    model = "fake"

    def __call__(self, system, user):
        u = json.loads(user)
        if u["task"] == "select":
            return json.dumps({"next": u["allowed"][0]["id"]})
        low = u["answer"].lower()
        return json.dumps({"layers": [{"kind": o["kind"], "target": o["target"], "confidence": 0.9, "quote": o["name"]}
                                      for o in u["options"] if o["name"] in low]})


class OllamaLLM:
    def __init__(self, model="qwen2.5:7b", host="http://127.0.0.1:11434", seed=0, timeout=120):
        self.model, self.host, self.seed, self.timeout = model, host, seed, timeout

    def __call__(self, system, user):
        body = json.dumps({"model": self.model, "stream": False, "format": "json",
                           "options": {"temperature": 0, "seed": self.seed},
                           "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        req = urllib.request.Request(self.host + "/api/chat", body.encode("utf-8"), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())["message"]["content"]


class RecordingLLM:
    def __init__(self, inner, path):
        self.inner, self.path, self.model = inner, path, inner.model
        open(path, "w").close()

    def __call__(self, system, user):
        raw = self.inner(system, user)
        with open(self.path, "a") as f:
            f.write(json.dumps({"key": key(system, user), "model": self.model, "raw": raw}) + "\n")
        return raw


class ReplayLLM:
    def __init__(self, path):
        rows = [json.loads(l) for l in open(path) if l.strip()]
        self.raw = {r["key"]: r["raw"] for r in rows}
        self.model = rows[0]["model"] if rows else "?"

    def __call__(self, system, user):
        k = key(system, user)
        if k not in self.raw:
            raise KeyError(f"no recorded LLM output for this prompt ({k[:12]}): the inputs changed since recording")
        return self.raw[k]
