"""The pharmacy lead's 37 rule test cases, run against the real rules.

Each case in data/rule_test_cases.json starts from the seed, applies its setup,
runs the rules at check_at_hours (hours from the 18:00 round) and compares with 'expect'.
"""
import json
from pathlib import Path

import pytest

from core.derive import derive
from core.rules import evaluate
from core.rules.r5 import draft_repeat
from core.types import Event, SyncState
from node.clock_client import from_test_hours, minute_of
from node.seed_loader import read_seed, residents, to_events

DATA = Path(__file__).resolve().parents[1] / "data"
SEED = read_seed(DATA / "seed_data.json")
CASES = json.loads((DATA / "rule_test_cases.json").read_text())["cases"]

NODE_FOR_RULE = {"R6": "pharmacy", "R7": "gp"}
SEVERITY = {"hold": "HOLD", "warn": "WARN", "info": "INFO", "block": "BLOCK", "pharmacist review": "REVIEW"}


def clock_on_day(hhmm: str, minute: int) -> int:
    return minute_of(hhmm, (minute + 14 * 60) // 1440)


def to_event(raw: dict, n: int, case: dict) -> Event:
    """One event in the test cases' format -> our Event (see core/types.py for the mapping)."""
    t = from_test_hours(raw["t_hours"])
    kind, rx = raw["type"], raw.get("medication_id")
    p: dict = {}
    seen = None
    if kind == "RX_CHANGED":
        seen = raw["new_rx_version"] - 1
        p = {"dose": raw["new_dose"], "old_dose": raw.get("old_dose", ""), "reason": raw.get("reason", "")}
    elif kind == "RX_CONFIRMED":
        p = {"reason": raw.get("reason", ""), "version": raw.get("rx_version", 1)}
    elif kind == "RX_ACKNOWLEDGED":
        p = {"version": raw.get("rx_version")}
    elif kind == "RX_CREATED":
        p = {"drug": raw["drug"], "dose": raw["dose"], "times": raw.get("times", []),
             "frequency": raw.get("frequency")}
    elif kind == "DISPENSED":
        p = {"version": raw.get("rx_version", 1), "qty": raw.get("quantity", 0)}
    elif kind == "DOSE_GIVEN":
        p = {"slot": clock_on_day(raw["scheduled_time"], t) if raw.get("scheduled_time") else None,
             "given_at": clock_on_day(raw["given_at"], t) if raw.get("given_at") else t}
    elif kind == "REPEAT_REQUESTED":
        p = {"qty": raw.get("quantity"), "auto_drafted": raw.get("auto_drafted", False)}
    elif kind == "OBSERVATION":
        p = {"kind": raw["kind"].upper(), "detail": raw.get("detail", "")}
        if "stock_doses" in raw:
            p["stock_doses"] = raw["stock_doses"]
        if rx is None:                      # e.g. "furosemide 3 left": the case says which medicine
            rx = case.get("medication_id")
            if p["kind"] == "INR_TAKEN":
                rx = next(m["id"] for m in SEED["medications"]
                          if m["resident_id"] == raw["resident_id"] and m["drug"].lower() == "warfarin")
    return Event(id=f"case-{n}", resident_id=raw["resident_id"], rx_id=rx, type=kind, payload=p,
                 author=raw["author"], created_at=t, lamport=1000 + n, seen_version=seen)


def build(case: dict):
    setup, expect = case["setup"], case["expect"]
    node = expect.get("node") or NODE_FOR_RULE.get(case["rule"], "carehome")
    events = to_events(SEED) if setup.get("baseline") else []

    for gone in setup.get("remove_events", []):
        events = [e for e in events if not (
            e.type == gone["type"] and e.resident_id == gone["resident_id"]
            and str(e.payload.get("kind", "")).upper() == gone.get("kind", "").upper())]

    given = {}
    for e in events:
        if e.type == "DOSE_GIVEN":
            given[e.rx_id] = given.get(e.rx_id, 0) + 1
    for rx_id, changes in setup.get("override_medications", {}).items():
        for e in events:
            if e.rx_id == rx_id and e.type == "RX_CREATED" and "drug" in changes:
                e.payload["drug"] = changes["drug"]
            if e.rx_id == rx_id and e.type == "DISPENSED" and "stock_doses" in changes:
                e.payload["qty"] = changes["stock_doses"] + given.get(rx_id, 0)

    for n, raw in enumerate(setup.get("add_events", [])):
        if node == "carehome" and raw.get("received_by_carehome") is False:
            continue                        # exists at the GP/pharmacy, never reached the care home
        events.append(to_event(raw, n, case))

    scan = setup.get("scan")
    if scan:
        pack_resident, pack_med, _, _, version = scan["pack_code"].split("|")
        if scan["local_rx_version"] > 1:    # the home's record is already newer than this pack
            events.append(Event(id="case-local", resident_id=pack_resident, rx_id=pack_med, type="RX_CHANGED",
                                author="gp", created_at=-300, lamport=900,
                                seen_version=scan["local_rx_version"] - 1, payload={"dose": "3mg"}))
        events.append(Event(id="case-scan", resident_id=scan["giving_to_resident"], rx_id=case["medication_id"],
                            type="OBSERVATION", author="carehome", created_at=-1, lamport=950,
                            payload={"kind": "PACK_SCANNED", "pack_code": scan["pack_code"],
                                     "version": int(version.lstrip("v")), "pack_resident": pack_resident,
                                     "pack_medication": pack_med}))

    now = from_test_hours(case["check_at_hours"])
    offline_since = setup.get("carehome_offline_since_hours")
    if node == "carehome" and offline_since is not None:
        last = from_test_hours(offline_since)
        sync = SyncState(online=False, last_seen={"gp": last, "pharmacy": last})
    else:
        sync = SyncState(online=True, last_seen={"gp": now, "pharmacy": now, "carehome": now})
    return derive(events, residents(SEED)), now, sync, node


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_rule_case(case):
    state, now, sync, node = build(case)
    expect = case["expect"]
    flags = [f for f in evaluate(state, now, sync, node=node) if f.rule == case["rule"]]
    if case.get("medication_id"):
        flags = [f for f in flags if f.rx_id in (case["medication_id"], None)]

    assert bool(flags) == expect["fires"], f"{case['id']}: {case['description']} -> {flags}"
    if not expect["fires"]:
        return
    if "severity" in expect:
        assert flags[0].action == SEVERITY[expect["severity"]]
    if "action" in expect:
        assert flags[0].action == SEVERITY[expect["action"]]
    if "count" in expect:
        assert len(flags) == expect["count"], flags
    if "message_contains" in expect:
        assert any(expect["message_contains"].lower() in f.message.lower() for f in flags), flags
    if "creates" in expect:
        draft = draft_repeat(state.rx[case["medication_id"]])
        assert draft["qty"] == expect["creates"]["quantity"]
        assert draft["auto_drafted"] == expect["creates"]["auto_drafted"]