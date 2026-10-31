"""The ghost: prompt building, spoiler guard, and memory adapters."""
from __future__ import annotations

import os
import re

import httpx

from .game import GameState

REFUSAL = "I cannot say"


def build_system(state: GameState, memories: list[str]) -> str:
    facts = "\n".join(f"- {f}" for f in state.known_facts())
    mem = "\n".join(f"- {m}" for m in memories) or "- (nothing yet)"
    return (
        "You are Wren, a ghost speaking through a spirit board. Reply in at most 12 words, "
        "old-fashioned and sad. You may ONLY use the facts below. If asked about anything "
        f"else, reply exactly: {REFUSAL}.\n\nFacts you may use:\n{facts}\n\n"
        f"What you remember of this visitor:\n{mem}"
    )


def leaks(text: str, state: GameState) -> bool:
    low = text.lower()
    return any(re.search(rf"\b{re.escape(s.lower())}\b", low) for s in state.locked_secrets())


def guard(text: str, state: GameState) -> str:
    """If the model blurted out something the player has not earned, say so instead."""
    return REFUSAL if leaks(text, state) else text


class LocalMemory:
    name = "local"

    def __init__(self):
        self.items: list[str] = []

    def remember(self, event: str) -> None:
        self.items.append(event)

    def recall(self) -> list[str]:
        return self.items[-8:]


class BackboardMemory:
    """Persists milestones in Backboard so Wren remembers a visitor across sessions.

    NOTE: endpoint shapes follow docs.backboard.io as read during the build; verify
    against a live key before relying on them. Failures degrade to local memory.
    """
    name = "backboard"

    def __init__(self, assistant_id: str | None = None, key: str | None = None):
        self.base = "https://app.backboard.io/api"
        self.key = key or os.getenv("BACKBOARD_API_KEY", "")
        self.aid = assistant_id or os.getenv("BACKBOARD_ASSISTANT_ID", "")
        self.fallback = LocalMemory()

    def _h(self):
        return {"X-API-Key": self.key}

    def remember(self, event: str) -> None:
        self.fallback.remember(event)
        try:
            httpx.post(f"{self.base}/assistants/{self.aid}/memories", headers=self._h(),
                       json={"content": event}, timeout=10).raise_for_status()
        except Exception:
            pass

    def recall(self) -> list[str]:
        try:
            r = httpx.post(f"{self.base}/assistants/{self.aid}/memories/search", headers=self._h(),
                           json={"query": "visitor progress in the haunted house"}, timeout=10)
            r.raise_for_status()
            items = r.json().get("memories", [])
            got = [m.get("content", "") for m in items if m.get("content")]
            return got or self.fallback.recall()
        except Exception:
            return self.fallback.recall()


def get_memory():
    if os.getenv("BACKBOARD_API_KEY") and os.getenv("BACKBOARD_ASSISTANT_ID"):
        return BackboardMemory()
    return LocalMemory()
