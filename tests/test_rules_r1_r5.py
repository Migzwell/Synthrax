"""Safety rules R1-R5, both risk groups."""
from core.rules import blocking_flag, evaluate, r1, r2, r3, r4, r5
from core.schedule import at, hhmm, next_round
from core.types import SyncState
from tests.factories import (COCARELDOPA, FUROSEMIDE, LAST_SYNC, SIX_PM, WARFARIN,
                             demo_state, ev, offline, online)


def by_rx(flags, rx_id):
    return [f for f in flags if f.rx_id == rx_id]


# --- schedule ---------------------------------------------------------------

def test_demo_clock_conversion():
    assert SIX_PM == 240                      # matches core/types.py: minute = t_hours * 60 + 240
    assert (at(14), at(8), at(8, day=1)) == (0, -360, 1080)
    assert (hhmm(240), hhmm(-360), hhmm(0)) == ('18:00', '08:00', '14:00')
    assert next_round(at(16)) == SIX_PM
    assert next_round(at(23)) == at(8, day=1)


# --- R1: outstanding instruction --------------------------------------------

def test_r1_holds_margarets_warfarin_when_offline():
    (flag,) = by_rx(r1.check(demo_state(), SIX_PM, offline()), WARFARIN)
    assert flag.action == 'HOLD'
    assert 'INR taken at 08:00' in flag.message
    assert 'before giving' in flag.message


def test_r1_gives_arthurs_cocareldopa_and_escalates():
    (flag,) = by_rx(r1.check(demo_state(), SIX_PM, offline()), COCARELDOPA)
    assert flag.action == 'GIVE_AND_ESCALATE'
    assert 'must not be missed' in flag.message


def test_r1_never_blocks_a_never_omit_medicine():
    flags = evaluate(demo_state(), SIX_PM, offline())
    assert blocking_flag(flags, WARFARIN) is not None
    assert blocking_flag(flags, COCARELDOPA) is None


def test_r1_silent_when_online_and_synced_since_the_observation():
    assert r1.check(demo_state(), SIX_PM, online()) == []


def test_r1_fires_when_online_but_no_sync_since_the_observation():
    sync = SyncState(online=True, last_seen={'gp': at(7)})   # before the 8am INR
    assert by_rx(r1.check(demo_state(), SIX_PM, sync), WARFARIN)


def test_r1_accepts_lowercase_observation_kind():
    """Ethan's test cases write "INR_taken"."""
    state = demo_state()
    for e in state.events:
        if e.payload.get('kind') == 'INR_TAKEN':
            e.payload['kind'] = 'INR_taken'
    assert by_rx(r1.check(state, SIX_PM, offline()), WARFARIN)


def test_r1_cleared_by_rx_confirmed():
    """A normal INR ("result reviewed, no change") must not hold warfarin forever."""
    confirmed = ev('RX_CONFIRMED', WARFARIN, at(15), author='gp', reason='INR 2.6, in range')
    assert by_rx(r1.check(demo_state([confirmed]), SIX_PM, offline()), WARFARIN) == []


def test_r1_cleared_by_rx_changed():
    changed = ev('RX_CHANGED', WARFARIN, at(15), author='gp', seen_version=1, dose='3mg')
    assert by_rx(r1.check(demo_state([changed]), SIX_PM, offline()), WARFARIN) == []


def test_r1_only_fires_when_a_dose_is_due():
    assert r1.check(demo_state(), at(14), offline()) == []


def test_r1_stops_once_the_dose_is_recorded():
    withheld = ev('DOSE_WITHHELD', WARFARIN, SIX_PM + 5, slot=SIX_PM, reason='safety hold')
    assert by_rx(r1.check(demo_state([withheld]), SIX_PM + 10, offline()), WARFARIN) == []


def test_r1_ignores_standard_and_stopped_medicines():
    obs = ev('OBSERVATION', FUROSEMIDE, at(7, day=1), kind='GP_VISIT')
    state = demo_state([obs])
    state.rx[WARFARIN].stopped = True
    flags = r1.check(state, at(8, day=1), offline())
    assert by_rx(flags, FUROSEMIDE) == [] and by_rx(flags, WARFARIN) == []


# --- R2: stale high-risk record ---------------------------------------------

def test_r2_silent_within_24h():
    assert r2.check(demo_state(), SIX_PM, offline()) == []


def test_r2_after_24h_warns_with_wording_by_risk_group():
    flags = r2.check(demo_state(), LAST_SYNC + 25 * 60, offline())
    (warfarin,) = by_rx(flags, WARFARIN)
    (cocareldopa,) = by_rx(flags, COCARELDOPA)
    assert warfarin.action == cocareldopa.action == 'WARN'
    assert 'second member of staff must sign' in warfarin.message
    assert 'Give on time' in cocareldopa.message
    assert by_rx(flags, FUROSEMIDE) == []          # standard medicines are not flagged


def test_r2_never_synced_counts_as_stale():
    flags = r2.check(demo_state(), SIX_PM, SyncState(online=True, last_seen={}))
    assert len(flags) == 2


# --- R3: pack/record mismatch -----------------------------------------------

def scan(rx_id, version, pack_resident):
    return ev('OBSERVATION', rx_id, SIX_PM, kind='PACK_SCANNED',
              version=version, pack_resident=pack_resident)


def test_r3_newer_pack_holds_warfarin():
    (flag,) = r3.check(demo_state([scan(WARFARIN, 2, 'margaret')]), SIX_PM, offline())
    assert flag.action == 'HOLD'
    assert "a change exists you haven't received" in flag.message


def test_r3_newer_pack_gives_never_omit_and_escalates():
    (flag,) = r3.check(demo_state([scan(COCARELDOPA, 2, 'arthur')]), SIX_PM, offline())
    assert flag.action == 'GIVE_AND_ESCALATE'


def test_r3_older_pack_says_dont_use():
    state = demo_state([scan(WARFARIN, 1, 'margaret')])
    state.rx[WARFARIN].version = 2
    (flag,) = r3.check(state, SIX_PM, online())
    assert flag.action == 'HOLD' and "don't use this pack" in flag.message


def test_r3_wrong_residents_pack():
    (flag,) = r3.check(demo_state([scan(WARFARIN, 1, 'arthur')]), SIX_PM, online())
    assert flag.action == 'HOLD' and 'another resident' in flag.message
    (flag,) = r3.check(demo_state([scan(COCARELDOPA, 1, 'margaret')]), SIX_PM, online())
    assert flag.action == 'GIVE_AND_ESCALATE' and 'correct pack' in flag.message


def test_r3_matching_pack_is_silent():
    assert r3.check(demo_state([scan(WARFARIN, 1, 'margaret')]), SIX_PM, offline()) == []


# --- R4: late time-critical dose --------------------------------------------

def test_r4_silent_at_30_minutes():
    assert r4.check(demo_state(), SIX_PM + 30, online(SIX_PM + 30)) == []


def test_r4_warns_after_30_minutes():
    (flag,) = r4.check(demo_state(), SIX_PM + 31, online(SIX_PM + 31))
    assert (flag.rx_id, flag.action) == (COCARELDOPA, 'WARN')
    assert 'due at 18:00 is 31 min late' in flag.message


def test_r4_silent_once_given_and_never_for_warfarin():
    given = ev('DOSE_GIVEN', COCARELDOPA, SIX_PM + 10, slot=SIX_PM, given_at=SIX_PM + 10)
    assert r4.check(demo_state([given]), SIX_PM + 45, online(SIX_PM + 45)) == []


# --- R5: low stock -> repeat request ----------------------------------------

def test_r5_flags_under_7_days_and_drafts_a_28_day_repeat():
    state = demo_state()
    state.rx[COCARELDOPA].stock = 20               # 4 a day = 5 days
    (flag,) = r5.check(state, SIX_PM, offline())
    assert (flag.rx_id, flag.action) == (COCARELDOPA, 'INFO')
    assert r5.draft_repeat(state.rx[COCARELDOPA]) == {'qty': 112, 'auto_drafted': True}


def test_r5_silent_with_7_days_or_more():
    state = demo_state()
    state.rx[FUROSEMIDE].stock = 7
    assert r5.check(state, SIX_PM, offline()) == []


def test_r5_silent_while_a_request_is_open_or_approved():
    request = ev('REPEAT_REQUESTED', FUROSEMIDE, at(13), qty=28, auto_drafted=True)
    for field in ('open_requests', 'approved_requests'):
        state = demo_state()
        state.rx[FUROSEMIDE].stock = 3
        getattr(state, field)[request.id] = request
        assert r5.check(state, SIX_PM, offline()) == []


def test_r5_skips_prn_medicines():
    state = demo_state()
    state.rx[FUROSEMIDE].times = []
    state.rx[FUROSEMIDE].stock = 0
    assert r5.check(state, SIX_PM, offline()) == []


# --- evaluate() -------------------------------------------------------------

def test_evaluate_demo_moment_most_severe_first():
    flags = evaluate(demo_state(), SIX_PM, offline())
    assert [(f.rule, f.rx_id, f.action) for f in flags] == [
        ('R1', WARFARIN, 'HOLD'),
        ('R1', COCARELDOPA, 'GIVE_AND_ESCALATE'),
    ]


def test_evaluate_all_green_when_online():
    assert evaluate(demo_state(), at(16), online(at(16))) == []


def test_evaluate_runs_no_carehome_rules_on_other_nodes():
    assert evaluate(demo_state(), SIX_PM, offline(), node='gp') == []
