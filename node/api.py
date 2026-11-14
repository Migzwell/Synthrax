"""Endpoints other sites and the screens call."""
from typing import Any, Callable, Optional

from fastapi import APIRouter, Body, HTTPException

from core.types import Event, SyncState
from .actions import ALLOWED, Actions
from .store import EventStore


def make_router(node_id: str, store: EventStore, state: Optional[SyncState] = None,
                now: Optional[Callable[[], int]] = None, actions: Optional[Actions] = None,
                seed: Optional[dict] = None) -> APIRouter:
    """`state` is the sync loop's SyncState, so the switch and the sync loop share one on/off flag.
    Without a state (as in the sync tests) the site is always online."""
    router = APIRouter()
    state = state or SyncState()

    @router.get("/api/events")
    def events_since(since: int = 0):
        """Peers ask: 'what do you have after position `since`?' We send every event we hold,
        not only our own, so events relay through whichever site is reachable."""
        if not state.online:
            raise HTTPException(status_code=503, detail=f"{node_id} is offline")
        events, max_seq = store.since(since)
        return {"node": node_id, "events": [e.model_dump() for e in events], "max_seq": max_seq}

    @router.post("/api/events")
    def add_event(event: Event):
        """The screens add a new event here, online or offline. Pydantic rejects anything malformed (422)."""
        return {"stored": store.add(event), "id": event.id}

    @router.get("/api/status")
    def status():
        """For the green/red light: online or not, and when each other site was last reached."""
        return {"node": node_id, "online": state.online, "last_seen": state.last_seen,
                "now": now() if now else None}

    @router.post("/api/online/{value}")
    def set_online(value: bool):
        """The network switch: /api/online/false cuts this site off, /api/online/true reconnects it."""
        state.online = value
        return {"node": node_id, "online": state.online}

    @router.get("/api/reference")
    def reference():
        """Residents and medications from seed_data.json, for the screens (names, aliases, risk flags)."""
        if seed is None:
            raise HTTPException(status_code=404, detail="No seed data loaded")
        return {"nodes": seed["nodes"], "residents": seed["residents"], "medications": seed["medications"]}

    @router.post("/api/actions/{action}")
    def do_action(action: str, fields: dict[str, Any] = Body(default={})):
        """Run an action by name, e.g. POST /api/actions/give_dose with
        {"resident_id": "R1", "rx_id": "M1", "slot": 240}. Works online or offline."""
        if actions is None or action not in ALLOWED:
            raise HTTPException(status_code=404, detail=f"Unknown action: {action}")
        try:
            event = getattr(actions, action)(**fields)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=422, detail=str(e))
        return {"stored": True, "event": event.model_dump()}

    return router
