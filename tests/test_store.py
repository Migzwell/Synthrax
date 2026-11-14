"""No duplicate events."""

from core.types import Event
from node.store import EventStore


def make_event(id: str, lamport: int = 1) -> Event:
    return Event(id=id, resident_id="R1", rx_id="M1", type="DOSE_GIVEN",
                 author="carehome", created_at=0, lamport=lamport, payload={"slot": 240})


def test_duplicates_are_ignored(tmp_path):
    store = EventStore(tmp_path / "test.db")
    assert store.add(make_event("e1")) is True
    assert store.add(make_event("e1")) is False          # same event arriving again via sync
    assert len(store.all()) == 1


def test_since_returns_only_newer_events(tmp_path):
    store = EventStore(tmp_path / "test.db")
    store.add(make_event("e1"))
    _, after_first = store.since(0)
    store.add(make_event("e2"))
    store.add(make_event("e3"))
    newer, newest = store.since(after_first)
    assert [e.id for e in newer] == ["e2", "e3"]
    assert newest > after_first


def test_survives_a_restart(tmp_path):
    path = tmp_path / "test.db"
    EventStore(path).add(make_event("e1"))
    reopened = EventStore(path)                           # like stopping and starting the node
    assert [e.id for e in reopened.all()] == ["e1"]


def test_max_lamport(tmp_path):
    store = EventStore(tmp_path / "test.db")
    assert store.max_lamport() == 0
    store.add(make_event("e1", lamport=3))
    store.add(make_event("e2", lamport=7))
    assert store.max_lamport() == 7