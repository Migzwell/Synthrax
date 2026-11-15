"""R6 (pharmacy safety check) and R7 (unacknowledged change), on derived state."""
from core.derive import derive
from core.rules import evaluate
from core.types import Event, SyncState
from node.actions import Actions
from node.store import EventStore

ONLINE = SyncState(online=True, last_seen={"carehome": 0, "gp": 0, "pharmacy": 0})


def ev(id, type, at, rx, resident="R1", author="gp", seen=None, **payload):
    return Event(id=id, resident_id=resident, rx_id=rx, type=type, author=author,
                 created_at=at, lamport=100, seen_version=seen, payload=payload)


def prescribed(rx, drug, dose, times, resident="R1", frequency=None):
    return [ev(f"{rx}-new", "RX_CREATED", -43200, rx, resident, drug=drug, dose=dose, times=times, frequency=frequency),
            ev(f"{rx}-pack", "DISPENSED", -43200, rx, resident, author="pharmacy", version=1, qty=28)]


WARFARIN = prescribed("M1", "Warfarin", "5mg", ["18:00"])
SERTRALINE = prescribed("M7", "Sertraline", "50mg", ["08:00"], resident="R3")


def pharmacy_flags(events, now=0):
    return evaluate(derive(events), now, ONLINE, node="pharmacy")


def gp_flags(events, now):
    return evaluate(derive(events), now, ONLINE, node="gp")


#  R6

def test_new_ibuprofen_with_warfarin_is_blocked():
    ibuprofen = ev("M8-new", "RX_CREATED", 0, "M8", drug="Ibuprofen", dose="400mg", times=["08:00"])
    (flag,) = pharmacy_flags(WARFARIN + [ibuprofen])
    assert (flag.rule, flag.rx_id, flag.action) == ("R6", "M8", "BLOCK")
    assert "Bleeding" in flag.message and "Do not dispense" in flag.message


def test_sertraline_with_ibuprofen_needs_review():
    ibuprofen = ev("M9-new", "RX_CREATED", 0, "M9", resident="R3", drug="Ibuprofen", dose="400mg", times=["08:00"])
    (flag,) = pharmacy_flags(SERTRALINE + [ibuprofen])
    assert flag.action == "REVIEW"


def test_methotrexate_written_daily_is_blocked_weekly_is_fine():
    daily = ev("M10-new", "RX_CREATED", 0, "M10", drug="Methotrexate", dose="10mg", times=["08:00"], frequency="once daily")
    weekly = ev("M10-new", "RX_CREATED", 0, "M10", drug="Methotrexate", dose="10mg", times=["08:00"], frequency="once weekly")
    assert [f.action for f in pharmacy_flags([daily])] == ["BLOCK"]
    assert pharmacy_flags([weekly]) == []


def test_r6_only_checks_whats_waiting_to_be_dispensed_and_same_resident():
    other_resident = ev("M8-new", "RX_CREATED", 0, "M8", resident="R2", drug="Ibuprofen", dose="400mg", times=["08:00"])
    assert pharmacy_flags(WARFARIN + [other_resident]) == []              # Arthur's ibuprofen, Margaret's warfarin
    assert pharmacy_flags(WARFARIN) == []                                 # already dispensed: nothing waiting


def test_r6_runs_at_the_pharmacy_only():
    ibuprofen = ev("M8-new", "RX_CREATED", 0, "M8", drug="Ibuprofen", dose="400mg", times=["08:00"])
    assert evaluate(derive(WARFARIN + [ibuprofen]), 0, ONLINE, node="carehome") == []


CHANGE = ev("chg", "RX_CHANGED", 0, "M1", seen=1, dose="3mg")             # 14:00

# R7 
def test_r7_warns_the_gp_at_2_hours():
    assert gp_flags(WARFARIN + [CHANGE], now=119) == []
    (flag,) = gp_flags(WARFARIN + [CHANGE], now=120)                       # 16:00, demo story step 4
    assert (flag.rule, flag.rx_id, flag.action) == ("R7", "M1", "WARN")
    assert "not acknowledged by the care home after 2h 0m" in flag.message


def test_r7_cleared_by_acknowledgement():
    ack = ev("ack", "RX_ACKNOWLEDGED", 130, "M1", author="carehome", version=2)
    assert gp_flags(WARFARIN + [CHANGE, ack], now=240) == []

def test_gp_prescribes_a_new_medicine_that_needs_dispensing_and_acknowledging(tmp_path):
    store = EventStore(tmp_path / "gp.db")
    for e in WARFARIN:
        store.add(e)
    gp = Actions("gp", store, now=lambda: 0)
    new = gp.prescribe("R1", "Ibuprofen", "400mg", ["08:00"], "once daily")
    assert new.rx_id == "M2"
    rx = derive(store.all()).rx["M2"]
    assert (rx.version, rx.dispensed_version, rx.acked_version) == (1, 0, 0)
    assert [f.action for f in pharmacy_flags(store.all())] == ["BLOCK"]


def test_r6_flags_the_new_medicine_not_the_warfarin_change():
    change = ev("chg", "RX_CHANGED", 0, "M1", seen=1, dose="3mg")
    ibuprofen = ev("M8-new", "RX_CREATED", 0, "M8", drug="Ibuprofen", dose="400mg", times=["08:00"])
    flags = pharmacy_flags(WARFARIN + [change, ibuprofen])
    assert [(f.rx_id, f.action) for f in flags] == [("M8", "BLOCK")]      # warfarin 3mg can still be dispensed