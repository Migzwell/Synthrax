"""R5: low stock -> repeat request.

Fires (INFO) when Rx.stock covers fewer than 7 days and no request is
open or approved for that medicine. Same for every risk group. PRN
medicines have no stock maths.

The rule never sends anything. When staff confirm, the UI creates a
REPEAT_REQUESTED event with draft_repeat(rx) as its payload (queued in
the outbox if offline).
"""
from core.rules.common import active_rxs
from core.types import Flag, NodeState, Rx, SyncState

MIN_DAYS = 7
CYCLE_DAYS = 28

MSG_LOW = ('{drug}: about {days} days of stock left ({stock} doses). '
           'A repeat request has been drafted. Check and confirm to send.')


def days_left(rx: Rx) -> float:
    return rx.stock / len(rx.times)


def has_open_request(state: NodeState, rx: Rx) -> bool:
    waiting = list(state.open_requests.values()) + list(state.approved_requests.values())
    return any(e.rx_id == rx.id for e in waiting)


def draft_repeat(rx: Rx) -> dict:
    """Payload for the REPEAT_REQUESTED event staff confirm."""
    return {'qty': CYCLE_DAYS * len(rx.times), 'auto_drafted': True}


def check(state: NodeState, now: int, sync: SyncState) -> list[Flag]:
    flags = []
    for rx in active_rxs(state):
        if rx.prn:
            continue
        if days_left(rx) >= MIN_DAYS or has_open_request(state, rx):
            continue
        flags.append(Flag(
            rule='R5',
            rx_id=rx.id,
            resident_id=rx.resident_id,
            action='INFO',
            message=MSG_LOW.format(drug=rx.drug, days=int(days_left(rx)), stock=rx.stock),
        ))
    return flags
