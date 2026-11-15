"""Header, toggle, clock, badges, message log."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nicegui import ui

from core.conflicts import find_conflicts
from core.derive import derive
from core.rules import evaluate
from core.types import SEVERITY, Flag, NodeState, Resident
from node import clock_client
from node.actions import Actions
from node.clock_client import fmt
from node.store import EventStore
from node.sync import Sync

ASSETS = Path(__file__).resolve().parents[2] / "assets"
ICON = ASSETS / "synthrax_icon_animated.svg"            # the green pill: halves click together on load
if not ICON.exists():
    ICON = ASSETS / "synthrax_icon.png"
COLOUR = {"carehome": "#1D6B63", "gp": "#33479A", "pharmacy": "#9A5B0C"}
CHIP = {
    "BLOCK": ("Block", "bg-red-100 text-red-800"),
    "HOLD": ("Hold", "bg-red-100 text-red-800"),
    "GIVE_AND_ESCALATE": ("Give and escalate", "bg-orange-100 text-orange-800"),
    "REVIEW": ("Pharmacist review", "bg-purple-100 text-purple-800"),
    "WARN": ("Check", "bg-amber-100 text-amber-800"),
    "INFO": ("Note", "bg-sky-100 text-sky-800"),
    "OK": ("OK", "bg-emerald-100 text-emerald-800"),
}


@dataclass
class Site:
    """Everything a screen needs about this site. Screens read state and call actions; nothing else."""
    node_id: str
    store: EventStore
    sync: Sync
    actions: Actions
    seed: dict
    residents: list[Resident] = field(default_factory=list)

    @property
    def name(self) -> str:
        return next((n["name"] for n in self.seed.get("nodes", []) if n["id"] == self.node_id), self.node_id)

    def now(self) -> int:
        return clock_client.now()

    def online(self) -> bool:
        return self.sync.state.online

    def state(self) -> NodeState:
        return derive(self.store.all(), self.residents)

    def flags(self, state: NodeState) -> list[Flag]:
        return evaluate(state, self.now(), self.sync.state, node=self.node_id)

    def conflicts(self):
        return find_conflicts(self.store.all())

    def aliases(self) -> dict[str, list[str]]:
        """resident id -> names and aliases, lower case (e.g. 'mags' for Margaret)."""
        out = {}
        for r in self.seed.get("residents", []):
            out[r["id"]] = [r["name"].lower(), r["name"].split()[0].lower()] + [a.lower() for a in r.get("aliases", [])]
        return out


def page_style(site: Site) -> None:
    ui.query("body").style("background:#EEF2F1")


def chip(action: str) -> None:
    text, cls = CHIP[action]
    ui.label(text).classes(f"px-2 py-0.5 rounded text-xs font-bold {cls}")


def worst(flags: list[Flag]) -> str:
    return max((f.action for f in flags), key=lambda a: SEVERITY[a], default="OK")


def card(title: str):
    c = ui.card().classes("w-full shadow-none border border-gray-300")
    with c:
        ui.label(title).classes("text-lg font-bold")
    return c


def header(site: Site) -> None:
    colour = COLOUR[site.node_id]
    with ui.row().classes("w-full items-center justify-between border-b-4 pb-2").style(f"border-color:{colour}"):
        with ui.row().classes("items-center gap-3"):
            if ICON.exists():
                ui.image(str(ICON)).classes("w-12 h-12")
            with ui.column().classes("gap-0"):
                ui.label(site.name).classes("text-3xl font-bold leading-tight").style(f"color:{colour}")
                ui.label("Synthrax").classes("text-xs font-bold tracking-widest text-gray-500")
        with ui.row().classes("items-center gap-3"):
            @ui.refreshable
            def status():
                ui.label(f"Demo time {fmt(site.now())}").classes("text-lg font-bold")
                if site.online():
                    ui.label("● Synced").classes("px-3 py-1 rounded bg-emerald-100 text-emerald-800 font-bold")
                else:
                    seen = site.sync.state.last_seen
                    last = ", ".join(f"{k} {fmt(v)}" for k, v in seen.items()) or "never"
                    ui.label(f"● OFFLINE (last contact: {last})").classes(
                        "px-3 py-1 rounded bg-red-100 text-red-800 font-bold")
            status()
            ui.timer(1.0, status.refresh)
            ui.switch("Network", value=site.online(),
                      on_change=lambda e: setattr(site.sync.state, "online", e.value)).props("color=green")
            ui.button("+1 hour", on_click=lambda: clock_client.advance(60)).props("outline")
            ui.button("Next round", on_click=clock_client.jump_to_next_round).props("outline")


def describe(e, state: NodeState) -> str:
    rx = state.rx.get(e.rx_id) if e.rx_id else None
    who = state.residents.get(e.resident_id)
    first = who.name.split()[0] if who else e.resident_id
    med = f"{first}'s {rx.drug.lower()}" if rx else first
    p: dict[str, Any] = e.payload
    return {
        "RX_CREATED": f"prescribed {med}",
        "RX_CHANGED": f"changed {med} to {p.get('dose')}",
        "RX_STOPPED": f"stopped {med}",
        "RX_CONFIRMED": f"confirmed {med}: no change",
        "RX_ACKNOWLEDGED": f"acknowledged {med} v{p.get('version')}",
        "DISPENSED": f"dispensed {med} v{p.get('version')}" + (f", {p.get('qty')} doses" if p.get("qty") else ""),
        "DOSE_GIVEN": f"gave {med}",
        "DOSE_WITHHELD": f"did not give {med} ({p.get('reason')})",
        "OBSERVATION": f"{str(p.get('kind', '')).replace('_', ' ').lower()} for {first}",
        "REPEAT_REQUESTED": f"requested a repeat of {med}",
        "REQUEST_APPROVED": "authorised a repeat",
        "REQUEST_REJECTED": "declined a repeat",
        "CONFLICT_RESOLVED": f"reviewed a conflict card for {med}",
    }.get(e.type, e.type)


def event_log(site: Site) -> None:
    with card("Message log"):
        @ui.refreshable
        def body():
            state = site.state()
            recent = [e for e in reversed(state.events) if not e.id.startswith("seed-")][:12]
            if not recent:
                ui.label("Nothing has happened yet today.").classes("text-gray-500")
            for e in recent:
                with ui.row().classes("gap-3 text-sm"):
                    ui.label(fmt(e.created_at)).classes("text-gray-500 w-36")
                    ui.label(e.author).classes("font-bold w-20")
                    ui.label(describe(e, state))
        body()
        ui.timer(1.5, body.refresh)