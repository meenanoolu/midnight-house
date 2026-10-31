"""Game rules live in plain code, so the language model can never cheat.

The ghost (an LLM) may only talk about facts the player has unlocked here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ROOMS = {
    "hall": {
        "title": "The Hall",
        "desc": "Dust sheets, a crooked staircase, and a portrait whose eyes follow you.",
        "exits": ["kitchen", "library", "attic"],
        "items": ["portrait"],
    },
    "kitchen": {
        "title": "The Kitchen",
        "desc": "A cold stove. Something white is tucked beneath it.",
        "exits": ["hall", "cellar"],
        "items": ["stove"],
    },
    "library": {
        "title": "The Library",
        "desc": "Shelves of rotting books and one heavy writing desk.",
        "exits": ["hall"],
        "items": ["desk"],
    },
    "attic": {
        "title": "The Attic",
        "desc": "Slanted beams. A trunk sits under the only window, padlocked.",
        "exits": ["hall"],
        "items": ["trunk"],
    },
    "cellar": {
        "title": "The Cellar",
        "desc": "Damp stone. A gramophone rests on a crate, its horn full of cobwebs.",
        "exits": ["kitchen"],
        "items": ["gramophone"],
    },
}

# Facts the ghost may speak about. `requires` is a flag the player must have earned.
# `secrets` are words that must never appear in the ghost's speech before that.
FACTS = [
    {"id": "name", "requires": None, "secrets": [],
     "text": "Her name was Wren Halloway and she died in this house in the winter of 1931."},
    {"id": "brother", "requires": None, "secrets": [],
     "text": "Her brother Tom promised to come home and never did."},
    {"id": "key", "requires": "read_note", "secrets": ["brass key", "desk"],
     "text": "A brass key is hidden in the library desk."},
    {"id": "trunk", "requires": "got_key", "secrets": ["trunk", "music box"],
     "text": "The attic trunk holds Tom's music box."},
    {"id": "gramophone", "requires": "got_music_box", "secrets": ["gramophone"],
     "text": "The music box must be wound beside the gramophone in the cellar to set her free."},
]


@dataclass
class GameState:
    room: str = "hall"
    inv: set = field(default_factory=set)
    flags: set = field(default_factory=set)
    log: list = field(default_factory=list)
    won: bool = False
    moves: int = 0

    # ---------- facts ----------
    def known_facts(self) -> list[str]:
        return [f["text"] for f in FACTS if f["requires"] is None or f["requires"] in self.flags]

    def locked_secrets(self) -> list[str]:
        out: list[str] = []
        for f in FACTS:
            if f["requires"] is not None and f["requires"] not in self.flags:
                out.extend(f["secrets"])
        return out

    # ---------- actions ----------
    def _flag(self, name: str, events: list[str], note: str) -> None:
        if name not in self.flags:
            self.flags.add(name)
            events.append(note)

    def act(self, action: str, target: str) -> tuple[str, list[str]]:
        """Return (narration, milestone events worth remembering)."""
        events: list[str] = []
        if self.won:
            return "The house is quiet now.", events
        action, target = action.lower().strip(), target.lower().strip()
        if action == "go":
            if target not in ROOMS[self.room]["exits"]:
                msg = "There is no way through there."
            else:
                self.room = target
                self.moves += 1
                msg = ROOMS[target]["desc"]
        elif action == "examine":
            msg = self._examine(target, events)
        else:
            msg = "The house does not understand."
        self.log.append(msg)
        return msg, events

    def _examine(self, item: str, events: list[str]) -> str:
        if item not in ROOMS[self.room]["items"]:
            return "You see no such thing here."
        if item == "portrait":
            self._flag("saw_portrait", events, "The visitor looked at Wren's portrait.")
            return "A girl in a pale dress. A brass plate reads: W. HALLOWAY, 1929."
        if item == "stove":
            self._flag("read_note", events, "The visitor read the note under the kitchen stove.")
            return "A note under the stove: 'If you want what he left, ask the desk in the library.'"
        if item == "desk":
            if "got_key" in self.flags:
                return "The drawer is empty now."
            self.inv.add("brass key")
            self._flag("got_key", events, "The visitor found the brass key in the library desk.")
            return "A drawer sticks, then gives. Inside lies a brass key."
        if item == "trunk":
            if "brass key" not in self.inv:
                return "The padlock will not budge."
            if "got_music_box" in self.flags:
                return "The trunk is open and empty."
            self.inv.add("music box")
            self._flag("got_music_box", events, "The visitor opened the attic trunk and took the music box.")
            return "The key turns. Inside, wrapped in cloth: a small music box."
        if item == "gramophone":
            if "music box" not in self.inv:
                return "Nothing to play. The horn is silent."
            self.won = True
            self.flags.add("won")
            events.append("The visitor wound the music box by the gramophone and set Wren free.")
            return "You wind the music box. A slow tune fills the cellar. The cold lifts. Wren is free."
        return "Nothing happens."

    # ---------- view ----------
    def view(self) -> dict:
        room = ROOMS[self.room]
        return {
            "room": self.room,
            "title": room["title"],
            "desc": room["desc"],
            "exits": room["exits"],
            "items": room["items"],
            "inventory": sorted(self.inv),
            "won": self.won,
            "moves": self.moves,
            "log": self.log[-6:],
        }
