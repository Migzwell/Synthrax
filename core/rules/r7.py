"""R7: unacknowledged change.

GP only. Fires (WARN) when a dose change has not been acknowledged by the care
home 2 hours or more after the GP made it: "Did they get my message?"
"""
from core.types import Flag, NodeState, SyncState

LIMIT = 2 * 60

MSG = "{drug} dose change not acknowledged by the care home after {h}h {m}m. Phone the home."


def check(state: NodeState, now: int, sync: SyncState) -> list[Flag]:
    flags = []
    for rx in state.rx.values():
        if rx.version <= rx.acked_version or rx.last_changed_at is None:
            continue
        waited = now - rx.last_changed_at
        if waited >= LIMIT:
            flags.append(Flag(rule="R7", rx_id=rx.id, resident_id=rx.resident_id, action="WARN",
                              message=MSG.format(drug=rx.drug, h=waited // 60, m=waited % 60)))
    return flags