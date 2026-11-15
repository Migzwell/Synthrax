"""Starts a node: screen, API, sync and clock loops."""
import argparse
import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # the Synthrax project folder
if str(ROOT) not in sys.path:                       # lets PyCharm's Run button start this file directly
    sys.path.insert(0, str(ROOT))

import uvicorn                                      # noqa: E402
from fastapi import FastAPI                         # noqa: E402

from node import clock_client                       # noqa: E402
from node.actions import Actions                    # noqa: E402
from node.api import make_router                    # noqa: E402
from node.config import SYNC_INTERVAL_SECONDS, peers_of, port_of   # noqa: E402
from node.seed_loader import load_seed, read_seed   # noqa: E402
from node.store import EventStore                   # noqa: E402
from node.sync import Sync                          # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--node", default="carehome", choices=["carehome", "gp", "pharmacy"],
                    help="which site to run (default: carehome)")
parser.add_argument("--port", type=int)
args, _ = parser.parse_known_args()

NODE_ID = args.node
DATA = ROOT / "data"                                # works whatever folder you start from
store = EventStore(DATA / f"{NODE_ID}.db")
sync = Sync(NODE_ID, store, peers_of(NODE_ID), now=clock_client.now)
actions = Actions(NODE_ID, store, now=clock_client.now)   # the screens call these

SEED_PATH = DATA / "seed_data.json"
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

# ---------- screens ----------
from nicegui import ui                                    # noqa: E402

from node.seed_loader import residents as seed_residents  # noqa: E402
from node.ui import carehome, common, gp, pharmacy        # noqa: E402

site = common.Site(node_id=NODE_ID, store=store, sync=sync, actions=actions, seed=seed,
                   residents=seed_residents(seed))
SCREENS = {"carehome": carehome, "gp": gp, "pharmacy": pharmacy}


@ui.page("/")
def index():
    common.page_style(site)
    common.header(site)
    screen = SCREENS[NODE_ID]
    if hasattr(screen, "build"):
        screen.build(site)
    else:
        ui.label("This screen has not been built yet.").classes("text-gray-500")
    common.event_log(site)


ui.run_with(app, title=f"Synthrax {site.name}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=args.port or port_of(NODE_ID))