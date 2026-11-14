"""Derive: the event log becomes current doses, versions, stock and requests."""
# Self-contained: builds its own events, so it doesn't depend on the seed file or the seed loader.
from core.derive import derive
from core.rules import blocking_flag, evaluate
from core.types import Event, Resident, SyncState

PEOPLE = [Resident(id="R1", name="Margaret Hughes", age=87, room="4"),
          Resident(id="R2", name="Arthur Bell", age=81, room="7"),
          Resident(id="R3", name="Doris Patel", age=92, room="2")]


def ev(id, type, at, rx="M1", author="gp", seen=None, resident="R1", **payload):
    return Event(id=id, resident_id=resident, rx_id=rx, type=type, author=author,
                 created_at=at, lamport=100, seen_version=seen, payload=payload)


def prescribe(rx, resident, drug, dose, times, stock):
    """A new medicine plus its opening stock."""
    return [ev(f"{rx}-new", "RX_CREATED", -43200, rx=rx, resident=resident, drug=drug, dose=dose, times=times),
            ev(f"{rx}-stock", "DISPENSED", -43200, rx=rx, resident=resident, author="pharmacy",
               version=1, qty=stock)]


START = [
    *prescribe("M1", "R1", "Warfarin", "5mg", ["18:00"], 20),
    *prescribe("M3", "R1", "Paracetamol", "1g", [], 30),                                   # when required
    *prescribe("M4", "R2", "Co-careldopa", "1 tablet", ["08:00", "12:00", "16:00", "20:00"], 22),
    *prescribe("M6", "R3", "Furosemide", "40mg", ["08:00"], 10),
    ev("inr", "OBSERVATION", -1680, author="carehome", kind="INR_TAKEN"),                   # 10:00 yesterday
]


def state(*extra):
    return derive(START + list(extra), PEOPLE)


# ---------- medicines ----------

def test_risk_groups_and_prn():
    s = state()
    assert s.rx["M1"].risk_group == "hold_and_confirm"      # warfarin
    assert s.rx["M4"].risk_group == "never_omit"            # co-careldopa
    assert s.rx["M6"].risk_group == "standard"              # furosemide
    assert s.rx["M3"].prn and not s.rx["M1"].prn            # paracetamol is when-required


def test_residents_are_kept_and_unknown_ones_added_by_id():
    s = derive(START, PEOPLE[:1])
    assert s.residents["R1"].name == "Margaret Hughes"
    assert s.residents["R2"].name == "R2"                   # not passed in: listed by id


# ---------- prescription changes ----------

def test_gp_change_makes_version_2():
    rx = state(ev("chg", "RX_CHANGED", 0, seen=1, dose="3mg")).rx["M1"]
    assert (rx.dose, rx.version, rx.last_changed_at) == ("3mg", 2, 0)


def test_concurrent_changes_keep_the_first_and_leave_the_second_for_review():
    first = ev("a", "RX_CHANGED", 0, seen=1, dose="3mg")
    second = ev("b", "RX_CHANGED", 30, seen=1, dose="4mg")
    rx = state(first, second).rx["M1"]
    assert (rx.dose, rx.version) == ("3mg", 2)              # never silently overwritten


def test_acknowledge_and_stop():
    s = state(ev("chg", "RX_CHANGED", 0, seen=1, dose="3mg"),
              ev("ack", "RX_ACKNOWLEDGED", 60, author="carehome", version=2))
    assert s.rx["M1"].acked_version == 2
    stopped = state(ev("stop", "RX_STOPPED", 0, rx="M6", resident="R3")).rx["M6"]
    assert stopped.stopped and stopped.version == 2


# ---------- stock ----------

def test_opening_stock_then_doses_count_down():
    dose = ev("dose", "DOSE_GIVEN", -1200, author="carehome", slot=-1200, given_at=-1200)
    assert state().rx["M1"].stock == 20
    assert state(dose).rx["M1"].stock == 19


def test_stock_count_replaces_the_estimate_then_doses_count_down():
    count = ev("count", "OBSERVATION", 0, rx="M6", resident="R3", author="carehome", kind="STOCK_COUNT", stock_doses=3)
    dose = ev("dose", "DOSE_GIVEN", 60, rx="M6", resident="R3", author="carehome", slot=60, given_at=60)
    assert state(count, dose).rx["M6"].stock == 2


def test_dispensing_adds_stock_and_new_version():
    pack = ev("pack", "DISPENSED", 60, author="pharmacy", version=2, qty=28)
    rx = state(ev("chg", "RX_CHANGED", 0, seen=1, dose="3mg"), pack).rx["M1"]
    assert rx.stock == 48 and rx.dispensed_version == 2


# ---------- repeat requests ----------

def test_request_open_then_approved_then_closed_by_dispensing():
    req = ev("req", "REPEAT_REQUESTED", 0, rx="M4", resident="R2", author="carehome", qty=112)
    ok = ev("ok", "REQUEST_APPROVED", 10, rx="M4", resident="R2", request="req")
    packed = ev("packed", "DISPENSED", 20, rx="M4", resident="R2", author="pharmacy", version=1, qty=112, request="req")
    assert list(state(req).open_requests) == ["req"]
    assert list(state(req, ok).approved_requests) == ["req"]
    done = state(req, ok, packed)
    assert done.open_requests == {} and done.rx["M4"].stock == 22 + 112


def test_rejected_request_is_closed():
    req = ev("req", "REPEAT_REQUESTED", 0, rx="M4", resident="R2", author="carehome", qty=112)
    no = ev("no", "REQUEST_REJECTED", 10, rx="M4", resident="R2", request="req")
    assert state(req, no).open_requests == {}


# ---------- the demo moment, with the team's rules ----------

def test_6pm_round_offline_holds_warfarin():
    offline = SyncState(online=False, last_seen={"gp": -120})          # cut off at 12:00
    flags = evaluate(state(), 240, offline)
    assert blocking_flag(flags, "M1").rule == "R1"                     # warfarin held
    assert blocking_flag(flags, "M4") is None                          # Arthur never held


def test_gp_change_reaching_the_home_clears_the_hold():
    online = SyncState(online=True, last_seen={"gp": 240})
    flags = evaluate(state(ev("chg", "RX_CHANGED", 0, seen=1, dose="3mg")), 240, online)
    assert blocking_flag(flags, "M1") is None


def test_arthurs_low_stock_drafts_a_repeat():
    flags = evaluate(state(), 240, SyncState(online=True, last_seen={"gp": 240}))
    assert [(f.rule, f.rx_id) for f in flags if f.rule == "R5"] == [("R5", "M4")]   # 22 doses = 5.5 days