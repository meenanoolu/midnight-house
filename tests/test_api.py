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
