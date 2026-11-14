"""R4: late time-critical dose.

Fires (WARN) when a never-omit dose has not been recorded within 30
minutes of its scheduled time. The message says how late it is.
Not applicable to hold-and-confirm, standard or PRN medicines.
"""
from core.rules.common import active_rxs
from core.schedule import LOOKBACK, hhmm, is_recorded, slots_between
from core.types import Flag, NodeState, SyncState

LATE_AFTER = 30

MSG_LATE = ('{drug} due at {when} is {late} min late and not recorded. '
            'This medicine must not be missed: give it now and record it.')


def minutes_late(state: NodeState, rx, now: int) -> int:
    """Minutes since the oldest unrecorded slot that is over 30 min late, or 0."""
    for slot in slots_between(rx, now - LOOKBACK, now - LATE_AFTER - 1):
        if not is_recorded(rx, slot, state.events):
            return now - slot
    return 0


def check(state: NodeState, now: int, sync: SyncState) -> list[Flag]:
    flags = []
    for rx in active_rxs(state):
        if rx.risk_group != 'never_omit':
            continue
        late = minutes_late(state, rx, now)
        if not late:
            continue
        flags.append(Flag(
            rule='R4',
            rx_id=rx.id,
            resident_id=rx.resident_id,
            action='WARN',
            message=MSG_LATE.format(drug=rx.drug, when=hhmm(now - late), late=late),
        ))
    return flags
