from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_NAMES = ("seed_data.json", "seed.json")
_SKIP_DIRS = {".venv", "venv", ".git", "__pycache__", ".pytest_cache", "node_modules"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id            TEXT PRIMARY KEY,
    seq           INTEGER NOT NULL UNIQUE,   -- order this node received it
    resident_id   TEXT NOT NULL,
    rx_id         TEXT,                      -- the medication id, e.g. M1
    type          TEXT NOT NULL,
    payload       TEXT NOT NULL,             -- JSON
    author        TEXT NOT NULL,
    created_at    INTEGER NOT NULL,          -- minutes (see module docstring)
    lamport       INTEGER NOT NULL,
    seen_version  INTEGER
);
CREATE TABLE IF NOT EXISTS residents (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL,
    age   INTEGER,
    room  TEXT
);
"""

# Keys that become columns on the event row. Everything else goes in payload.
_ROW_KEYS = {"t_hours", "type", "author", "resident_id", "medication_id"}

def find_seed_path(root: Union[str, Path, None] = None) -> Path:
    """Find the seed file (seed_data.json or seed.json) inside the project."""
    root = Path(root) if root else PROJECT_ROOT
    # the usual places first
    for folder in (root / "data", root, root / "core"):
        for name in SEED_NAMES:
            if (folder / name).is_file():
                return folder / name
    # then anywhere else in the project, skipping .venv and similar
    for folder, subfolders, files in os.walk(root):
        subfolders[:] = sorted(d for d in subfolders if d not in _SKIP_DIRS)
        for name in SEED_NAMES:
            if name in files:
                return Path(folder) / name
    raise FileNotFoundError(
        f"No seed file found. Put seed_data.json (or seed.json) somewhere inside {root}"
    )


def load_seed_file(path: Union[str, Path, None] = None) -> dict:
    """Read and parse the seed JSON. Finds the file itself if no path is given."""
    path = Path(path) if path else find_seed_path()
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def build_events(seed: dict, now_minutes: int = 0) -> list[dict]:
    """Turn seed["starting_events"] into event dicts, oldest first."""
    raw_events = seed["starting_events"]
    # sort by time; ties keep file order
    ordered = sorted(enumerate(raw_events), key=lambda pair: (pair[1]["t_hours"], pair[0]))
    events = []
    for n, (_, raw) in enumerate(ordered, start=1):
        payload = {k: v for k, v in raw.items() if k not in _ROW_KEYS}
        seen_version = raw.get("rx_version_used") if raw["type"] == "DOSE_GIVEN" else None
        events.append({
            "id": f"seed-{n:03d}",
            "resident_id": raw["resident_id"],
            "rx_id": raw.get("medication_id"),
            "type": raw["type"],
            "payload": payload,
            "author": raw["author"],
            "created_at": now_minutes + round(raw["t_hours"] * 60),
            "lamport": n,
            "seen_version": seen_version,
        })
    return events

def load_seed(db_path: Union[str, Path],
              seed_path: Union[str, Path, None] = None,
              now_minutes: int = 0) -> dict:
    """Write the residents and starting events into a SQLite file.

    Creates the file and tables if needed. Safe to call again.
    Returns {"db", "residents", "events_in_seed", "events_inserted"};
    events_inserted is 0 when everything was already there.
    """
    seed = load_seed_file(seed_path)
    events = build_events(seed, now_minutes)

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(db_path)
    try:
        con.executescript(SCHEMA)
        inserted = 0
        with con:  # one transaction
            for r in seed["residents"]:
                con.execute(
                    "INSERT OR IGNORE INTO residents (id, name, age, room) VALUES (?, ?, ?, ?)",
                    (r["id"], r["name"], r.get("age"), r.get("room")),
                )
            next_seq = con.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0] + 1
            for e in events:
                cur = con.execute(
                    "INSERT OR IGNORE INTO events "
                    "(id, seq, resident_id, rx_id, type, payload, author, created_at, lamport, seen_version) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (e["id"], next_seq, e["resident_id"], e["rx_id"], e["type"],
                     json.dumps(e["payload"], sort_keys=True), e["author"],
                     e["created_at"], e["lamport"], e["seen_version"]),
                )
                if cur.rowcount:
                    inserted += 1
                    next_seq += 1
    finally:
        con.close()

    return {
        "db": str(db_path),
        "residents": len(seed["residents"]),
        "events_in_seed": len(events),
        "events_inserted": inserted,
    }


# ---------- looking things up (case-insensitive, aliases) ----------

def _norm(text: Any) -> str:
    return str(text).strip().lower()


def find_medication(seed: dict, name: str, resident_id: Optional[str] = None) -> Optional[dict]:
    """Find a medication by drug name or alias, ignoring case.

    Pass resident_id to look only at that resident's medicines.
    """
    wanted = _norm(name)
    for med in seed["medications"]:
        if resident_id is not None and med["resident_id"] != resident_id:
            continue
        names = [_norm(med["drug"])] + [_norm(a) for a in med.get("aliases", [])]
        if wanted in names:
            return med
    return None


def canonical_drug(seed: dict, name: str) -> str:
    """Lower-case drug name, with aliases resolved ("Sinemet" -> "co-careldopa")."""
    med = find_medication(seed, name)
    return _norm(med["drug"]) if med else _norm(name)


def is_high_risk(seed: dict, name: str) -> bool:
    return canonical_drug(seed, name) in {_norm(d) for d in seed["high_risk_drugs"]}


def is_time_critical(seed: dict, name: str) -> bool:
    return canonical_drug(seed, name) in {_norm(d) for d in seed["time_critical_drugs"]}


def check_flags_in_step(seed: dict) -> list[str]:
    """Check each medication's high_risk / time_critical flag against the two lists.

    The seed's readme says they must be kept in step. Returns a list of
    problems; an empty list means they agree.
    """
    problems = []
    for med in seed["medications"]:
        for flag, listed in (("high_risk", is_high_risk(seed, med["drug"])),
                             ("time_critical", is_time_critical(seed, med["drug"]))):
            if bool(med[flag]) != listed:
                problems.append(f"{med['id']} {med['drug']}: {flag} is {med[flag]} but the drug list says {listed}")
    return problems
