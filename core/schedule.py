"""Dose times <-> demo-clock minutes, next round.

Demo-clock minute 0 = 14:00 on demo day (see core/types.py), so 18:00 on
demo day is 240 and 08:00 that morning is -360. A "slot" is one scheduled
dose as a demo-clock minute. Rx.times holds clock strings such as "18:00".
Pure functions only.
"""
from typing import Optional

from core.types import Event, Rx

DAY = 24 * 60
ORIGIN = 14 * 60    # demo minute 0 is 14:00
DUE_EARLY = 30      # a dose counts as due from 30 min before its time
LOOKBACK = 180      # ...and stays on the round for 3h after it
RECORD_EARLY = 60   # a dose recorded up to 1h early still counts for the slot

ROUNDS = ['08:00', '12:00', '18:00', '22:00']


def minute_of_day(clock: str) -> int:
    """'18:00' -> 1080."""
    hours, _, minutes = str(clock).strip().partition(':')
    return int(hours) * 60 + int(minutes or 0)


def at(hour: int, minute: int = 0, day: int = 0) -> int:
    """Demo-clock minute for a clock time. at(18) -> 240; at(8) -> -360; day=-1 is yesterday."""
    return day * DAY + hour * 60 + minute - ORIGIN


def hhmm(minute: int) -> str:
    """Demo-clock minute -> '18:00'."""
    m = (minute + ORIGIN) % DAY
    return f'{m // 60:02d}:{m % 60:02d}'


def _slots(times: list[str], start: int, end: int) -> list[int]:
    slots = []
    for day in range((start + ORIGIN) // DAY, (end + ORIGIN) // DAY + 1):
        for t in times:
            slot = day * DAY + minute_of_day(t) - ORIGIN
            if start <= slot <= end:
                slots.append(slot)
    return sorted(slots)


def next_round(now: int) -> int:
    """Demo-clock minute of the next med round strictly after now."""
    return _slots(ROUNDS, now + 1, now + DAY)[0]


def slots_between(rx: Rx, start: int, end: int) -> list[int]:
    """Scheduled slots for rx with start <= slot <= end, oldest first. PRN has none."""
    return [] if rx.prn else _slots(rx.times, start, end)


def is_recorded(rx: Rx, slot: int, events: list[Event]) -> bool:
    """True if a DOSE_GIVEN or DOSE_WITHHELD exists for this slot.

    Uses payload['slot'] when set; otherwise matches on the event time.
    """
    for e in events:
        if e.rx_id != rx.id or e.type not in ('DOSE_GIVEN', 'DOSE_WITHHELD'):
            continue
        if e.payload.get('slot') is not None:
            if e.payload['slot'] == slot:
                return True
            continue
        when = e.payload.get('given_at', e.created_at)
        if slot - RECORD_EARLY <= when <= slot + LOOKBACK:
            return True
    return False


def due_slot(rx: Rx, now: int, events: list[Event]) -> Optional[int]:
    """The slot that is due now and not yet recorded, or None."""
    for slot in slots_between(rx, now - LOOKBACK, now + DUE_EARLY):
        if not is_recorded(rx, slot, events):
            return slot
    return None
