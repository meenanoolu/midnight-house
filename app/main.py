"""FastAPI server: game actions + the Ouija stream (SSE)."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .game import GameState
from .ghost import REFUSAL, build_system, get_memory, guard
from .llm import get_provider
from .store import get_store
import os
import sentry_sdk

if os.getenv("SENTRY_DSN"):
    sentry_sdk.init(dsn=os.environ["SENTRY_DSN"], traces_sample_rate=1.0, send_default_pii=False)

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
        saved = store.load_session(sid)
        if saved is None:
            raise HTTPException(404, "unknown session")
        SESSIONS[sid] = (saved, get_memory())
    return SESSIONS[sid]


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "provider": provider.name}


@app.post("/api/start")
def start():
    sid = uuid.uuid4().hex
    SESSIONS[sid] = (GameState(), get_memory())
    state, mem = SESSIONS[sid]
    store.save_session(sid, state)
    return {"sid": sid, "state": state.view(), "memory": mem.name, "provider": provider.name, "store": store.name}


@app.get("/api/stats")
def stats():
    return {**store.stats(), "store": store.name, "provider": provider.name}


@app.post("/api/act")
def act(body: ActIn):
    state, mem = _get(body.sid)
    msg, events = state.act(body.action, body.target)
    for e in events:
        mem.remember(e)
    store.save_session(body.sid, state)
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
                spoken += t["token"]
                real_any = real_any or t["real"]
                yield f"data: {json.dumps(t)}\n\n"
        except Exception as e:  # model offline: stay in character, stay honest
            yield f"data: {json.dumps({'error': type(e).__name__})}\n\n"
        final = guard(spoken, state)
        blocked = final == REFUSAL and spoken != REFUSAL
        store.log_reply(body.sid, question, final, blocked, real_any)
        if blocked:
            sentry_sdk.capture_message("ghost tried to leak a locked secret", level="warning")
        yield f"data: {json.dumps({'done': True, 'blocked': blocked, 'final': final, 'real': real_any})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
