"""R1: outstanding instruction.

"The node notices what it should have heard."

Fires when ALL of these hold for a medicine:
  1. an OBSERVATION that normally produces an instruction (INR taken, GP
     visit) has no later RX_CHANGED or RX_CONFIRMED;
  2. a dose of that medicine is due now;
  3. the care home has no contact with the prescriber (offline, or no sync
     since the observation).

Hold-and-confirm medicine -> HOLD.
Never-omit medicine       -> GIVE_AND_ESCALATE: give the last confirmed dose on time.
"""
from typing import Optional

from core.rules.common import PRESCRIBER, active_rxs, events_for, observations
from core.schedule import due_slot, hhmm
from core.types import Event, Flag, NodeState, Rx, SyncState

INSTRUCTION_KINDS = ('INR_TAKEN', 'GP_VISIT')
KIND_LABEL = {'INR_TAKEN': 'INR taken', 'GP_VISIT': 'GP visit'}

MSG_HOLD = ('HOLD {drug}. {what} at {when}, no dosing instruction received and '
            'no contact with the prescriber. Confirm the dose with the '
            'prescriber or NHS 111 before giving.')
MSG_GIVE = ('GIVE {drug} {dose} ON TIME. {what} at {when} and review outstanding, '
            'but this medicine must not be missed. Give the last confirmed dose, '
            'then confirm the dose with the prescriber or NHS 111 now.')


def outstanding_observation(state: NodeState, rx: Rx) -> Optional[Event]:
    """Latest instruction-producing observation with no prescriber answer after it."""
    found = observations(state, rx.id, *INSTRUCTION_KINDS)
    if not found:
        return None
    obs = found[-1]
    answers = events_for(state, rx.id, 'RX_CHANGED', 'RX_CONFIRMED')
    if any(a.created_at >= obs.created_at for a in answers):
        return None
    return obs


def no_prescriber_contact(sync: SyncState, since: int) -> bool:
    last = sync.last_seen.get(PRESCRIBER)
    return (not sync.online) or last is None or last < since


def check(state: NodeState, now: int, sync: SyncState) -> list[Flag]:
    flags = []
    for rx in active_rxs(state):
        if rx.risk_group == 'standard':
            continue                        # R1 only covers the two high-risk groups
        obs = outstanding_observation(state, rx)
        if obs is None:
            continue
        if due_slot(rx, now, state.events) is None:
            continue
        if not no_prescriber_contact(sync, obs.created_at):
            continue
        kind = str(obs.payload.get('kind', '')).upper()
        text = dict(drug=rx.drug, dose=rx.dose,
                    what=KIND_LABEL.get(kind, 'Review'), when=hhmm(obs.created_at))
        hold = rx.risk_group == 'hold_and_confirm'
        flags.append(Flag(
            rule='R1',
            rx_id=rx.id,
            resident_id=rx.resident_id,
            action='HOLD' if hold else 'GIVE_AND_ESCALATE',
            message=(MSG_HOLD if hold else MSG_GIVE).format(**text),
        ))
    return flags
