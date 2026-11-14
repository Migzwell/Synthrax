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

from core.seed import load_seed, load_seed_file

DATA_DIR = Path(__file__).resolve().parent / "data"


def reset_demo(data_dir: Union[str, Path] = DATA_DIR,
               seed_path: Union[str, Path, None] = None,
               now_minutes: int = 0) -> dict:
    """Wipe the node databases and reload the seed. Returns {node_id: summary}."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    seed = load_seed_file(seed_path)

    for old in list(data_dir.glob("*.db")) + list(data_dir.glob("*.db-*")):
        try:
            old.unlink()
        except PermissionError as exc:
            raise SystemExit(f"Cannot delete {old.name}: it is in use. Stop the node programs and try again.") from exc

    return {
        node["id"]: load_seed(data_dir / f"{node['id']}.db", seed_path, now_minutes)
        for node in seed["nodes"]
    }


if __name__ == "__main__":
    for node_id, summary in reset_demo().items():
        print(f"{node_id:9} {summary['events_inserted']} events, {summary['residents']} residents -> {summary['db']}")
        