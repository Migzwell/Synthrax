"""evaluate() + which node shows which rule.

Every rule is a pure function (state, now, sync) -> list[Flag].
No LLM, no network, no real clock: `now` comes from the demo clock.
Call evaluate() after every new event and every clock tick.
"""
from typing import Optional

from core.rules import r1, r2, r3, r4, r5
from core.types import SEVERITY, Flag, NodeState, SyncState

# R6 (pharmacy), R7 (GP) and R8 (care home) plug in here when written.
RULES_BY_NODE = {
    'carehome': [r1.check, r2.check, r3.check, r4.check, r5.check],
    'gp': [],
    'pharmacy': [],
}


def evaluate(state: NodeState, now: int, sync: SyncState, node: str = 'carehome') -> list[Flag]:
    """Run one node's rules. Most severe flags first."""
    flags: list[Flag] = []
    for rule in RULES_BY_NODE.get(node, []):
        flags.extend(rule(state, now, sync))
    return sorted(flags, key=lambda f: (-SEVERITY[f.action], f.rule, f.rx_id or ''))


def blocking_flag(flags: list[Flag], rx_id: str) -> Optional[Flag]:
    """The flag that stops this medicine being given right now, if any.

    Only HOLD and BLOCK stop a dose. Never-omit medicines never get either
    from R1-R5, by design: holding them is itself the harm.
    """
    for f in flags:
        if f.rx_id == rx_id and f.action in ('HOLD', 'BLOCK'):
            return f
    return None
