"""R2: stale high-risk record.

Fires when a medicine is in either high-risk group and the care home has
not synced with the prescriber for more than 24h. A node that has never
synced with the prescriber counts as stale.

Both groups get a WARN; the wording differs:
Hold-and-confirm -> second staff signature required.
Never-omit       -> give on time, logged for review.
"""
from core.risk_groups import is_high_risk
from core.rules.common import PRESCRIBER, active_rxs
from core.types import Flag, NodeState, SyncState

STALE_AFTER = 24 * 60

MSG_SECOND_SIG = ('{drug}: this record has not been checked against the prescriber '
                  'for {age}. A second member of staff must sign before giving.')
MSG_GIVE = ('{drug}: this record has not been checked against the prescriber '
            'for {age}. Give on time. Logged for review.')


def _age_text(now: int, last) -> str:
    if last is None:
        return 'an unknown time (never synced)'
    return f'{(now - last) // 60}h'


def check(state: NodeState, now: int, sync: SyncState) -> list[Flag]:
    last = sync.last_seen.get(PRESCRIBER)
    if last is not None and now - last <= STALE_AFTER:
        return []
    flags = []
    for rx in active_rxs(state):
        if not is_high_risk(rx.risk_group):
            continue
        msg = MSG_SECOND_SIG if rx.risk_group == 'hold_and_confirm' else MSG_GIVE
        flags.append(Flag(
            rule='R2',
            rx_id=rx.id,
            resident_id=rx.resident_id,
            action='WARN',
            message=msg.format(drug=rx.drug, age=_age_text(now, last)),
        ))
    return flags
