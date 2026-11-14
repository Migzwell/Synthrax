"""Pulls missing events from peers every 2s."""
import asyncio
from typing import Callable, Optional

import httpx

from core.types import Event, SyncState
from .store import EventStore


class Sync:
    def __init__(self, node_id: str, store: EventStore, peers: dict[str, str],
                 now: Callable[[], int], client: Optional[httpx.AsyncClient] = None):
        self.node_id = node_id
        self.store = store
        self.peers = peers                              # {"gp": "http://localhost:8002", ...}
        self.now = now                                  # the demo clock, never the real one
        self.state = SyncState()                        # last_seen per peer; the toggle uses .online
        self._pulled = {peer: 0 for peer in peers}      # highest position already pulled from each peer
        self._client = client                           # tests pass one in; normally made per pull

    async def pull_once(self) -> int:
        """Ask each peer for events since the last pull. Returns how many new events were stored."""
        if not self.state.online:
            return 0                                    # switched off: work alone, last_seen stays frozen
        new = 0
        client = self._client or httpx.AsyncClient(timeout=1.5)
        try:
            for peer, url in self.peers.items():
                try:
                    r = await client.get(f"{url}/api/events", params={"since": self._pulled[peer]})
                    if r.status_code != 200:
                        continue                        # peer offline or broken: try again next time
                    data = r.json()
                    for raw in data["events"]:
                        new += self.store.add(Event.model_validate(raw))
                    self._pulled[peer] = data["max_seq"]
                    self.state.last_seen[peer] = self.now()
                except httpx.HTTPError:
                    pass                                # unreachable: never crash the loop
        finally:
            if self._client is None:
                await client.aclose()
        return new

    async def run_forever(self, interval: float = 2.0) -> None:
        while True:
            await self.pull_once()
            await asyncio.sleep(interval)