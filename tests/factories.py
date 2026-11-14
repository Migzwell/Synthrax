"""Hand-built states for rule and agent tests (no store, no derive needed)."""
import itertools

from core.schedule import at
from core.types import Event, NodeState, Resident, Rx, SyncState

_ids = itertools.count(1)

WARFARIN = 'rx-margaret-warfarin'
COCARELDOPA = 'rx-arthur-cocareldopa'
FUROSEMIDE = 'rx-doris-furosemide'


def ev(type, rx_id, when, resident_id='r', author='carehome', seen_version=None, **payload):
    n = next(_ids)
    return Event(id=f'e{n}', resident_id=resident_id, rx_id=rx_id, type=type,
                 payload=payload, author=author, created_at=when, lamport=n,
                 seen_version=seen_version)


def demo_state(extra_events=()):
    """Margaret (warfarin, hold and confirm), Arthur (co-careldopa, never omit),
    Doris (furosemide, standard), with the seeded observations from the plan."""
    residents = {
        'margaret': Resident(id='margaret', name='Margaret Hughes', age=87, room='4'),
        'arthur': Resident(id='arthur', name='Arthur Bell', age=81, room='7'),
        'doris': Resident(id='doris', name='Doris Patel', age=92, room='2'),
    }
    rxs = {
        WARFARIN: Rx(id=WARFARIN, resident_id='margaret', drug='Warfarin', dose='5mg',
                     times=[at(18)], risk_group='hold_and_confirm'),
        COCARELDOPA: Rx(id=COCARELDOPA, resident_id='arthur', drug='Co-careldopa',
                        dose='25/100', times=[at(8), at(12), at(18), at(22)],
                        risk_group='never_omit'),
        FUROSEMIDE: Rx(id=FUROSEMIDE, resident_id='doris', drug='Furosemide', dose='40mg',
                       times=[at(8)], risk_group='standard'),
    }
    day = 1   # "today" is day 1 so "yesterday" exists
    events = [
        # Arthur: GP visit yesterday, GP to advise
        ev('OBSERVATION', COCARELDOPA, at(15, day=0), resident_id='arthur', kind='gp_visit'),
        # Margaret: INR taken this morning
        ev('OBSERVATION', WARFARIN, at(8, day=day), resident_id='margaret', kind='inr_taken'),
        # Arthur's earlier doses today were given on time
        ev('DOSE_GIVEN', COCARELDOPA, at(8, day=day), resident_id='arthur'),
        ev('DOSE_GIVEN', COCARELDOPA, at(12, day=day), resident_id='arthur'),
        # Doris's morning dose
        ev('DOSE_GIVEN', FUROSEMIDE, at(8, day=day), resident_id='doris'),
        *extra_events,
    ]
    return NodeState(node='carehome', residents=residents, rxs=rxs, events=events)


SIX_PM = at(18, day=1)
LAST_SYNC = at(16, day=1)      # home synced until the network was cut at 4pm


def offline():
    return SyncState(online=False, last_seen={'gp': LAST_SYNC, 'pharmacy': LAST_SYNC})


def online(now=SIX_PM):
    return SyncState(online=True, last_seen={'gp': now, 'pharmacy': now})