"""Med round, letter, note, verbal, pack scan."""
from nicegui import ui

from core.rules import blocking_flag
from core.rules.r5 import draft_repeat
from core.schedule import due_slot
from node.agent import llm
from node.agent.parse_note import parse_note, to_draft_events
from node.clock_client import fmt
from .common import Site, card, chip, worst


def build(site: Site) -> None:
    with ui.row().classes("w-full items-start gap-4 no-wrap"):
        with ui.column().classes("w-3/5"):
            med_round(site)
        with ui.column().classes("w-2/5"):
            change_inbox(site)
            note_box(site)
            pack_scan(site)


def med_round(site: Site) -> None:
    with card("Med round"):
        ui.label("Always the latest version. What staff see before giving each dose.").classes("text-sm text-gray-600")

        @ui.refreshable
        def body():
            state = site.state()
            flags = site.flags(state)
            now = site.now()
            for res in state.residents.values():
                rxs = [rx for rx in state.rx.values() if rx.resident_id == res.id and not rx.stopped]
                if not rxs:
                    continue
                ui.label(f"{res.name}, Room {res.room}").classes("font-bold mt-3")
                for rx in rxs:
                    mine = [f for f in flags if f.rx_id == rx.id]
                    slot = due_slot(rx, now, state.events)
                    held = blocking_flag(flags, rx.id)
                    with ui.column().classes("w-full border-t border-dashed border-gray-300 py-2 gap-1"):
                        with ui.row().classes("w-full items-center justify-between"):
                            with ui.column().classes("gap-0"):
                                ui.label(rx.drug).classes("font-bold")
                                when = "when required" if rx.prn else ", ".join(rx.times)
                                ui.label(f"{rx.dose}, {when} · v{rx.version} · stock {rx.stock}").classes(
                                    "text-sm text-gray-600")
                            chip(worst(mine))
                        for f in mine:
                            ui.label(f"{f.rule}: {f.message}").classes("text-sm")
                        with ui.row().classes("gap-2 items-center"):
                            if held and slot is not None:
                                ui.button("Record held", on_click=lambda rx=rx, s=slot: site.actions.withhold_dose(
                                    rx.resident_id, rx.id, "safety hold", slot=s)).props("dense color=red")
                            elif slot is not None:
                                ui.button(f"Give {rx.dose}", on_click=lambda rx=rx, s=slot: site.actions.give_dose(
                                    rx.resident_id, rx.id, slot=s, dose=rx.dose, version=rx.version)).props("dense")
                                ui.button("Refused", on_click=lambda rx=rx, s=slot: site.actions.withhold_dose(
                                    rx.resident_id, rx.id, "refused", slot=s)).props("dense outline")
                            elif rx.prn:
                                ui.button("Give (when required)", on_click=lambda rx=rx: site.actions.give_dose(
                                    rx.resident_id, rx.id, dose=rx.dose, version=rx.version)).props("dense outline")
                            else:
                                ui.label("Not due now").classes("text-xs text-gray-500")
                            if any(f.rule == "R5" for f in mine):
                                ui.button("Send repeat request", on_click=lambda rx=rx: site.actions.request_repeat(
                                    rx.resident_id, rx.id, **draft_repeat(rx))).props("dense outline")
        body()
        ui.timer(1.0, body.refresh)


def change_inbox(site: Site) -> None:
    with card("Change inbox"):
        ui.label("New dose changes from the GP. Tap to acknowledge.").classes("text-sm text-gray-600")

        @ui.refreshable
        def body():
            state = site.state()
            waiting = [rx for rx in state.rx.values() if rx.version > rx.acked_version]
            if not waiting:
                ui.label("Nothing new.").classes("text-gray-500")
            for rx in waiting:
                name = state.residents[rx.resident_id].name
                with ui.row().classes("items-center gap-3"):
                    changed = fmt(rx.last_changed_at) if rx.last_changed_at is not None else "?"
                    ui.label(f"{name}: {rx.drug} is now {'stopped' if rx.stopped else rx.dose} "
                             f"(v{rx.version}, {changed})").classes("font-bold text-sm")
                    ui.button("Acknowledge", on_click=lambda rx=rx: site.actions.acknowledge_change(
                        rx.resident_id, rx.id, rx.version)).props("dense")
        body()
        ui.timer(1.0, body.refresh)


def _resident_in(text: str, site: Site):
    low = text.lower()
    for res_id, names in site.aliases().items():
        if any(n and n in low for n in names):
            return res_id
    return None


def note_box(site: Site) -> None:
    notes = site.seed.get("messy_carer_notes_for_ai", [])
    with card("Messy note (AI)"):
        ui.label("Type it how you'd text a colleague. The AI drafts the records; you confirm.").classes(
            "text-sm text-gray-600")
        text = ui.textarea(value=notes[0]["note"] if notes else "").classes("w-full").props("outlined autogrow")
        result = ui.column().classes("w-full")

        def read():
            result.clear()
            with result:
                res_id = _resident_in(text.value, site)
                if res_id is None:
                    ui.label("Add the resident's name so the note can be filed.").classes("text-red-700")
                    return
                if not site.online() and llm.available():
                    ui.label("No connection: the AI can't read this now. Record the stock count by hand.").classes(
                        "text-red-700")
                    return
                state = site.state()
                rxs = [rx for rx in state.rx.values() if rx.resident_id == res_id]
                parsed = parse_note(text.value, rxs)
                if parsed is None:
                    ui.label("The AI couldn't read this note. Please record it by hand.").classes("text-red-700")
                    return
                ui.label(f"AI draft: {parsed.summary}").classes("font-bold")
                for item in parsed.items:
                    ui.label(f"• {item.kind.replace('_', ' ')}: {item.detail}   “{item.source_text}”").classes("text-sm")

                def confirm():
                    for item in parsed.items:
                        if item.kind == "refusal" and item.rx_id:
                            site.actions.withhold_dose(res_id, item.rx_id, "refused")
                    for draft in to_draft_events(parsed, res_id, text.value):
                        kind = draft["payload"]["kind"]
                        if kind == "STOCK_COUNT":
                            site.actions.record_stock_count(res_id, draft["rx_id"], draft["payload"]["stock_doses"])
                        elif kind == "NOTE":
                            site.actions.log_observation(res_id, "NOTE", draft["payload"]["summary"])
                    save.disable()
                    save.text = "Saved"
                save = ui.button("Confirm and save", on_click=confirm)
        ui.button("Read note", on_click=read)


def pack_scan(site: Site) -> None:
    with card("Scan a pack (stretch)"):
        ui.label("Choose the medicine you're giving, then scan or type the code on the pack label.").classes(
            "text-sm text-gray-600")
        state = site.state()
        options = {rx.id: f"{state.residents[rx.resident_id].name}: {rx.drug}" for rx in state.rx.values()}
        pick = ui.select(options, value=next(iter(options), None), label="Medicine").classes("w-full")
        code = ui.input("Pack code, e.g. R1|M1|warfarin|3mg|v2").classes("w-full")

        def scan(text: str):
            rx = site.state().rx.get(pick.value)
            try:
                site.actions.scan_pack(rx.resident_id, rx.id, text)
                ui.notify("Scanned. Any mismatch shows on the med round.")
            except ValueError as e:
                ui.notify(str(e), type="warning")

        async def from_photo(e):
            data = await e.file.read()
            try:
                import cv2
                import numpy as np
                img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                found, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
            except Exception:
                found = ""
            if found:
                scan(found)
            else:
                ui.notify("No pack code found in that photo. Type the code instead.", type="warning")
            upload.reset()

        ui.button("Scan typed code", on_click=lambda: scan(code.value))
        upload = ui.upload(label="Or upload a photo of the label", auto_upload=True,
                           on_upload=from_photo).props('accept="image/*"').classes("w-full")