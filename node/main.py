"""Starts a node: screen, API, sync and clock loops."""
import argparse
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from . import clock_client
from .actions import Actions
from .api import make_router
from .config import SYNC_INTERVAL_SECONDS, peers_of, port_of
from .seed_loader import load_seed, read_seed
from .store import EventStore
from .sync import Sync

parser = argparse.ArgumentParser()
parser.add_argument("--node", required=True, choices=["carehome", "gp", "pharmacy"])
parser.add_argument("--port", type=int)
args, _ = parser.parse_known_args()

NODE_ID = args.node
store = EventStore(Path("data") / f"{NODE_ID}.db")
sync = Sync(NODE_ID, store, peers_of(NODE_ID), now=clock_client.now)
actions = Actions(NODE_ID, store, now=clock_client.now)   # the screens call these

SEED_PATH = Path("data") / "seed_data.json"
seed = read_seed(SEED_PATH)
print(f"{NODE_ID}: loaded {load_seed(SEED_PATH, store)} new seed events")   # 0 after a restart


async def clock_loop():
    while True:
        await clock_client.poll()
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(_app):
    tasks = [asyncio.create_task(clock_loop()), asyncio.create_task(sync.run_forever(SYNC_INTERVAL_SECONDS))]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title=f"Synthrax {NODE_ID}", lifespan=lifespan)
app.include_router(make_router(NODE_ID, store, sync.state, now=clock_client.now, actions=actions, seed=seed))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=args.port or port_of(NODE_ID))
