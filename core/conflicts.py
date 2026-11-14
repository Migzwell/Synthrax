"""Conflict cards: what went wrong while a site was offline, for the GP to review after reconnect."""
from collections import defaultdict
from typing import Literal, Optional

from pydantic import BaseModel

from .types import Event

CardKind = Literal["held_while_offline", "stale_dose", "stale_dispense", "concurrent_change"]


class ConflictCard(BaseModel):
    id: str                          # stable id; the GP's review sends this back as `group`
    kind: CardKind
    severity: Literal["urgent", "review"]
    resident_id: str
    rx_id: Optional[str] = None
    title: str
    message: str
    event_ids: list[str]
    created_at: int                  # demo minute of the event that caused the card


def _time(minute: int) -> str:
    total = 14 * 60 + minute                                    # minute 0 = 14:00 on demo day
    day = {-1: " yesterday", 0: "", 1: " tomorrow"}.get(total // 1440, "")
    return f"{(total // 60) % 24:02d}:{total % 60:02d}{day}"


class _History:
    """Each medicine's versions over time, rebuilt from the events."""

    def __init__(self, events: list[Event]):
        self.drug: dict[str, str] = {}
        self.versions: dict[str, list[tuple[int, int, str]]] = defaultdict(list)   # (from minute, version, dose)
        for e in sorted(events, key=lambda e: (e.created_at, e.lamport)):
            if e.type == "RX_CREATED" and e.rx_id:
                self.drug[e.rx_id] = e.payload.get("drug", e.rx_id)
                self.versions[e.rx_id].append((e.created_at, 1, e.payload.get("dose", "")))
            elif e.type == "RX_CHANGED" and e.rx_id and e.seen_version is not None:
                self.versions[e.rx_id].append((e.created_at, e.seen_version + 1, e.payload.get("dose", "")))

    def at(self, rx_id: str, minute: int) -> tuple[int, str, Optional[int]]:
        """(version, dose, minute it started) in force at `minute`."""
        current = (1, "", None)
        for start, version, dose in self.versions.get(rx_id, []):
            if start <= minute and version >= current[0]:
                current = (version, dose, start)
        return current

    def latest(self, rx_id: str) -> tuple[int, str]:
        v, dose, _ = self.at(rx_id, 10 ** 9)
        return v, dose


def find_conflicts(events: list[Event]) -> list[ConflictCard]:
    """Every open card, most urgent first."""
    reviewed = {e.payload.get("group") for e in events if e.type == "CONFLICT_RESOLVED"}
    history = _History(events)
    cards: list[ConflictCard] = []

    for e in events:
        rx = e.rx_id
        drug = history.drug.get(rx, rx or "medicine")

        # 1. A dose held for safety (e.g. R1 while the care home was cut off from the GP)
        if e.type == "DOSE_WITHHELD" and e.payload.get("reason") == "safety hold":
            latest_v, latest_dose = history.latest(rx)
            when = e.payload.get("slot") if e.payload.get("slot") is not None else e.created_at
            cards.append(ConflictCard(
                id=f"held:{e.id}", kind="held_while_offline", severity="review",
                resident_id=e.resident_id, rx_id=rx, event_ids=[e.id], created_at=e.created_at,
                title=f"{drug} held at {_time(when)}",
                message=(f"The care home held this dose for safety. The prescription is now v{latest_v} "
                         f"({latest_dose}). Confirm the hold was right and the next dose is correct.")))

        if e.type == "DOSE_GIVEN" and rx:
            used = e.payload.get("version")
            given = e.payload.get("given_at", e.created_at)
            v, dose, since = history.at(rx, given)
            if used is not None and used < v:
                cards.append(ConflictCard(
                    id=f"stale-dose:{e.id}", kind="stale_dose", severity="urgent",
                    resident_id=e.resident_id, rx_id=rx, event_ids=[e.id], created_at=e.created_at,
                    title=f"{drug} given from an old prescription",
                    message=(f"Given at {_time(given)} using v{used}, but v{v} ({dose}) had existed since "
                             f"{_time(since)}. Check the resident and seek clinical advice if needed.")))

        if e.type == "DISPENSED" and rx:
            made = e.payload.get("version")
            v, dose, since = history.at(rx, e.created_at)
            if made is not None and made < v:
                cards.append(ConflictCard(
                    id=f"stale-dispense:{e.id}", kind="stale_dispense", severity="urgent",
                    resident_id=e.resident_id, rx_id=rx, event_ids=[e.id], created_at=e.created_at,
                    title=f"{drug} pack made from an old prescription",
                    message=(f"Pack v{made} made at {_time(e.created_at)}, but v{v} ({dose}) existed. "
                             f"Re-dispense and withdraw the old pack.")))

    by_base: dict[tuple[str, int], list[Event]] = defaultdict(list)
    for e in events:
        if e.type == "RX_CHANGED" and e.rx_id and e.seen_version is not None:
            by_base[(e.rx_id, e.seen_version)].append(e)
    for (rx, base), changes in by_base.items():
        if len(changes) > 1:
            changes.sort(key=lambda e: e.created_at)
            doses = " vs ".join(f"{c.payload.get('dose')} ({c.author}, {_time(c.created_at)})" for c in changes)
            cards.append(ConflictCard(
                id=f"concurrent:{rx}@{base}", kind="concurrent_change", severity="urgent",
                resident_id=changes[0].resident_id, rx_id=rx, event_ids=[c.id for c in changes],
                created_at=changes[-1].created_at,
                title=f"Two changes to {history.drug.get(rx, rx)} at the same time",
                message=f"Both changed v{base} without seeing each other: {doses}. Choose the right dose."))

    open_cards = [c for c in cards if c.id not in reviewed]
    return sorted(open_cards, key=lambda c: (c.severity != "urgent", c.created_at))