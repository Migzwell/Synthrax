"""Reset the demo to its starting state.

Deletes every data/*.db file, then loads the seed into one fresh database per
node (data/carehome.db, data/gp.db, data/pharmacy.db).

Run from the project root:   python reset_demo.py
Safe to run as often as you like: you get the same result every time.
Stop the node programs first. Windows will not delete a file that is in use.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

from node.seed_loader import load_seed, read_seed
from node.store import EventStore

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SEED_PATH = DATA_DIR / "seed_data.json"


def reset_demo(data_dir: Union[str, Path] = DATA_DIR,
               seed_path: Union[str, Path] = SEED_PATH) -> dict:
    """Wipe the node databases and reload the seed. Returns {node_id: summary}."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    seed = read_seed(Path(seed_path))

    for old in list(data_dir.glob("*.db")) + list(data_dir.glob("*.db-*")):
        try:
            old.unlink()
        except PermissionError as exc:
            raise SystemExit(f"Cannot delete {old.name}: it is in use. Stop the node programs and try again.") from exc

    summary = {}
    for node in seed["nodes"]:
        db = data_dir / f"{node['id']}.db"
        inserted = load_seed(Path(seed_path), EventStore(db))
        summary[node["id"]] = {"events_inserted": inserted, "residents": len(seed["residents"]), "db": str(db)}
    return summary


if __name__ == "__main__":
    for node_id, summary in reset_demo().items():
        print(f"{node_id:9} {summary['events_inserted']} events, {summary['residents']} residents -> {summary['db']}")