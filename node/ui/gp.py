"""Alerts, dose changes, repeat requests, conflict cards, AI triage of residents."""
from nicegui import run, ui

from node.agent import llm

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


URGENCY_ORDER = {"urgent": 0, "soon": 1, "routine": 2}
URGENCY_CHIP = {"urgent": "HOLD", "soon": "WARN", "routine": "OK"}
_summary_cache: dict = {}      # (resident, last event id) -> (summary, source): the AI is asked once per change


def _summary_for(resident_id: str, events, rxs):
    key = (resident_id, events[-1].id if events else None)
    if key not in _summary_cache:
        summary = summarise(events, rxs)
        if summary.source != "llm":
            source = "Automatic summary (AI not used)"
        else:
            source = "AI summary (Claude, live)" if llm.last_source == "live" else "AI summary (cached example)"
        _summary_cache[key] = (summary, source)
    return _summary_cache[key]


def summary_box(site: Site) -> None:
    with card("Residents by urgency (AI)"):
        ui.label("The AI reads each resident's recent events and writes three lines, most urgent first. "
                 "A reading aid only: it changes nothing. A safety flag always makes it urgent.").classes(
            "text-sm text-gray-600")
        result = ui.column().classes("w-full")
        seen = {"key": None}

        async def show(force: bool = False):
            state = site.state()
            by_resident = {}
            for e in state.events:
                if not e.id.startswith("seed-"):
                    by_resident.setdefault(e.resident_id, []).append(e)
            key = tuple((r, ev[-1].id) for r, ev in sorted(by_resident.items()))
            if key == seen["key"] and not force:
                return                                   # nothing new: don't ask the AI again
            seen["key"] = key
            found = []
            for res_id, events in by_resident.items():
                summary, source = await run.io_bound(_summary_for, res_id, events, state.rx)
                found.append((res_id, summary, source))
            found.sort(key=lambda r: URGENCY_ORDER[r[1].urgency])
            result.clear()
            with result:
                if not found:
                    ui.label("Nothing new today.").classes("text-gray-500")
                for res_id, summary, source in found:
                    with ui.column().classes("w-full gap-1 border-t border-dashed border-gray-300 py-2"):
                        with ui.row().classes("items-center gap-2"):
                            chip(URGENCY_CHIP[summary.urgency])
                            ui.label(f"{_name(state, res_id)}: {summary.urgency.capitalize()}").classes("font-bold")
                        for line in summary.lines:
                            ui.label(f"• {line}").classes("text-sm")
                        ui.label(source).classes("text-xs text-gray-500")

        ui.timer(3.0, show)
        ui.button("Refresh", on_click=lambda: show(force=True)).props("dense outline")