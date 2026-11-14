"""Tests for core/seed.py and reset_demo.py. Run: python -m pytest tests/test_seed.py

Uses only the real data/seed.json, the standard library and pytest's tmp_path.
No other Synthrax code is needed.
"""
import json
import sqlite3

from core.seed import (
    build_events,
    canonical_drug,
    check_flags_in_step,
    find_medication,
    is_high_risk,
    is_time_critical,
    load_seed,
    load_seed_file,
)
from reset_demo import reset_demo

SEED = load_seed_file()


def rows(db_path, sql="SELECT * FROM events ORDER BY seq"):
    con = sqlite3.connect(db_path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


# ---------- the seed file ----------

def test_seed_has_expected_people_and_medicines():
    assert [r["name"] for r in SEED["residents"]] == ["Margaret Hughes", "Arthur Bell", "Doris Patel"]
    assert len(SEED["medications"]) == 7
    assert [n["id"] for n in SEED["nodes"]] == ["carehome", "gp", "pharmacy"]
    assert SEED["demo_now"] == "18:00"


def test_margarets_warfarin_starts_at_v1_5mg():
    warfarin = find_medication(SEED, "warfarin", resident_id="R1")
    assert warfarin["dose"] == "5mg"
    assert warfarin["rx_version"] == 1
    assert warfarin["times"] == ["18:00"]


def test_risk_flags_match_the_two_drug_lists():
    assert check_flags_in_step(SEED) == []


def test_check_flags_catches_a_mismatch():
    broken = json.loads(json.dumps(SEED))
    find_medication(broken, "warfarin")["high_risk"] = False
    assert len(check_flags_in_step(broken)) == 1


def test_every_starting_event_is_valid():
    """Known type, right author, real resident and medication."""
    meds = {m["id"]: m for m in SEED["medications"]}
    residents = {r["id"] for r in SEED["residents"]}
    for ev in SEED["starting_events"]:
        spec = SEED["event_types"][ev["type"]]
        assert spec["author"] in ("any", ev["author"]), ev
        assert ev["resident_id"] in residents, ev
        if "medication_id" in ev:
            assert ev["medication_id"] in meds, ev
            assert meds[ev["medication_id"]]["resident_id"] == ev["resident_id"], ev


# ---------- looking up drugs ----------

def test_find_medication_ignores_case():
    assert find_medication(SEED, "WARFARIN")["id"] == "M1"
    assert find_medication(SEED, " Warfarin ")["id"] == "M1"


def test_find_medication_checks_aliases():
    assert find_medication(SEED, "Sinemet")["drug"] == "Co-careldopa"
    assert find_medication(SEED, "water tablet")["drug"] == "Furosemide"


def test_find_medication_can_be_limited_to_one_resident():
    assert find_medication(SEED, "Sinemet", resident_id="R2")["id"] == "M4"
    assert find_medication(SEED, "Sinemet", resident_id="R1") is None


def test_find_medication_unknown_is_none():
    assert find_medication(SEED, "not-a-drug") is None


def test_risk_lookups():
    assert is_high_risk(SEED, "Warfarin")
    assert is_high_risk(SEED, "ibuprofen") is False
    assert is_time_critical(SEED, "Sinemet")          # alias of co-careldopa
    assert is_time_critical(SEED, "co-careldopa")
    assert not is_time_critical(SEED, "Warfarin")
    assert not is_high_risk(SEED, "Amlodipine")
    assert not is_high_risk(SEED, "not-a-drug")
    assert canonical_drug(SEED, "Sinemet") == "co-careldopa"


# ---------- building events (no database) ----------

def test_build_events_counts_and_types():
    events = build_events(SEED)
    assert len(events) == len(SEED["starting_events"]) == 11
    types = [e["type"] for e in events]
    assert types.count("RX_CREATED") == 7
    assert types.count("OBSERVATION") == 1
    assert types.count("DOSE_GIVEN") == 3


def test_build_events_ids_unique_and_ordered_by_time():
    events = build_events(SEED)
    assert len({e["id"] for e in events}) == len(events)
    assert [e["lamport"] for e in events] == list(range(1, len(events) + 1))
    times = [e["created_at"] for e in events]
    assert times == sorted(times)


def test_margarets_inr_is_32_hours_before_demo_now():
    events = build_events(SEED)
    inr = [e for e in events if e["type"] == "OBSERVATION" and e["resident_id"] == "R1"]
    assert len(inr) == 1
    assert inr[0]["payload"]["kind"] == "INR_taken"
    assert inr[0]["created_at"] == -32 * 60


def test_now_minutes_shifts_every_time():
    base = build_events(SEED)
    shifted = build_events(SEED, now_minutes=1080)  # 18:00 as minutes after midnight
    assert [s["created_at"] - b["created_at"] for s, b in zip(shifted, base)] == [1080] * len(base)


def test_dose_given_records_the_version_it_used():
    for e in build_events(SEED):
        if e["type"] == "DOSE_GIVEN":
            assert e["seen_version"] == e["payload"]["rx_version_used"] == 1
        else:
            assert e["seen_version"] is None


def test_arthurs_late_dose_keeps_its_times():
    late = [e for e in build_events(SEED)
            if e["type"] == "DOSE_GIVEN" and e["payload"]["given_at"] == "16:05"]
    assert len(late) == 1
    assert late[0]["rx_id"] == "M4"
    assert late[0]["payload"]["scheduled_time"] == "16:00"


# ---------- loading into SQLite ----------

def test_load_seed_creates_database(tmp_path):
    db = tmp_path / "data" / "carehome.db"
    summary = load_seed(db)
    assert db.exists()
    assert summary["residents"] == 3
    assert summary["events_in_seed"] == summary["events_inserted"] == 11
    assert len(rows(db)) == 11
    assert len(rows(db, "SELECT * FROM residents")) == 3


def test_load_seed_stores_event_details(tmp_path):
    db = tmp_path / "gp.db"
    load_seed(db)
    first = rows(db, "SELECT id, seq, resident_id, rx_id, type, author, payload FROM events ORDER BY seq")[0]
    assert first[0] == "seed-001" and first[1] == 1
    assert first[4] == "RX_CREATED" and first[5] == "gp"
    payload = json.loads(first[6])
    assert payload["drug"] and payload["dose"] and payload["rx_version"] == 1
    assert "medication_id" not in payload   # it is in the rx_id column


def test_loading_twice_changes_nothing(tmp_path):
    db = tmp_path / "carehome.db"
    load_seed(db)
    before = rows(db)
    again = load_seed(db)
    assert again["events_inserted"] == 0
    assert rows(db) == before


def test_every_node_gets_identical_events(tmp_path):
    for node in ("carehome", "gp", "pharmacy"):
        load_seed(tmp_path / f"{node}.db")
    dumps = [rows(tmp_path / f"{n}.db") for n in ("carehome", "gp", "pharmacy")]
    assert dumps[0] == dumps[1] == dumps[2]


def test_load_seed_respects_now_minutes(tmp_path):
    db = tmp_path / "x.db"
    load_seed(db, now_minutes=1080)
    inr = rows(db, "SELECT created_at FROM events WHERE type = 'OBSERVATION'")
    assert inr == [(1080 - 32 * 60,)]


# ---------- demo reset ----------

def test_reset_demo_builds_one_database_per_node(tmp_path):
    result = reset_demo(data_dir=tmp_path)
    assert set(result) == {"carehome", "gp", "pharmacy"}
    for node in result:
        assert len(rows(tmp_path / f"{node}.db")) == 11


def test_reset_demo_wipes_old_data_and_is_repeatable(tmp_path):
    reset_demo(data_dir=tmp_path)
    # simulate a rehearsal that added an event and left a stray file behind
    con = sqlite3.connect(tmp_path / "carehome.db")
    with con:
        con.execute("INSERT INTO events (id, seq, resident_id, type, payload, author, created_at, lamport) "
                    "VALUES ('live-1', 99, 'R1', 'RX_CHANGED', '{}', 'gp', 5, 99)")
    con.close()
    (tmp_path / "old.db").write_bytes(b"junk")

    reset_demo(data_dir=tmp_path)

    assert not (tmp_path / "old.db").exists()
    assert len(rows(tmp_path / "carehome.db")) == 11
    first = {n: rows(tmp_path / f"{n}.db") for n in ("carehome", "gp", "pharmacy")}
    reset_demo(data_dir=tmp_path)
    assert first == {n: rows(tmp_path / f"{n}.db") for n in ("carehome", "gp", "pharmacy")}
    