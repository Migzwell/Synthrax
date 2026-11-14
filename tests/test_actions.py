"""Actions: each makes the right event, and each site can only do its own job."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from node.actions import Actions
from node.api import make_router
from node.store import EventStore


def site(tmp_path, node_id, now=240):
    store = EventStore(tmp_path / f"{node_id}.db")
    return Actions(node_id, store, now=lambda: now), store


def test_fills_in_id_author_time_and_lamport(tmp_path):
    actions, store = site(tmp_path, "carehome", now=240)
    first = actions.give_dose("R1", "M1", slot=240)
    second = actions.withhold_dose("R1", "M1", reason="refused", slot=240)
    assert first.author == "carehome" and first.created_at == 240
    assert first.id != second.id
    assert second.lamport == first.lamport + 1
    assert [e.id for e in store.all()] == [first.id, second.id]


def test_give_dose_records_when_it_was_due_and_given(tmp_path):
    actions, _ = site(tmp_path, "carehome", now=-75)                 # 12:45
    given = actions.give_dose("R2", "M4", slot=-120, dose="1 tablet", staff_name="Jo")
    assert given.type == "DOSE_GIVEN"
    assert given.payload["slot"] == -120 and given.payload["given_at"] == -75   # 45 min late (R4)


def test_withhold_reasons_match_the_seed(tmp_path):
    actions, _ = site(tmp_path, "carehome")
    assert actions.withhold_dose("R1", "M1", reason="safety_hold").payload["reason"] == "safety hold"
    assert actions.withhold_dose("R3", "M6", reason="Refused").payload["reason"] == "refused"
    with pytest.raises(ValueError):
        actions.withhold_dose("R1", "M1", reason="forgot")


def test_only_the_gp_changes_medicines(tmp_path):
    carehome, _ = site(tmp_path, "carehome")
    with pytest.raises(PermissionError, match="Only the GP"):
        carehome.change_dose("R1", "M1", dose="3mg", seen_version=1)
    gp, _ = site(tmp_path, "gp")
    change = gp.change_dose("R1", "M1", dose="3mg", seen_version=1, old_dose="5mg", reason="INR 4.2 (too high)")
    assert change.type == "RX_CHANGED" and change.seen_version == 1
    assert change.payload == {"dose": "3mg", "old_dose": "5mg", "reason": "INR 4.2 (too high)"}


def test_each_site_does_its_own_job(tmp_path):
    gp, _ = site(tmp_path, "gp")
    pharmacy, _ = site(tmp_path, "pharmacy")
    with pytest.raises(PermissionError):
        gp.give_dose("R1", "M1")                       # only the care home gives doses
    with pytest.raises(PermissionError):
        gp.dispense("R1", "M1", version=2, qty=28)     # only the pharmacy dispenses
    packed = pharmacy.dispense("R1", "M1", version=2, qty=28, drug="Warfarin", dose="3mg")
    assert packed.payload["pack_code"] == "R1|M1|warfarin|3mg|v2"   # same format as the seed's demo script


def test_observations_use_the_seed_kinds(tmp_path):
    actions, _ = site(tmp_path, "carehome")
    assert actions.log_inr_taken("R1", "M1").payload["kind"] == "INR_TAKEN"
    assert actions.log_observation("R1", "fall", "no injury").payload == {"kind": "FALL", "detail": "no injury"}
    assert actions.record_stock_count("R3", "M6", 3).payload == {"kind": "STOCK_COUNT", "stock_doses": 3}
    with pytest.raises(ValueError):
        actions.log_observation("R1", "weather")


def test_scan_pack_reads_the_label(tmp_path):
    actions, _ = site(tmp_path, "carehome")
    scan = actions.scan_pack("R1", "M1", "R1|M1|warfarin|3mg|v2")
    assert scan.payload["version"] == 2
    assert scan.payload["pack_resident"] == "R1" and scan.payload["pack_medication"] == "M1"
    with pytest.raises(ValueError):
        actions.scan_pack("R1", "M1", "https://example.com")


def test_gp_review_and_requests(tmp_path):
    gp, _ = site(tmp_path, "gp")
    assert gp.confirm_no_change("R1", "M1", "INR 2.6, in range, continue 5mg").type == "RX_CONFIRMED"
    assert gp.approve_request("R2", "req-1").payload == {"request": "req-1"}
    review = gp.review_conflict("R1", "M1", group="M1@1", chosen="evt-9", note="Held correctly")
    assert review.type == "CONFLICT_RESOLVED" and review.payload["note"] == "Held correctly"


def test_actions_over_http(tmp_path):
    actions, store = site(tmp_path, "carehome")
    app = FastAPI()
    app.include_router(make_router("carehome", store, actions=actions))
    client = TestClient(app)
    ok = client.post("/api/actions/give_dose", json={"resident_id": "R1", "rx_id": "M1", "slot": 240})
    assert ok.status_code == 200 and ok.json()["event"]["type"] == "DOSE_GIVEN"
    assert client.post("/api/actions/change_dose", json={"resident_id": "R1", "rx_id": "M1",
                       "dose": "3mg", "seen_version": 1}).status_code == 403
    assert client.post("/api/actions/give_dose", json={"resident_id": "R1"}).status_code == 422
    assert client.post("/api/actions/launch_rocket", json={}).status_code == 404