"""Endpoints other sites and the screens call."""
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException

from core.types import Event, SyncState
from .store import EventStore


def make_router(node_id: str, store: EventStore, state: Optional[SyncState] = None,
                now: Optional[Callable[[], int]] = None) -> APIRouter:
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

    return router