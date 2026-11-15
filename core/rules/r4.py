"""R4: late time-critical dose.

Fires (WARN) for a never-omit dose today that is more than 30 minutes late:
either not recorded by its time + 30 min ("not recorded"), or given more than
30 min after its time ("given late"). A late-but-given dose replaces its
"not recorded" warning rather than adding a second one.
Not applicable to hold-and-confirm, standard or PRN medicines.
"""
from typing import Optional

from core.rules.common import active_rxs
from core.schedule import DAY, ORIGIN, RECORD_EARLY, LOOKBACK, hhmm, slots_between
from core.types import Event, Flag, NodeState, SyncState

LATE_AFTER = 30

MSG_LATE = ('{drug} due at {when} is {late} min late and not recorded. '
            'This medicine must not be missed: give it now and record it.')
MSG_GIVEN_LATE = ('{drug} due at {when} was given {late} min late (limit 30 min). '
                  'Tell the senior carer and note it for review.')


def start_of_day(now: int) -> int:
    return ((now + ORIGIN) // DAY) * DAY - ORIGIN


def record_for(rx, slot: int, events: list[Event]) -> Optional[Event]:
    """The DOSE_GIVEN or DOSE_WITHHELD for this slot, if any."""
    for e in events:
        if e.rx_id != rx.id or e.type not in ('DOSE_GIVEN', 'DOSE_WITHHELD'):
            continue
        if e.payload.get('slot') is not None:
            if e.payload['slot'] == slot:
                return e
            continue
        when = e.payload.get('given_at', e.created_at)
        if slot - RECORD_EARLY <= when <= slot + LOOKBACK:
            return e
    return None


def check(state: NodeState, now: int, sync: SyncState) -> list[Flag]:
    flags = []
    for rx in active_rxs(state):
        if rx.risk_group != 'never_omit':
            continue
        for slot in slots_between(rx, start_of_day(now), now):
            record = record_for(rx, slot, state.events)
            if record is None:
                if now - slot > LATE_AFTER:
                    msg = MSG_LATE.format(drug=rx.drug, when=hhmm(slot), late=now - slot)
                else:
                    continue
            elif record.type == 'DOSE_GIVEN' and record.payload.get('given_at', record.created_at) - slot > LATE_AFTER:
                late = record.payload.get('given_at', record.created_at) - slot
                msg = MSG_GIVEN_LATE.format(drug=rx.drug, when=hhmm(slot), late=late)
            else:
                continue
            flags.append(Flag(rule='R4', rx_id=rx.id, resident_id=rx.resident_id, action='WARN', message=msg))
    return flags