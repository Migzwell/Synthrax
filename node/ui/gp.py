"""Alerts, dose changes, repeat requests, conflict cards, AI summary."""
from nicegui import ui

from node.agent.summarise import summarise
from node.clock_client import fmt
from .common import Site, card, chip


def build(site: Site) -> None:
    with ui.row().classes("w-full items-start gap-4 no-wrap"):
        with ui.column().classes("w-3/5"):
            alerts(site)
            conflict_cards(site)
            requests(site)
        with ui.column().classes("w-2/5"):
            change_form(site)
            prescribe_form(site)
            summary_box(site)


def _name(state, resident_id: str) -> str:
    res = state.residents.get(resident_id)
    return res.name if res else resident_id


def alerts(site: Site) -> None:
    with card("Alerts"):
        ui.label("Dose changes the care home has not acknowledged.").classes("text-sm text-gray-600")

        @ui.refreshable
        def body():
            state = site.state()
            flags = site.flags(state)
            if not flags:
                ui.label("Nothing needs your attention.").classes("text-gray-500")
            for f in flags:
                with ui.row().classes("items-center gap-2"):
                    chip(f.action)
                    ui.label(f"{_name(state, f.resident_id)}: {f.message}").classes("text-sm")
        body()
        ui.timer(1.0, body.refresh)


def conflict_cards(site: Site) -> None:
    with card("Conflict cards"):
        ui.label("What happened while a site was offline. Review each one.").classes("text-sm text-gray-600")

        @ui.refreshable
        def body():
            state = site.state()
            cards = site.conflicts()
            if not cards:
                ui.label("No conflicts to review.").classes("text-gray-500")
            for c in cards:
                urgent = c.severity == "urgent"
                with ui.card().classes(
                        f"w-full shadow-none border-l-8 {'border-red-600 bg-red-50' if urgent else 'border-amber-500'}"):
                    ui.label(f"{_name(state, c.resident_id)} · {fmt(c.created_at)}").classes("text-xs text-gray-600")
                    ui.label(c.title).classes("font-bold")
                    ui.label(c.message).classes("text-sm")
                    ui.button("Mark reviewed", on_click=lambda c=c: site.actions.review_conflict(
                        c.resident_id, c.rx_id, group=c.id,
                        chosen=c.event_ids[-1] if c.event_ids else "")).props("dense")
        body()
        ui.timer(1.5, body.refresh)


def requests(site: Site) -> None:
    with card("Repeat requests"):
        ui.label("Requests from the care home waiting for you.").classes("text-sm text-gray-600")

        @ui.refreshable
        def body():
            state = site.state()
            waiting = [r for r in state.open_requests.values() if r.id not in state.approved_requests]
            if not waiting:
                ui.label("No requests waiting.").classes("text-gray-500")
            for req in waiting:
                rx = state.rx.get(req.rx_id)
                drug = f"{rx.drug} {rx.dose}" if rx else "medicine"
                auto = " (drafted automatically, low stock)" if req.payload.get("auto_drafted") else ""
                with ui.row().classes("items-center gap-3"):
                    ui.label(f"{_name(state, req.resident_id)}: {drug}, {req.payload.get('qty')} doses{auto}").classes(
                        "text-sm font-bold")
                    ui.button("Authorise", on_click=lambda r=req: site.actions.approve_request(
                        r.resident_id, r.id, rx_id=r.rx_id)).props("dense")
                    ui.button("Decline", on_click=lambda r=req: site.actions.reject_request(
                        r.resident_id, r.id, rx_id=r.rx_id)).props("dense outline")
        body()
        ui.timer(1.0, body.refresh)


def _medicine_options(site: Site) -> dict:
    state = site.state()
    return {rx.id: f"{_name(state, rx.resident_id)}: {rx.drug} {rx.dose} (v{rx.version})"
            for rx in state.rx.values() if not rx.stopped}


def change_form(site: Site) -> None:
    with card("Change a medicine"):
        ui.label("Only the GP changes medicines. The care home must acknowledge each change.").classes(
            "text-sm text-gray-600")
        options = _medicine_options(site)
        pick = ui.select(options, value=next(iter(options), None), label="Medicine").classes("w-full")
        dose = ui.input("New dose, e.g. 3mg").classes("w-full")
        reason = ui.input("Reason, e.g. INR 3.8, reduce dose").classes("w-full")

        def refresh_options():
            pick.options = _medicine_options(site)
            pick.update()

        def current():
            return site.state().rx.get(pick.value)

        def change():
            rx = current()
            if rx is None:
                ui.notify("Choose a medicine first.", type="warning")
                return
            try:
                site.actions.change_dose(rx.resident_id, rx.id, dose.value or "", seen_version=rx.version,
                                         old_dose=rx.dose, reason=reason.value or "")
            except ValueError as e:
                ui.notify(str(e), type="warning")
                return
            ui.notify(f"{rx.drug} changed to {dose.value}. Waiting for the care home to acknowledge.")
            dose.value = ""
            refresh_options()

        def no_change():
            rx = current()
            if rx is None:
                ui.notify("Choose a medicine first.", type="warning")
                return
            site.actions.confirm_no_change(rx.resident_id, rx.id,
                                           reason.value or "Result reviewed, no change", version=rx.version)
            ui.notify(f"{rx.drug}: confirmed, no change.")

        def stop():
            rx = current()
            if rx is None:
                ui.notify("Choose a medicine first.", type="warning")
                return
            site.actions.stop_medicine(rx.resident_id, rx.id, reason=reason.value or "")
            ui.notify(f"{rx.drug} stopped.")
            refresh_options()

        with ui.row().classes("gap-2"):
            ui.button("Change dose", on_click=change)
            ui.button("Confirm no change", on_click=no_change).props("outline")
            ui.button("Stop", on_click=stop).props("outline color=red")


def prescribe_form(site: Site) -> None:
    with card("Prescribe a new medicine"):
        ui.label("The pharmacy checks it for interactions before dispensing.").classes("text-sm text-gray-600")
        state = site.state()
        people = {r.id: r.name for r in state.residents.values()}
        who = ui.select(people, value=next(iter(people), None), label="Resident").classes("w-full")
        drug = ui.input("Drug, e.g. Ibuprofen").classes("w-full")
        dose = ui.input("Dose, e.g. 400mg").classes("w-full")
        times = ui.input("Times, e.g. 08:00, 18:00 (leave empty for when required)").classes("w-full")
        frequency = ui.input("Frequency (optional), e.g. once weekly").classes("w-full")

        def prescribe():
            wanted = [t.strip() for t in (times.value or "").split(",") if t.strip()]
            try:
                site.actions.prescribe(who.value, drug.value or "", dose.value or "", times=wanted,
                                       frequency=frequency.value or "")
            except ValueError as e:
                ui.notify(str(e), type="warning")
                return
            ui.notify(f"{drug.value} prescribed. Sent to the pharmacy.")
            drug.value = dose.value = times.value = frequency.value = ""
        ui.button("Prescribe", on_click=prescribe)


def summary_box(site: Site) -> None:
    with card("Resident summary (AI)"):
        ui.label("Three lines on what has happened. A reading aid only: it changes nothing.").classes(
            "text-sm text-gray-600")
        state = site.state()
        people = {r.id: r.name for r in state.residents.values()}
        who = ui.select(people, value=next(iter(people), None), label="Resident").classes("w-full")
        result = ui.column().classes("w-full")

        def show():
            result.clear()
            state = site.state()
            events = [e for e in state.events if e.resident_id == who.value and not e.id.startswith("seed-")]
            summary = summarise(events, state.rx)
            with result:
                with ui.row().classes("items-center gap-2"):
                    chip({"urgent": "HOLD", "soon": "WARN", "routine": "OK"}[summary.urgency])
                    ui.label(summary.urgency.capitalize()).classes("font-bold")
                for line in summary.lines:
                    ui.label(f"• {line}").classes("text-sm")
                source = "AI summary" if summary.source == "llm" else "Automatic summary (AI not used)"
                ui.label(source).classes("text-xs text-gray-500")
        ui.button("Summarise", on_click=show)
