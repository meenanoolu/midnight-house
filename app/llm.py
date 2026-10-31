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
        self.host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.model = model or os.getenv("OLLAMA_MODEL", "gemma3")

    def stream(self, system: str, user: str) -> Iterator[dict]:
        body = {"model": self.model, "system": system, "prompt": user, "stream": True,
                "logprobs": True, "top_logprobs": 4, "options": {"num_predict": 60, "temperature": 0.8}}
        with httpx.stream("POST", f"{self.host}/api/generate", json=body, timeout=120) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    yield from parse_ollama_chunk(json.loads(line))


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


def get_provider():
    kind = os.getenv("LLM_PROVIDER", "mock")
    return {"ollama": OllamaProvider, "openai": OpenAICompatProvider}.get(kind, MockProvider)()
