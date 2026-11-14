"""SQLite append-only event log."""
import sqlite3
import threading
from pathlib import Path

from core.types import Event


class EventStore:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)       # creates data/ if it's missing
        self._lock = threading.Lock()                        # screens and sync write at the same time
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            " seq  INTEGER PRIMARY KEY AUTOINCREMENT,"       # order events arrived at THIS site
            " id   TEXT UNIQUE NOT NULL,"                    # the event's own id, same at every site
            " body TEXT NOT NULL)"                           # the whole event as JSON
        )
        self._db.commit()

    def add(self, event: Event) -> bool:
        """Save an event. Returns True if it was new, False if we already had it.

        INSERT OR IGNORE is what stops sync from ever storing the same event twice.
        """
        with self._lock:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO events (id, body) VALUES (?, ?)",
                (event.id, event.model_dump_json()),
            )
            self._db.commit()
            return cur.rowcount == 1

    def since(self, seq: int) -> tuple[list[Event], int]:
        """Events stored after position `seq`, oldest first, plus the newest position.

        Sync calls this: "give me everything after the last position I pulled from you".
        """
        with self._lock:
            rows = self._db.execute(
                "SELECT seq, body FROM events WHERE seq > ? ORDER BY seq", (seq,)
            ).fetchall()
        events = [Event.model_validate_json(body) for _, body in rows]
        newest = rows[-1][0] if rows else seq
        return events, newest

    def all(self) -> list[Event]:
        """Every event, oldest first."""
        return self.since(0)[0]

    def max_lamport(self) -> int:
        """Highest lamport number so far; a new event uses this + 1."""
        return max((e.lamport for e in self.all()), default=0)