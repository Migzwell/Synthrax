"""Small helpers shared by the rules. Pure functions over NodeState."""
from core.types import Event, NodeState, Rx

PRESCRIBER = 'gp'


def active_rxs(state: NodeState) -> list[Rx]:
    return [rx for rx in state.rx.values() if not rx.stopped]


def events_for(state: NodeState, rx_id: str, *types: str) -> list[Event]:
    """Events for one medicine, optionally filtered by type, oldest first."""
    found = [e for e in state.events if e.rx_id == rx_id and (not types or e.type in types)]
    return sorted(found, key=lambda e: (e.created_at, e.lamport))


def observations(state: NodeState, rx_id: str, *kinds: str) -> list[Event]:
    """OBSERVATION events of the given kinds (case-insensitive), oldest first."""
    return [e for e in events_for(state, rx_id, 'OBSERVATION')
            if str(e.payload.get('kind', '')).upper() in kinds]
