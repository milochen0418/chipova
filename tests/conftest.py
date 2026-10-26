"""Every test gets its own data folder (CHIPOVA_HOME) and a fresh database."""

from __future__ import annotations

import pytest

from chipova import db
from chipova.services import collab, projects
from chipova.services.actors import Actor

ALICE = Actor("alice@example.com", "Alice", email="alice@example.com")
BOB = Actor("bob@example.com", "Bob", email="bob@example.com")
CAROL = Actor("carol@example.com", "Carol", email="carol@example.com")


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIPOVA_HOME", str(tmp_path / "home"))
    db.reset()
    collab._rooms.clear()
    collab._timers.clear()
    projects.wire()
    yield tmp_path / "home"
    collab.flush()
    collab._rooms.clear()
    db.reset()
