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
ollama pull gemma3            # any model works; if OLLAMA_MODEL isn't installed, the first installed one is used
cp .env.example .env          # then set LLM_PROVIDER=ollama in .env (works on Windows too)
python -m uvicorn app.main:app --reload
```
Open http://localhost:8000 and check http://localhost:8000/api/health (shows the active provider).
Needs a recent Ollama with `logprobs` support.

## Run hosted (Render)
Ollama only runs on your own machine, so a hosted demo needs an OpenAI-compatible endpoint (below); without one it runs the mock model.
Push to GitHub, create a Blueprint from `render.yaml`, set `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`
(an OpenAI-compatible Gemma endpoint). If that endpoint has no logprobs, the UI says so
and uses a fixed-speed planchette.

## Memory (optional)
Set `BACKBOARD_API_KEY` and `BACKBOARD_ASSISTANT_ID` so Wren remembers a visitor across sessions.
Endpoints follow the Backboard docs but have not been tested with a live key; memory is shared per assistant, and failures fall back to local memory.

## Tests
`python -m pytest -q`
