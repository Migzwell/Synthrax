"""Sync: events copy across, relay through a third site, and never duplicate."""
import asyncio

import httpx
from fastapi import FastAPI

from core.types import Event
from node.api import make_router
from node.store import EventStore
from node.sync import Sync

URLS = {"carehome": "http://carehome", "gp": "http://gp", "pharmacy": "http://pharmacy"}


class Sites(httpx.AsyncBaseTransport):
    """Routes requests to in-memory sites by host name, so tests need no real network.
    Hosts in `down` behave as unreachable."""

    def __init__(self, stores: dict[str, EventStore]):
        self.down: set[str] = set()
        self.apps = {}
        for name, store in stores.items():
            app = FastAPI()
            app.include_router(make_router(name, store))
            self.apps[name] = httpx.ASGITransport(app=app)

    async def handle_async_request(self, request):
        host = request.url.host
        if host in self.down:
            raise httpx.ConnectError("site unreachable", request=request)
        return await self.apps[host].handle_async_request(request)


def event(id: str, author: str = "gp") -> Event:
    return Event(id=id, resident_id="R1", rx_id="M1", type="RX_CHANGED", author=author,
                 created_at=0, seen_version=1, payload={"dose": "3mg"})


def setup(tmp_path, peers_for=None, clock=lambda: 240):
    stores = {n: EventStore(tmp_path / f"{n}.db") for n in URLS}
    sites = Sites(stores)
    client = httpx.AsyncClient(transport=sites)
    syncs = {}
    for n in URLS:
        peers = {p: URLS[p] for p in (peers_for or {}).get(n, [p for p in URLS if p != n])}
        syncs[n] = Sync(n, stores[n], peers, now=clock, client=client)
    return stores, syncs, sites


def run(coro):
    return asyncio.run(coro)


def test_event_copies_from_gp_to_carehome(tmp_path):
    stores, syncs, _ = setup(tmp_path)
    stores["gp"].add(event("change-1"))
    assert run(syncs["carehome"].pull_once()) == 1
    assert [e.id for e in stores["carehome"].all()] == ["change-1"]


def test_relays_through_a_third_site(tmp_path):
    # The care home can only reach the pharmacy; the pharmacy can reach the GP.
    stores, syncs, _ = setup(tmp_path, peers_for={"carehome": ["pharmacy"], "pharmacy": ["gp"]})
    stores["gp"].add(event("change-1"))
    run(syncs["pharmacy"].pull_once())
    run(syncs["carehome"].pull_once())
    assert [e.id for e in stores["carehome"].all()] == ["change-1"]


def test_never_duplicates(tmp_path):
    stores, syncs, _ = setup(tmp_path)
    stores["gp"].add(event("change-1"))
    for _ in range(3):
        for s in syncs.values():
            run(s.pull_once())
    for store in stores.values():
        assert [e.id for e in store.all()] == ["change-1"]


def test_only_pulls_what_is_new(tmp_path):
    stores, syncs, _ = setup(tmp_path)
    stores["gp"].add(event("change-1"))
    run(syncs["carehome"].pull_once())
    stores["gp"].add(event("change-2"))
    assert run(syncs["carehome"].pull_once()) == 1
    assert [e.id for e in stores["carehome"].all()] == ["change-1", "change-2"]


def test_unreachable_peer_does_not_crash_or_count_as_contact(tmp_path):
    stores, syncs, sites = setup(tmp_path)
    sites.down.add("gp")
    stores["gp"].add(event("change-1"))
    assert run(syncs["carehome"].pull_once()) == 0
    assert "gp" not in syncs["carehome"].state.last_seen
    assert syncs["carehome"].state.last_seen["pharmacy"] == 240     # pharmacy still reached


def test_catches_up_when_peer_comes_back(tmp_path):
    stores, syncs, sites = setup(tmp_path)
    sites.down.add("gp")
    stores["gp"].add(event("change-1"))
    run(syncs["carehome"].pull_once())
    sites.down.clear()
    run(syncs["carehome"].pull_once())
    assert [e.id for e in stores["carehome"].all()] == ["change-1"]


def test_post_rejects_malformed_event(tmp_path):
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(make_router("gp", EventStore(tmp_path / "gp.db")))
    client = TestClient(app)
    assert client.post("/api/events", json=event("e1").model_dump()).json()["stored"] is True
    assert client.post("/api/events", json={"id": "bad"}).status_code == 422