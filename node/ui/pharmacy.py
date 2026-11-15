"""Dispensing queue, QR codes, alerts."""
import segno
from nicegui import ui

from core.rules.r5 import days_left
from node.actions import pack_code
from .common import Site, card, chip

PACK_DAYS = 28


def qr(code: str, scale: int = 4) -> str:
    return segno.make(code, error="m").svg_data_uri(scale=scale, border=2)


def build(site: Site) -> None:
    with ui.row().classes("w-full items-start gap-4 no-wrap"):
        with ui.column().classes("w-3/5"):
            queue(site)
        with ui.column().classes("w-2/5"):
            supply(site)
            labels(site)


def queue(site: Site) -> None:
    with card("Dispensing queue"):
        ui.label("New and changed prescriptions, and authorised repeats.").classes("text-sm text-gray-600")

        @ui.refreshable
        def body():
            state = site.state()
            r6 = site.flags(state)
            empty = True
            for rx in state.rx.values():
                if rx.version <= rx.dispensed_version or rx.stopped:
                    continue
                empty = False
                name = state.residents[rx.resident_id].name
                code = pack_code(rx.resident_id, rx.id, rx.drug, rx.dose, rx.version)
                mine = [f for f in r6 if f.rx_id == rx.id]
                blocked = any(f.action == "BLOCK" for f in mine)
                with ui.card().classes(f"w-full shadow-none border-l-8 {'border-red-600 bg-red-50' if blocked else 'border-amber-500'}"):
                    kind = "New prescription" if rx.dispensed_version == 0 else "Dose change"
                    ui.label(f"{kind}: {name}").classes("text-xs text-gray-600")
                    ui.label(f"{rx.drug} {rx.dose} (v{rx.version})").classes("font-bold")
                    for f in mine:
                        with ui.row().classes("items-center gap-2"):
                            chip(f.action)
                            ui.label(f"R6: {f.message}").classes("text-sm")
                    if not mine:
                        ui.label("Safety check: no problems found.").classes("text-sm text-emerald-700")
                    with ui.row().classes("items-center gap-4"):
                        ui.image(qr(code)).classes("w-28")
                        ui.label(code).classes("font-mono text-sm")
                    qty = PACK_DAYS * max(1, len(rx.times))
                    btn = ui.button(f"Dispense new pack ({qty} doses)", on_click=lambda rx=rx, q=qty: site.actions.dispense(
                        rx.resident_id, rx.id, rx.version, q, drug=rx.drug, dose=rx.dose)).props("dense")
                    if blocked:
                        btn.disable()
            for req in state.approved_requests.values():
                rx = state.rx.get(req.rx_id)
                if rx is None:
                    continue
                empty = False
                name = state.residents[rx.resident_id].name
                with ui.card().classes("w-full shadow-none border-l-8 border-sky-500"):
                    ui.label(f"Authorised repeat: {name}").classes("text-xs text-gray-600")
                    ui.label(f"{rx.drug} {rx.dose}, {req.payload.get('qty')} doses").classes("font-bold")
                    ui.button("Mark dispensed", on_click=lambda rx=rx, r=req: site.actions.dispense(
                        rx.resident_id, rx.id, rx.version, int(r.payload.get("qty", 28)),
                        drug=rx.drug, dose=rx.dose, request_id=r.id)).props("dense")
            if empty:
                ui.label("Nothing to dispense.").classes("text-gray-500")
        body()
        ui.timer(1.0, body.refresh)


def labels(site: Site) -> None:
    with card("Current pack labels"):
        ui.label("Each label carries resident, medicine, dose and prescription version.").classes(
            "text-sm text-gray-600")

        @ui.refreshable
        def body():
            state = site.state()
            with ui.row().classes("gap-4 flex-wrap"):
                for rx in state.rx.values():
                    if rx.stopped or rx.dispensed_version < rx.version:
                        continue                       # new version still in the dispensing queue
                    code = pack_code(rx.resident_id, rx.id, rx.drug, rx.dose, rx.version)
                    with ui.column().classes("items-center gap-0"):
                        ui.image(qr(code, scale=3)).classes("w-24")
                        ui.label(f"{state.residents[rx.resident_id].name.split()[0]}: {rx.drug}").classes("text-xs")
                        ui.label(code).classes("text-xs font-mono")
        body()
        ui.timer(2.0, body.refresh)


def supply(site: Site) -> None:
    with card("Supply view"):
        ui.label("Upcoming repeats for all residents, so nothing is a last-minute rush.").classes(
            "text-sm text-gray-600")

        @ui.refreshable
        def body():
            state = site.state()
            requested = {r.rx_id: ("authorised" if r.id in state.approved_requests else "requested")
                         for r in state.open_requests.values()}
            rows = sorted(((days_left(rx), rx) for rx in state.rx.values()
                           if not rx.stopped and not rx.prn and rx.dispensed_version > 0), key=lambda r: r[0])
            for days, rx in rows[:6]:
                name = state.residents[rx.resident_id].name.split()[0]
                status = requested.get(rx.id, "")
                colour = "text-red-700" if days < 7 and not status else "text-gray-700"
                ui.label(f"{name}: {rx.drug}, {days:.1f} days left"
                         + (f" ({status})" if status else "")).classes(f"text-sm {colour}")
        body()
        ui.timer(2.0, body.refresh)