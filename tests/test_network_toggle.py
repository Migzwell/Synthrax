"""Network switch: an offline site works alone and catches up when it reconnects."""
import asyncio

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.types import Event
from node.api import make_router
from node.store import EventStore
from node.sync import Sync

URLS = {"carehome": "http://carehome", "gp": "http://gp", "pharmacy": "http://pharmacy"}


class Sites(httpx.AsyncBaseTransport):
    """In-memory sites routed by host name; each site's API uses its own sync state."""

    def __init__(self, apps: dict[str, FastAPI]):
        self.transports = {name: httpx.ASGITransport(app=app) for name, app in apps.items()}

    async def handle_async_request(self, request):
        return await self.transports[request.url.host].handle_async_request(request)


def event(id: str, author: str = "gp") -> Event:
    return Event(id=id, resident_id="R1", rx_id="M1", type="RX_CHANGED", author=author,
                 created_at=0, seen_version=1, payload={"dose": "3mg"})


def setup(tmp_path, clock=lambda: 240):
    stores = {n: EventStore(tmp_path / f"{n}.db") for n in URLS}
    syncs, apps = {}, {}
    for n in URLS:
        syncs[n] = Sync(n, stores[n], {p: URLS[p] for p in URLS if p != n}, now=clock)
        apps[n] = FastAPI()
        apps[n].include_router(make_router(n, stores[n], syncs[n].state, now=clock))
    client = httpx.AsyncClient(transport=Sites(apps))
    for s in syncs.values():
        s._client = client
    return stores, syncs, apps


def run(coro):
    return asyncio.run(coro)


def ids(store):
    return [e.id for e in store.all()]


def test_offline_site_does_not_pull(tmp_path):
    stores, syncs, _ = setup(tmp_path)
    syncs["carehome"].state.online = False
    stores["gp"].add(event("change-1"))
    assert run(syncs["carehome"].pull_once()) == 0
    assert ids(stores["carehome"]) == []


def test_others_get_503_and_it_does_not_count_as_contact(tmp_path):
    stores, syncs, apps = setup(tmp_path)
    syncs["carehome"].state.online = False
    assert TestClient(apps["carehome"]).get("/api/events").status_code == 503
    run(syncs["gp"].pull_once())
    assert "carehome" not in syncs["gp"].state.last_seen
    assert syncs["gp"].state.last_seen["pharmacy"] == 240


def test_offline_site_records_locally_and_syncs_after_reconnect(tmp_path):
    stores, syncs, apps = setup(tmp_path)
    syncs["carehome"].state.online = False
    TestClient(apps["carehome"]).post("/api/events", json=event("dose-held", author="carehome").model_dump())
    run(syncs["gp"].pull_once())
    assert ids(stores["gp"]) == []                     # nothing leaks out while offline
    syncs["carehome"].state.online = True
    run(syncs["gp"].pull_once())
    assert ids(stores["gp"]) == ["dose-held"]


def test_status_shows_offline_and_frozen_last_contact(tmp_path):
    times = iter([240, 600])
    stores, syncs, apps = setup(tmp_path, clock=lambda: next(times, 600))
    run(syncs["carehome"].pull_once())                 # contact at 240 (and 600 for the second peer)
    first = dict(syncs["carehome"].state.last_seen)
    syncs["carehome"].state.online = False
    run(syncs["carehome"].pull_once())
    status = TestClient(apps["carehome"]).get("/api/status").json()
    assert status["online"] is False
    assert status["last_seen"] == first                # frozen while offline


def test_switch_endpoint(tmp_path):
    _, syncs, apps = setup(tmp_path)
    client = TestClient(apps["carehome"])
    assert client.post("/api/online/false").json()["online"] is False
    assert syncs["carehome"].state.online is False
    assert client.post("/api/online/true").json()["online"] is True


def test_partition(tmp_path):
    """Cut the care home, change a dose at the GP: not received. Reconnect: received exactly once."""
    stores, syncs, apps = setup(tmp_path)
    TestClient(apps["carehome"]).post("/api/online/false")
    stores["gp"].add(event("warfarin-3mg"))
    for _ in range(3):
        for s in syncs.values():
            run(s.pull_once())
    assert ids(stores["carehome"]) == []
    assert ids(stores["pharmacy"]) == ["warfarin-3mg"]  # the pharmacy, still online, gets it
    TestClient(apps["carehome"]).post("/api/online/true")
    for _ in range(2):
        run(syncs["carehome"].pull_once())
    assert ids(stores["carehome"]) == ["warfarin-3mg"]