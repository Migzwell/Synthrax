"""Loads data/seed_data.json into a site's event log at start-up."""
# Only `starting_events` are loaded. `demo_script_events` happen live during the demo, and
# `messy_carer_notes_for_ai` are test cases for the AI, so neither is added here.
#
# Seed names -> our names (see core/types.py):
#   medication_id -> rx_id        t_hours -> created_at in demo minutes (t_hours * 60 + 240)
#   "INR_taken"   -> "INR_TAKEN"  quantity -> qty      "safety_hold" -> "safety hold"
#   scheduled_time / given_at ("HH:MM") -> minutes on the day given by t_hours
import json
from pathlib import Path
from typing import Any

from core.types import Event, Resident
from .clock_client import from_test_hours, minute_of
from .store import EventStore

DAY_START = 14 * 60


def read_seed(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"{path} is missing or empty: get seed_data.json v3.1 from the pharmacy lead.")
    return json.loads(path.read_text())


def residents(seed: dict) -> list[Resident]:
    return [Resident(id=r["id"], name=r["name"], age=r["age"], room=r["room"]) for r in seed["residents"]]


def _clock_on_day(hhmm: str, event_minute: int) -> int:
    """'16:05' on the same day as an event at `event_minute` -> demo minutes."""
    day = (event_minute + DAY_START) // 1440
    return minute_of(hhmm, day)


def _pack_code(resident_id: str, med: dict, version: int) -> str:
    return f"{resident_id}|{med['id']}|{med['drug'].lower()}|{med['dose']}|v{version}"


def to_events(seed: dict) -> list[Event]:
    """Turn the seed into events with fixed ids, so every site loads identical events
    and loading twice (or syncing them) never duplicates anything."""
    meds = {m["id"]: m for m in seed["medications"]}
    events: list[Event] = []
    lamport = 0

    def add(event_id: str, raw: dict, minute: int, type_: str, payload: dict, rx_id=None, author=None):
        nonlocal lamport
        lamport += 1
        events.append(Event(id=event_id, resident_id=raw["resident_id"], rx_id=rx_id, type=type_,
                            payload=payload, author=author or raw["author"], created_at=minute,
                            lamport=lamport, seen_version=None))

    # Stock: each medication's stock_doses is the count at the 6pm round, so the opening supply is
    # stock_doses plus any doses the starting events record as given.
    given = {}
    for raw in seed["starting_events"]:
        if raw["type"] == "DOSE_GIVEN":
            given[raw["medication_id"]] = given.get(raw["medication_id"], 0) + 1

    for i, raw in enumerate(seed["starting_events"], start=1):
        minute = from_test_hours(raw["t_hours"])
        rx_id = raw.get("medication_id")
        kind = raw["type"]
        if kind == "RX_CREATED":
            med = meds[rx_id]
            add(f"seed-{i:02d}", raw, minute, kind,
                {"drug": raw["drug"], "dose": raw["dose"], "times": raw["times"],
                 "frequency": med.get("frequency"), "aliases": med.get("aliases", []),
                 "prn": med.get("prn", False), "high_risk": med.get("high_risk", False),
                 "time_critical": med.get("time_critical", False)}, rx_id=rx_id)
            add(f"seed-{i:02d}-stock", raw, minute, "DISPENSED",
                {"version": raw.get("rx_version", 1), "qty": med["stock_doses"] + given.get(rx_id, 0),
                 "pack_code": _pack_code(raw["resident_id"], med, raw.get("rx_version", 1))},
                rx_id=rx_id, author="pharmacy")
        elif kind == "OBSERVATION":
            add(f"seed-{i:02d}", raw, minute, kind,
                {"kind": raw["kind"].upper(), "detail": raw.get("detail", "")}, rx_id=rx_id)
        elif kind == "DOSE_GIVEN":
            slot = _clock_on_day(raw["scheduled_time"], minute) if raw.get("scheduled_time") else None
            given_at = _clock_on_day(raw["given_at"], minute) if raw.get("given_at") else minute
            add(f"seed-{i:02d}", raw, minute, kind,
                {"slot": slot, "given_at": given_at, "dose": raw.get("dose"),
                 "version": raw.get("rx_version_used", 1), "staff_name": raw.get("staff_name", "")},
                rx_id=rx_id)
        elif kind == "DOSE_WITHHELD":
            add(f"seed-{i:02d}", raw, minute, kind,
                {"reason": raw.get("reason", "").replace("_", " "), "staff_name": raw.get("staff_name", "")},
                rx_id=rx_id)
        else:
            raise ValueError(f"Seed event type {kind} isn't handled by the loader yet.")

    # Observations about a resident (e.g. INR) belong to their anticoagulant for R1.
    for e in events:
        if e.type == "OBSERVATION" and e.payload["kind"] == "INR_TAKEN" and e.rx_id is None:
            warfarin = [m for m in seed["medications"]
                        if m["resident_id"] == e.resident_id and "warfarin" in m["drug"].lower()]
            if warfarin:
                e.rx_id = warfarin[0]["id"]
    return events


def load_seed(path: Path, store: EventStore) -> int:
    """Add the seed's starting events to `store`. Returns how many were new (0 on a restart)."""
    return sum(store.add(e) for e in to_events(read_seed(path)))