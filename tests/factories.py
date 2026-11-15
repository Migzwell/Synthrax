"""Hand-built states for rule and agent tests (no store, no derive needed).

Demo-clock minute 0 = 14:00 on demo day, so 18:00 is 240 (see core/types.py).
"""
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
    Doris (furosemide, standard), each with plenty of stock."""
    residents = {
        'margaret': Resident(id='margaret', name='Margaret Hughes', age=87, room='4'),
        'arthur': Resident(id='arthur', name='Arthur Bell', age=81, room='7'),
        'doris': Resident(id='doris', name='Doris Patel', age=92, room='2'),
    }
    rx = {
        WARFARIN: Rx(id=WARFARIN, resident_id='margaret', drug='Warfarin', dose='5mg',
                     times=['18:00'], risk_group='hold_and_confirm', stock=28),
        COCARELDOPA: Rx(id=COCARELDOPA, resident_id='arthur', drug='Co-careldopa',
                        dose='25/100', times=['08:00', '12:00', '18:00', '22:00'],
                        risk_group='never_omit', stock=112),
        FUROSEMIDE: Rx(id=FUROSEMIDE, resident_id='doris', drug='Furosemide', dose='40mg',
                       times=['08:00'], risk_group='standard', stock=28),
    }
    events = [
        # Arthur: GP visit yesterday, GP to advise
        ev('OBSERVATION', COCARELDOPA, at(15, day=-1), resident_id='arthur', kind='GP_VISIT'),
        # Margaret: INR taken yesterday at 10:00 (32h before the round, as in the demo story)
        ev('OBSERVATION', WARFARIN, at(10, day=-1), resident_id='margaret', kind='INR_TAKEN'),
        # Arthur's earlier doses today were given on time
        ev('DOSE_GIVEN', COCARELDOPA, at(8), resident_id='arthur', slot=at(8), given_at=at(8)),
        ev('DOSE_GIVEN', COCARELDOPA, at(12), resident_id='arthur', slot=at(12), given_at=at(12)),
        # Doris's morning dose
        ev('DOSE_GIVEN', FUROSEMIDE, at(8), resident_id='doris', slot=at(8), given_at=at(8)),
        *extra_events,
    ]
    return NodeState(residents=residents, rx=rx, events=events)


SIX_PM = at(18)                # 240
LAST_SYNC = at(16)             # home synced until the network was cut at 4pm


def offline():
    return SyncState(online=False, last_seen={'gp': LAST_SYNC, 'pharmacy': LAST_SYNC})


def online(now=SIX_PM):
    return SyncState(online=True, last_seen={'gp': now, 'pharmacy': now})