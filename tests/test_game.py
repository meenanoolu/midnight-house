from app.game import GameState
from app.ghost import REFUSAL, build_system, guard
from app.llm import parse_ollama_chunk, parse_openai_chunk


def solve(g):
    for a, t in [("go", "kitchen"), ("examine", "stove"), ("go", "hall"), ("go", "library"),
                 ("examine", "desk"), ("go", "hall"), ("go", "attic"), ("examine", "trunk"),
                 ("go", "hall"), ("go", "kitchen"), ("go", "cellar"), ("examine", "gramophone")]:
        g.act(a, t)


def test_full_playthrough_wins():
    g = GameState()
    solve(g)
    assert g.won


def test_ghost_cannot_leak_before_unlock():
    g = GameState()
    assert "brass key" not in " ".join(g.known_facts())
    assert guard("Look in the desk, child", g) == REFUSAL
    assert "desk" not in build_system(g, []).lower()


def test_unlock_reveals_fact():
    g = GameState()
    g.act("go", "kitchen"); g.act("examine", "stove")
    assert guard("A brass key waits in the desk", g) != REFUSAL


def test_cannot_skip_ahead():
    g = GameState()
    g.act("go", "attic")
    assert "padlock" in g.act("examine", "trunk")[0]


def test_ollama_parser_real_probs():
    chunk = {"response": "Hi", "logprobs": [{"token": "Hi", "logprob": -0.1,
             "top_logprobs": [{"token": "Hi", "logprob": -0.1}, {"token": "Go", "logprob": -2.3}]}]}
    e = parse_ollama_chunk(chunk)[0]
    assert e["real"] and e["alts"][0]["token"] == "Go" and 0.9 < e["prob"] < 0.91


def test_parsers_fall_back_honestly():
    assert parse_ollama_chunk({"response": "x"})[0]["real"] is False
    assert parse_openai_chunk({"choices": [{"delta": {"content": "x"}}]})[0]["real"] is False


def test_chain_falls_through_before_first_token(monkeypatch):
    from app.llm import ChainProvider

    class Bad:
        name = "bad"
        def stream(self, s, u):
            raise RuntimeError("down")
            yield

    class Good:
        name = "good"; model = "m"
        def stream(self, s, u):
            yield {"token": "hi", "prob": None, "alts": [], "real": False}

    c = ChainProvider([Bad(), Good()])
    assert [t["token"] for t in c.stream("s", "u")] == ["hi"]
    assert c.active == "good/m"
