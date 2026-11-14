"""Events -> doses, versions, stock, pending changes."""
from typing import Iterable, Optional, Union

from core.risk_groups import risk_group_for
from core.types import Event, NodeState, Resident, RiskGroup, Rx


def _risk_group(payload: dict) -> RiskGroup:
    group = risk_group_for(payload.get("drug", ""))
    if group == "standard":                         # fall back on the seed's own flags
        if payload.get("time_critical"):
            return "never_omit"
        if payload.get("high_risk"):
            return "hold_and_confirm"
    return group


def derive(events: Iterable[Event],
           residents: Optional[Union[dict[str, Resident], list[Resident]]] = None) -> NodeState:
    """Current state from the event log. Pass the residents (e.g. seed_loader.residents(seed))
    so screens can show names; without them, residents are listed by id only."""
    ordered = sorted(events, key=lambda e: (e.created_at, e.lamport, e.id))
    if isinstance(residents, list):
        residents = {r.id: r for r in residents}
    state = NodeState(residents=dict(residents or {}), events=ordered)

    proposals: dict[str, Event] = {}
    closed: set[str] = set()                        # proposal or request ids no longer open
    requests: dict[str, Event] = {}
    approved: set[str] = set()

    for e in ordered:
        p = e.payload
        rx = state.rx.get(e.rx_id) if e.rx_id else None
        if e.resident_id not in state.residents:
            state.residents[e.resident_id] = Resident(id=e.resident_id, name=e.resident_id, age=0, room="")

        if e.type == "RX_CREATED" and e.rx_id:
            state.rx[e.rx_id] = Rx(
                id=e.rx_id, resident_id=e.resident_id, drug=p.get("drug", e.rx_id),
                dose=p.get("dose", ""), times=list(p.get("times", [])), frequency=p.get("frequency"),
                version=1, risk_group=_risk_group(p))

        elif e.type == "RX_CHANGED" and rx:
            new_version = (e.seen_version if e.seen_version is not None else rx.version) + 1
            if new_version > rx.version:            # a concurrent second change is a conflict card
                rx.dose, rx.version, rx.last_changed_at = p.get("dose", rx.dose), new_version, e.created_at
            if p.get("resolves"):
                closed.add(p["resolves"])

        elif e.type == "RX_STOPPED" and rx:
            rx.stopped, rx.version, rx.last_changed_at = True, rx.version + 1, e.created_at

        elif e.type == "RX_ACKNOWLEDGED" and rx:
            rx.acked_version = max(rx.acked_version, int(p.get("version", rx.version)))

        elif e.type == "DISPENSED" and rx:
            rx.stock += int(p.get("qty", 0))
            rx.dispensed_version = max(rx.dispensed_version, int(p.get("version", rx.version)))
            if p.get("request"):
                closed.add(p["request"])

        elif e.type == "DOSE_GIVEN" and rx:
            rx.stock = max(0, rx.stock - 1)

        elif e.type == "OBSERVATION":
            kind = str(p.get("kind", "")).upper()
            if kind == "STOCK_COUNT" and rx and p.get("stock_doses") is not None:
                rx.stock = int(p["stock_doses"])
            elif kind == "LETTER_RECEIVED":
                state.unread_letters[e.resident_id] = e
            elif kind == "LETTER_READ":
                state.unread_letters.pop(e.resident_id, None)

        elif e.type == "REPEAT_REQUESTED":
            requests[e.id] = e
        elif e.type == "REQUEST_APPROVED" and p.get("request"):
            approved.add(p["request"])
        elif e.type == "REQUEST_REJECTED" and p.get("request"):
            closed.add(p["request"])

        elif e.type == "CHANGE_PROPOSED":
            proposals[e.id] = e
        elif e.type == "CONFLICT_RESOLVED" and p.get("group"):
            state.resolved_groups.add(p["group"])

    state.open_requests = {k: v for k, v in requests.items() if k not in closed}
    state.approved_requests = {k: v for k, v in state.open_requests.items() if k in approved}
    for pid, e in proposals.items():
        if pid not in closed and f"{e.rx_id}@{e.seen_version}" not in state.resolved_groups:
            state.pending[e.rx_id] = e
    return state