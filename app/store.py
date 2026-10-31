"""Persistence + stats. MongoDB Atlas when MONGODB_URI is set, otherwise in-memory.

Stores each visitor's progress (so a session survives restarts) and a ledger of
every ghost reply, including the ones the spoiler guard blocked. The ledger is
what gives us honest numbers for the write-up.
"""
from __future__ import annotations

import os
import time

from .game import GameState


def state_to_doc(s: GameState) -> dict:
    return {"room": s.room, "inv": sorted(s.inv), "flags": sorted(s.flags),
            "log": s.log[-20:], "won": s.won, "moves": s.moves}


def doc_to_state(d: dict) -> GameState:
    return GameState(room=d["room"], inv=set(d["inv"]), flags=set(d["flags"]),
                     log=list(d["log"]), won=d["won"], moves=d["moves"])


class MemoryStore:
    name = "memory"

    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.ledger: list[dict] = []

    def save_session(self, sid: str, state: GameState) -> None:
        self.sessions[sid] = state_to_doc(state)

    def load_session(self, sid: str) -> GameState | None:
        d = self.sessions.get(sid)
        return doc_to_state(d) if d else None

    def log_reply(self, sid: str, question: str, reply: str, blocked: bool, real: bool) -> None:
        self.ledger.append({"sid": sid, "q": question, "reply": reply, "blocked": blocked,
                            "real": real, "t": time.time()})

    def stats(self) -> dict:
        n = len(self.ledger)
        return {"replies": n, "blocked": sum(r["blocked"] for r in self.ledger),
                "real_probs": sum(r["real"] for r in self.ledger),
                "sessions": len(self.sessions),
                "won": sum(1 for d in self.sessions.values() if d["won"])}


class MongoStore(MemoryStore):
    name = "mongodb"

    def __init__(self, uri: str):
        from pymongo import MongoClient
        db = MongoClient(uri, serverSelectionTimeoutMS=3000)[os.getenv("MONGODB_DB", "midnight_house")]
        self.sess, self.led = db["sessions"], db["ledger"]
        self.sess.database.client.admin.command("ping")  # fail fast -> caller falls back

    def save_session(self, sid, state):
        self.sess.replace_one({"_id": sid}, {"_id": sid, **state_to_doc(state)}, upsert=True)

    def load_session(self, sid):
        d = self.sess.find_one({"_id": sid})
        return doc_to_state(d) if d else None

    def log_reply(self, sid, question, reply, blocked, real):
        self.led.insert_one({"sid": sid, "q": question, "reply": reply, "blocked": blocked,
                             "real": real, "t": time.time()})

    def stats(self):
        n = self.led.count_documents({})
        return {"replies": n, "blocked": self.led.count_documents({"blocked": True}),
                "real_probs": self.led.count_documents({"real": True}),
                "sessions": self.sess.count_documents({}),
                "won": self.sess.count_documents({"won": True})}


def get_store():
    uri = os.getenv("MONGODB_URI")
    if uri:
        try:
            return MongoStore(uri)
        except Exception as e:
            print("MongoDB unavailable, using in-memory store:", type(e).__name__)
    return MemoryStore()
