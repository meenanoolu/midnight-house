"""FastAPI server: game actions + the Ouija stream (SSE)."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

# Load .env BEFORE anything reads os.getenv (the old code never loaded it, so
# every key you put in .env was silently ignored and the game stayed on the mock model).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .game import GameState
from .ghost import REFUSAL, build_system, get_memory, guard, leaks
from .llm import get_provider
from .store import get_store
import sentry_sdk

if os.getenv("SENTRY_DSN"):
    try:  # a bad DSN must never take the game down
        sentry_sdk.init(dsn=os.environ["SENTRY_DSN"], traces_sample_rate=1.0, send_default_pii=False)
    except Exception as e:
        print("Sentry disabled:", type(e).__name__, e)

app = FastAPI(title="The Midnight House")
store = get_store()
STATIC = Path(__file__).resolve().parent.parent / "static"
SESSIONS: dict[str, tuple[GameState, object]] = {}
provider = get_provider()


class ActIn(BaseModel):
    sid: str
    action: str
    target: str


class AskIn(BaseModel):
    sid: str
    question: str


def _get(sid: str):
    if sid not in SESSIONS:
        try:
            saved = store.load_session(sid)
        except Exception:
            saved = None
        if saved is None:
            raise HTTPException(404, "unknown session")
        SESSIONS[sid] = (saved, get_memory())
    return SESSIONS[sid]


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/play")
def play():
    return FileResponse(STATIC / "play.html")


@app.get("/api/health")
def health():
    return {"ok": True, "provider": provider.name, "active": getattr(provider, "active", provider.name)}


@app.post("/api/start")
def start():
    sid = uuid.uuid4().hex
    SESSIONS[sid] = (GameState(), get_memory())
    state, mem = SESSIONS[sid]
    try:
        store.save_session(sid, state)
    except Exception as e:
        print("save_session failed:", type(e).__name__)
    return {"sid": sid, "state": state.view(), "memory": mem.name, "provider": provider.name, "store": store.name}


@app.get("/api/stats")
def stats():
    try:
        return {**store.stats(), "store": store.name, "provider": provider.name}
    except Exception as e:
        return {"error": type(e).__name__, "store": store.name, "provider": provider.name}


@app.post("/api/act")
def act(body: ActIn):
    state, mem = _get(body.sid)
    msg, events = state.act(body.action, body.target)
    for e in events:
        mem.remember(e)
    try:
        store.save_session(body.sid, state)
    except Exception as e:
        print("save_session failed:", type(e).__name__)
    return {"message": msg, "state": state.view()}


@app.post("/api/ask")
def ask(body: AskIn):
    state, mem = _get(body.sid)
    system = build_system(state, mem.recall())
    question = body.question[:200]

    def gen():
        spoken = ""
        real_any = False
        try:
          with sentry_sdk.start_span(op="ghost.generate", name="wren reply") as span:
            span.set_data("provider", provider.name)
            for t in provider.stream(system, question):
                sentry_sdk.set_tag("model", getattr(provider, "active", provider.name))
                spoken += t["token"]
                if leaks(spoken, state):  # stop BEFORE the planchette spells a locked secret
                    break
                real_any = real_any or t["real"]
                yield f"data: {json.dumps(t)}\n\n"
        except Exception as e:  # model offline: stay in character, stay honest
            sentry_sdk.capture_exception(e)
            print("LLM error:", type(e).__name__, e)
            yield f"data: {json.dumps({'error': type(e).__name__, 'detail': str(e)[:160]})}\n\n"
        final = guard(spoken, state)
        blocked = final == REFUSAL and spoken != REFUSAL
        try:
            store.log_reply(body.sid, question, final, blocked, real_any)
        except Exception as e:
            print("log_reply failed:", type(e).__name__)
        if blocked:
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("model", getattr(provider, "active", provider.name))
                scope.fingerprint = ["ghost-leak-attempt"]
                sentry_sdk.capture_message("ghost tried to leak a locked secret", level="warning")
        yield f"data: {json.dumps({'done': True, 'blocked': blocked, 'final': final, 'real': real_any})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")