"""Model providers. Each yields dicts: {"token", "prob", "alts": [{"token","prob"}], "real": bool}.

`real` is True only when the numbers are the model's actual next-token probabilities.
Providers that cannot expose them (many hosted APIs) yield real=False and the UI
says so honestly instead of faking it.
"""
from __future__ import annotations

import json
import math
import os
import random
from typing import Iterator

import httpx


def _entry(token: str, logprob: float, tops: list[dict] | None, real: bool = True) -> dict:
    alts = []
    for t in tops or []:
        if t.get("token") != token:
            alts.append({"token": t["token"], "prob": round(math.exp(t["logprob"]), 4)})
    return {"token": token, "prob": round(math.exp(logprob), 4), "alts": alts[:4], "real": real}


def parse_ollama_chunk(chunk: dict) -> list[dict]:
    """One streamed /api/generate chunk -> token entries."""
    lps = chunk.get("logprobs")
    if lps:
        return [_entry(e["token"], e["logprob"], e.get("top_logprobs")) for e in lps]
    text = chunk.get("response", "")
    return [{"token": text, "prob": None, "alts": [], "real": False}] if text else []


def parse_openai_chunk(chunk: dict) -> list[dict]:
    """One streamed chat.completions chunk -> token entries."""
    out = []
    for choice in chunk.get("choices", []):
        content = (choice.get("logprobs") or {}).get("content")
        if content:
            out += [_entry(e["token"], e["logprob"], e.get("top_logprobs")) for e in content]
        else:
            text = (choice.get("delta") or {}).get("content")
            if text:
                out.append({"token": text, "prob": None, "alts": [], "real": False})
    return out


class OllamaProvider:
    name = "ollama"

    def __init__(self, host=None, model=None):
        self.host = (host or os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self.wanted = model or os.getenv("OLLAMA_MODEL", "gemma3")
        self.model = self.wanted
        self._resolved = False

    def _resolve_model(self) -> None:
        """Use an installed model. If the wanted tag isn't pulled (e.g. you pulled llama3 but
        the default is gemma3), match by name or fall back to the first installed model."""
        if self._resolved:
            return
        installed = [m["name"] for m in httpx.get(f"{self.host}/api/tags", timeout=5).json().get("models", [])]
        if not installed:
            raise RuntimeError(f"Ollama has no models. Run: ollama pull {self.wanted}")
        base = self.wanted.split(":")[0]
        pick = (next((m for m in installed if m == self.wanted), None)
                or next((m for m in installed if m.split(":")[0] == base), None)
                or installed[0])
        if pick != self.wanted:
            print(f"Ollama model '{self.wanted}' not installed; using '{pick}'. Installed: {installed}")
        self.model, self._resolved = pick, True

    def stream(self, system: str, user: str) -> Iterator[dict]:
        self._resolve_model()
        body = {"model": self.model, "system": system, "prompt": user, "stream": True,
                "logprobs": True, "top_logprobs": 4, "options": {"num_predict": 60, "temperature": 0.8}}
        for attempt in (0, 1):
            with httpx.stream("POST", f"{self.host}/api/generate", json=body, timeout=180) as r:
                if r.status_code == 400 and attempt == 0:
                    body.pop("logprobs"); body.pop("top_logprobs")  # old Ollama: no logprobs, still playable
                    continue
                if r.status_code >= 400:
                    r.read()
                    raise RuntimeError(f"Ollama {r.status_code}: {r.text[:120]}")
                for line in r.iter_lines():
                    if line:
                        yield from parse_ollama_chunk(json.loads(line))
                return


class OpenAICompatProvider:
    """Any OpenAI-compatible endpoint serving an open model (Gemma etc)."""
    name = "openai-compat"

    def __init__(self, base=None, key=None, model=None):
        self.base = (base or os.getenv("LLM_BASE_URL", "")).rstrip("/")
        self.key = key or os.getenv("LLM_API_KEY", "")
        self.model = model or os.getenv("LLM_MODEL", "gemma")

    def stream(self, system: str, user: str) -> Iterator[dict]:
        body = {"model": self.model, "stream": True, "max_tokens": 60, "temperature": 0.8,
                "logprobs": True, "top_logprobs": 4,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        headers = {"Authorization": f"Bearer {self.key}"}
        with httpx.stream("POST", f"{self.base}/chat/completions", json=body, headers=headers, timeout=120) as r:
            if r.status_code == 400:  # endpoint rejects logprobs: retry as a plain chat
                r.read(); body.pop("logprobs"); body.pop("top_logprobs")
                with httpx.stream("POST", f"{self.base}/chat/completions", json=body, headers=headers, timeout=120) as r2:
                    r2.raise_for_status()
                    for line in r2.iter_lines():
                        if line.startswith("data:") and "[DONE]" not in line:
                            yield from parse_openai_chunk(json.loads(line[5:]))
                return
            r.raise_for_status()
            for line in r.iter_lines():
                if line.startswith("data:") and "[DONE]" not in line:
                    yield from parse_openai_chunk(json.loads(line[5:]))


class MockProvider:
    """Offline fallback for tests and demos with no model. Probabilities are NOT real."""
    name = "mock"

    def stream(self, system: str, user: str) -> Iterator[dict]:
        rng = random.Random(len(user))
        for w in "I am still here. He never came back.".split(" "):
            p = round(rng.uniform(0.4, 0.95), 2)
            yield {"token": w + " ", "prob": p, "alts": [{"token": "gone ", "prob": round((1 - p) / 2, 2)}], "real": False}


class ChainProvider:
    """Tries providers in order (e.g. local Ollama -> AI Studio -> OpenRouter).
    Falls through only if a provider fails BEFORE producing a token."""

    def __init__(self, providers):
        self.providers = providers
        self.last = providers[0]

    @property
    def name(self) -> str:
        return "chain:" + ">".join(p.name for p in self.providers)

    @property
    def active(self) -> str:
        return f"{self.last.name}/{getattr(self.last, 'model', '-')}"

    def stream(self, system: str, user: str) -> Iterator[dict]:
        errors = []
        for p in self.providers:
            started = False
            try:
                for t in p.stream(system, user):
                    if not started:
                        started, self.last = True, p
                    yield t
                return
            except Exception as e:
                if started:
                    raise
                errors.append(f"{p.name}: {type(e).__name__} {str(e)[:60]}")
        raise RuntimeError("all providers failed - " + "; ".join(errors))


def _build(kind: str):
    if kind == "ollama":
        return OllamaProvider()
    if kind == "openai":
        if not os.getenv("LLM_BASE_URL"):
            return None
        return OpenAICompatProvider()
    if kind == "openai2":  # second hosted endpoint, e.g. OpenRouter after AI Studio
        if not os.getenv("LLM_BASE_URL_2"):
            return None
        p = OpenAICompatProvider(os.getenv("LLM_BASE_URL_2"), os.getenv("LLM_API_KEY_2", ""), os.getenv("LLM_MODEL_2", "gemma"))
        p.name = "openai2"
        return p
    return MockProvider() if kind == "mock" else None


def get_provider():
    """LLM_CHAIN=ollama,openai,openai2 tries each in order. Otherwise LLM_PROVIDER picks one."""
    chain = [k.strip() for k in os.getenv("LLM_CHAIN", "").split(",") if k.strip()]
    if chain:
        built = [p for p in map(_build, chain) if p]
        for k, p in zip(chain, map(_build, chain)):
            if p is None:
                print(f"LLM_CHAIN: skipping '{k}' (not configured)")
        if built:
            return built[0] if len(built) == 1 else ChainProvider(built)
    kind = os.getenv("LLM_PROVIDER", "mock")
    return _build(kind) or MockProvider()
