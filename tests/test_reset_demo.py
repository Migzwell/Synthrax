"""Demo reset: wipes the node databases and reloads the same seed every time."""
import shutil
from pathlib import Path

from node.store import EventStore
from reset_demo import reset_demo

SEED = Path(__file__).resolve().parents[1] / "data" / "seed_data.json"


def test_builds_one_database_per_node(tmp_path):
    result = reset_demo(data_dir=tmp_path, seed_path=SEED)
    assert set(result) == {"carehome", "gp", "pharmacy"}
    for node in result:
        assert result[node]["events_inserted"] == 18
        assert len(EventStore(tmp_path / f"{node}.db").all()) == 18


def test_wipes_rehearsal_data_and_stray_files(tmp_path):
    reset_demo(data_dir=tmp_path, seed_path=SEED)
    store = EventStore(tmp_path / "carehome.db")
    from core.types import Event
    store.add(Event(id="live-1", resident_id="R1", rx_id="M1", type="RX_CHANGED", author="gp",
                    created_at=0, seen_version=1, payload={"dose": "3mg"}))
    (tmp_path / "old.db").write_bytes(b"junk")

    reset_demo(data_dir=tmp_path, seed_path=SEED)

    assert not (tmp_path / "old.db").exists()
    assert "live-1" not in [e.id for e in EventStore(tmp_path / "carehome.db").all()]


def test_same_result_every_time(tmp_path):
    reset_demo(data_dir=tmp_path, seed_path=SEED)
    first = {n: [e.id for e in EventStore(tmp_path / f"{n}.db").all()] for n in ("carehome", "gp", "pharmacy")}
    reset_demo(data_dir=tmp_path, seed_path=SEED)
    again = {n: [e.id for e in EventStore(tmp_path / f"{n}.db").all()] for n in ("carehome", "gp", "pharmacy")}
    assert first == again and first["carehome"] == first["gp"] == first["pharmacy"]