"""Conflict cards: what went wrong offline shows up for the GP, and goes away once reviewed."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.conflicts import find_conflicts
from core.types import Event
from node.actions import Actions
from node.api import make_router
from node.seed_loader import read_seed, to_events
from node.store import EventStore

SEED = to_events(read_seed(Path(__file__).resolve().parents[1] / "data" / "seed_data.json"))


def ev(id, type, author, at, rx="M1", resident="R1", seen=None, **payload):
    return Event(id=id, resident_id=resident, rx_id=rx, type=type, author=author,
                 created_at=at, lamport=100, seen_version=seen, payload=payload)


GP_CHANGE = ev("gp-change", "RX_CHANGED", "gp", at=0, seen=1, dose="3mg")              # 14:00
HELD = ev("held-1800", "DOSE_WITHHELD", "carehome", at=240, slot=240, reason="safety hold")  # 18:00


def test_seed_alone_has_no_cards():
    assert find_conflicts(SEED) == []


def test_demo_story_held_dose_appears_after_reconnect():
    cards = find_conflicts(SEED + [GP_CHANGE, HELD])
    assert [c.kind for c in cards] == ["held_while_offline"]
    card = cards[0]
    assert card.title == "Warfarin held at 18:00"
    assert "v2 (3mg)" in card.message


def test_dose_given_from_old_version_is_urgent():
    gave_5mg = ev("gave-v1", "DOSE_GIVEN", "carehome", at=240, slot=240, given_at=240, version=1)
    card = find_conflicts(SEED + [GP_CHANGE, gave_5mg])[0]
    assert card.kind == "stale_dose" and card.severity == "urgent"
    assert "v2 (3mg) had existed since 14:00" in card.message


def test_dose_given_before_the_change_is_fine():
    gave_earlier = ev("gave-early", "DOSE_GIVEN", "carehome", at=-60, slot=-60, given_at=-60, version=1)
    assert find_conflicts(SEED + [GP_CHANGE, gave_earlier]) == []


def test_pack_from_old_version_is_urgent():
    old_pack = ev("pack-v1", "DISPENSED", "pharmacy", at=60, version=1, qty=28)
    assert [c.kind for c in find_conflicts(SEED + [GP_CHANGE, old_pack])] == ["stale_dispense"]


def test_two_changes_at_once():
    other = ev("other-change", "RX_CHANGED", "gp", at=30, seen=1, dose="4mg")
    card = find_conflicts(SEED + [GP_CHANGE, other])[0]
    assert card.kind == "concurrent_change" and card.id == "concurrent:M1@1"
    assert "3mg" in card.message and "4mg" in card.message


def test_urgent_cards_come_first():
    gave_5mg = ev("gave-v1", "DOSE_GIVEN", "carehome", at=250, slot=240, given_at=250, version=1)
    kinds = [c.kind for c in find_conflicts(SEED + [GP_CHANGE, HELD, gave_5mg])]
    assert kinds == ["stale_dose", "held_while_offline"]


def test_gp_review_closes_the_card(tmp_path):
    store = EventStore(tmp_path / "gp.db")
    for e in SEED + [GP_CHANGE, HELD]:
        store.add(e)
    gp = Actions("gp", store, now=lambda: 260)
    app = FastAPI()
    app.include_router(make_router("gp", store, actions=gp))
    client = TestClient(app)

    cards = client.get("/api/conflicts").json()
    assert len(cards) == 1
    gp.review_conflict("R1", "M1", group=cards[0]["id"], chosen="held-1800", note="Held correctly, no harm")
    assert client.get("/api/conflicts").json() == []