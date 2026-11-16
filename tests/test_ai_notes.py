"""AI notes: names never reach the LLM, all three demo notes parse, and each feeds the right rule."""
import json
from pathlib import Path

import pytest

from core.derive import derive
from core.rules import evaluate
from core.types import SyncState
from node.actions import Actions
from node.agent import llm
from node.agent.parse_note import _user_prompt, parse_note
from node.agent.redact import all_names, redact
from node.clock_client import minute_of
from node.seed_loader import load_seed, read_seed, residents
from node.store import EventStore

DATA = Path(__file__).resolve().parents[1] / "data"
SEED = read_seed(DATA / "seed_data.json")
NAMES = all_names(SEED["residents"])
NOTES = {n["note"].split()[0].split("'")[0].lower(): n["note"] for n in SEED["messy_carer_notes_for_ai"]}


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.delenv("LLM_API_KEY", raising=False)


@pytest.fixture
def home(tmp_path):
    store = EventStore(tmp_path / "carehome.db")
    load_seed(DATA / "seed_data.json", store)
    return store, Actions("carehome", store, now=lambda: 240)


def meds(store, resident):
    return [rx for rx in derive(store.all()).rx.values() if rx.resident_id == resident]


def test_names_and_nicknames_are_removed():
    for note in NOTES.values():
        safe = redact(note, NAMES)
        for name in NAMES:
            assert name.lower() not in safe.lower().split(), (name, safe)
    assert redact("Mags had a fall", NAMES) == "the resident had a fall"
    assert redact("Doris Patel refused", NAMES) == "the resident refused"


def test_the_prompt_sent_to_claude_has_no_names(home):
    store, _ = home
    prompt = _user_prompt(redact(NOTES["arthur"], NAMES), meds(store, "R2"))
    assert "Arthur" not in prompt and "Bell" not in prompt


@pytest.mark.parametrize("who, resident", [("doris", "R3"), ("arthur", "R2"), ("mags", "R1")])
def test_every_demo_note_has_a_cached_answer(home, who, resident):
    store, _ = home
    parsed = parse_note(redact(NOTES[who], NAMES), meds(store, resident))
    assert parsed is not None and llm.last_source == "cached"


def test_arthurs_late_dose_note_becomes_an_r4_warning(home):
    store, actions = home
    parsed = parse_note(redact(NOTES["arthur"], NAMES), meds(store, "R2"))
    (item,) = parsed.items
    assert (item.kind, item.rx_id, item.scheduled_time, item.given_at) == ("dose_given", "M4", "12:00", "12:45")
    actions.give_dose("R2", "M4", slot=minute_of(item.scheduled_time), given_at=minute_of(item.given_at))
    flags = evaluate(derive(store.all(), residents(SEED)), 240, SyncState(online=True, last_seen={"gp": 240}))
    (r4,) = [f for f in flags if f.rule == "R4"]
    assert "given 45 min late" in r4.message


def test_dorises_note_becomes_a_low_stock_repeat(home):
    store, actions = home
    parsed = parse_note(redact(NOTES["doris"], NAMES), meds(store, "R3"))
    assert [i.kind for i in parsed.items] == ["refusal", "symptom", "stock_count"]
    actions.record_stock_count("R3", "M6", 3)
    flags = evaluate(derive(store.all()), 240, SyncState(online=True, last_seen={"gp": 240}))
    assert ("R5", "M6") in [(f.rule, f.rx_id) for f in flags]


def test_a_dose_cannot_be_recorded_in_the_future(home):
    _, actions = home
    with pytest.raises(ValueError):
        actions.give_dose("R2", "M4", slot=minute_of("20:00"), given_at=minute_of("20:30"))


def test_bad_times_from_the_ai_are_rejected(monkeypatch, home):
    store, _ = home
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {"summary": "s", "items": [
        {"kind": "dose_given", "detail": "x", "source_text": "x", "given_at": "about lunchtime"}]})
    assert parse_note("anything", meds(store, "R2")) is None          # falls back to the manual form


def test_status_reports_what_the_ai_is_doing(monkeypatch):
    assert llm.status() == "cached"
    monkeypatch.setenv("DEMO_MODE", "0")
    assert llm.status() == "off"
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    assert llm.status() == "live"