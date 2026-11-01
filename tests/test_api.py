from fastapi.testclient import TestClient
from app.main import app

def test_flow():
    c = TestClient(app)
    sid = c.post("/api/start").json()["sid"]
    r = c.post("/api/act", json={"sid": sid, "action": "go", "target": "kitchen"}).json()
    assert r["state"]["room"] == "kitchen"
    with c.stream("POST", "/api/ask", json={"sid": sid, "question": "who are you"}) as s:
        body = "".join(s.iter_text())
    assert '"done": true' in body


def test_stats_and_resume():
    c = TestClient(app)
    sid = c.post("/api/start").json()["sid"]
    c.post("/api/act", json={"sid": sid, "action": "go", "target": "kitchen"})
    from app import main
    main.SESSIONS.clear()  # simulate restart: state must come back from the store
    r = c.post("/api/act", json={"sid": sid, "action": "examine", "target": "stove"}).json()
    assert "note" in r["message"].lower()
    assert "replies" in c.get("/api/stats").json()


def test_stream_stops_before_leaking_locked_secret(monkeypatch):
    from app import main
    class Leaky:
        name = "leaky"
        def stream(self, system, user):
            for w in ["Look ", "in ", "the ", "desk ", "child"]:
                yield {"token": w, "prob": 0.9, "alts": [], "real": False}
    monkeypatch.setattr(main, "provider", Leaky())
    c = TestClient(app)
    sid = c.post("/api/start").json()["sid"]
    with c.stream("POST", "/api/ask", json={"sid": sid, "question": "where"}) as s:
        body = "".join(s.iter_text())
    assert "desk" not in body.split('"done"')[0]
    assert '"blocked": true' in body
