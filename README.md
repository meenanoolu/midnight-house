# The Midnight House

A haunted house you explore by talking to its ghost through a spirit board.
The planchette moves using the model's **real next-token probabilities**. Words the
model almost said flicker as faint whispers. Open weights make that possible, because
most closed APIs don't expose token probabilities.

The game rules live in plain code (`app/game.py`). The ghost's prompt only contains facts
the player has unlocked, and a guard blocks any reply that mentions a locked secret.

## Run locally (private, offline)
```
pip install -r requirements.txt
ollama pull gemma3            # any Gemma tag; set OLLAMA_MODEL
LLM_PROVIDER=ollama uvicorn app.main:app
```
Needs a recent Ollama with `logprobs` support.

## Run hosted (Render)
Push to GitHub, create a Blueprint from `render.yaml`, set `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`
(an OpenAI-compatible Gemma endpoint). If that endpoint has no logprobs, the UI says so
and uses a fixed-speed planchette.

## Memory (optional)
Set `BACKBOARD_API_KEY` and `BACKBOARD_ASSISTANT_ID` so Wren remembers a visitor across sessions.
The Backboard endpoint shapes are unverified against a live key; failures fall back to local memory.

## Tests
`python -m pytest -q`
