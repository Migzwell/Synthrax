"""Med round, letter, note, verbal, pack scan."""
from nicegui import run, ui

from core.rules import blocking_flag
from core.rules.r5 import draft_repeat
from core.schedule import due_slot
from node.agent import llm
from node.agent.redact import all_names, redact
from node.agent.parse_note import parse_note, to_draft_events
from node.clock_client import fmt, minute_of
from node.qr_read import read_pack_codes
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
                            record = _last_record_today(rx, state.events, now)
                            safety_held = (record is not None and record.type == "DOSE_WITHHELD"
                                           and record.payload.get("reason") == "safety hold")
                            chip("HOLD" if safety_held and worst(mine) in ("OK", "INFO", "WARN") else worst(mine))
                        if record is not None:
                            when = fmt(record.payload.get("slot") or record.created_at).replace(" today", "")
                            if safety_held:
                                ui.label(f"Held at {when} for safety. Waiting for the prescriber to confirm the dose."
                                         ).classes("text-sm font-bold text-red-700")
                            elif record.type == "DOSE_WITHHELD":
                                ui.label(f"Not given at {when} ({record.payload.get('reason')}).").classes(
                                    "text-sm text-gray-600")
                            else:
                                given = fmt(record.payload.get("given_at", record.created_at)).replace(" today", "")
                                ui.label(f"Given at {given}.").classes("text-sm text-emerald-700")
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


def _last_record_today(rx, events, now):
    """The latest dose given or not given today for this medicine, if any."""
    start = ((now + 14 * 60) // 1440) * 1440 - 14 * 60          # 00:00 today in demo minutes
    found = [e for e in events if e.rx_id == rx.id and e.type in ("DOSE_GIVEN", "DOSE_WITHHELD")
             and (e.payload.get("slot") if e.payload.get("slot") is not None else e.created_at) >= start]
    return max(found, key=lambda e: (e.created_at, e.lamport)) if found else None


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


SOURCE_LABEL = {"live": "Claude (live)", "cached": "Claude (cached example answer)"}


def note_box(site: Site) -> None:
    notes = [n["note"] for n in site.seed.get("messy_carer_notes_for_ai", []) if "_comment" not in n]
    with card("Messy note (AI)"):
        ui.label("Type it how you'd text a colleague. Claude drafts the records; you check and confirm. "
                 "Names are removed before anything leaves this computer.").classes("text-sm text-gray-600")
        if notes:
            examples = ui.row().classes("gap-1")
            with examples:
                ui.label("Examples:").classes("text-xs text-gray-500")
                for i, n in enumerate(notes):
                    ui.button(f"{i + 1}", on_click=lambda n=n: setattr(text, "value", n)).props("dense flat size=sm")
        text = ui.textarea(value=notes[0] if notes else "").classes("w-full").props("outlined autogrow")
        result = ui.column().classes("w-full")

        async def read():
            result.clear()
            with result:
                res_id = _resident_in(text.value, site)
                if res_id is None:
                    ui.label("Add the resident's name so the note can be filed.").classes("text-red-700")
                    return
                if not site.online() and llm.status() == "live":
                    ui.label("No connection, so Claude can't read this now. Use the form below.").classes(
                        "text-red-700")
                    manual_form(site, res_id)
                    return
                state = site.state()
                rxs = [rx for rx in state.rx.values() if rx.resident_id == res_id]
                safe_text = redact(text.value, all_names(site.seed.get("residents", [])))
                spinner = ui.spinner(size="lg")
                parsed = await run.io_bound(parse_note, safe_text, rxs)
                spinner.delete()
                if parsed is None:
                    ui.label("Claude couldn't read this note, so nothing was guessed. Use the form below.").classes(
                        "text-red-700")
                    manual_form(site, res_id)
                    return
                name = state.residents[res_id].name
                with ui.row().classes("items-center gap-2"):
                    ui.label(f"Draft for {name}").classes("font-bold")
                    ui.label(SOURCE_LABEL.get(llm.last_source, "Claude")).classes(
                        "px-2 py-0.5 rounded text-xs font-bold bg-violet-100 text-violet-800")
                ui.label(parsed.summary).classes("text-sm")
                ui.label(f"Sent to Claude: “{safe_text.strip()}”").classes("text-xs text-gray-500")
                for item in parsed.items:
                    times = ""
                    if item.kind == "dose_given" and (item.scheduled_time or item.given_at):
                        times = f" (due {item.scheduled_time or '?'}, given {item.given_at or 'now'})"
                    ui.label(f"• {item.kind.replace('_', ' ')}: {item.detail}{times}   “{item.source_text}”").classes(
                        "text-sm")

                def confirm():
                    saved = save_items(site, res_id, parsed)
                    save.disable()
                    save.text = "Saved"
                    ui.notify(f"Saved {saved} record(s). The safety rules re-check straight away.")
                save = ui.button("Confirm and save", on_click=confirm)
                ui.label("Nothing is recorded until you confirm.").classes("text-xs text-gray-500")
        ui.button("Read note", on_click=read)
        with ui.expansion("Record by hand instead").classes("w-full text-sm"):
            state = site.state()
            pick = ui.select({r.id: r.name for r in state.residents.values()},
                             value=next(iter(state.residents), None), label="Resident").classes("w-full")
            holder = ui.column().classes("w-full")

            def show():
                holder.clear()
                with holder:
                    manual_form(site, pick.value)
            pick.on_value_change(lambda _: show())
            show()


def save_items(site: Site, res_id: str, parsed) -> int:
    """Turn a confirmed AI draft into records. Returns how many were saved."""
    saved = 0
    for item in parsed.items:
        try:
            if item.kind == "refusal" and item.rx_id:
                site.actions.withhold_dose(res_id, item.rx_id, "refused")
            elif item.kind == "dose_given" and item.rx_id:
                rx = site.state().rx[item.rx_id]
                slot = minute_of(item.scheduled_time) if item.scheduled_time else None
                given = minute_of(item.given_at) if item.given_at else None
                site.actions.give_dose(res_id, item.rx_id, slot=slot, dose=rx.dose, version=rx.version,
                                       given_at=given)
            elif item.kind == "fall":
                site.actions.log_observation(res_id, "FALL", item.detail)
            else:
                continue
            saved += 1
        except ValueError as e:
            ui.notify(f"Not saved: {item.detail} ({e})", type="warning")
    for draft in to_draft_events(parsed, res_id, ""):
        if draft["payload"]["kind"] == "STOCK_COUNT":
            site.actions.record_stock_count(res_id, draft["rx_id"], draft["payload"]["stock_doses"])
            saved += 1
    site.actions.log_observation(res_id, "NOTE", parsed.summary)
    return saved + 1


def manual_form(site: Site, res_id: str) -> None:
    """The fallback when the AI is unavailable or unsure: the same records, entered by hand."""
    state = site.state()
    meds = {rx.id: rx.drug for rx in state.rx.values() if rx.resident_id == res_id}
    with ui.column().classes("w-full gap-1 border border-dashed border-gray-300 rounded p-2"):
        med = ui.select(meds, value=next(iter(meds), None), label="Medicine").classes("w-full")
        what = ui.select({"refused": "Refused a dose", "stock": "Stock count", "fall": "Had a fall"},
                         value="refused", label="What happened").classes("w-full")
        count = ui.number("Doses left (for a stock count)", min=0, value=None).classes("w-full")

        def save():
            if what.value == "refused":
                site.actions.withhold_dose(res_id, med.value, "refused")
            elif what.value == "stock":
                if count.value is None:
                    ui.notify("Enter how many doses are left.", type="warning")
                    return
                site.actions.record_stock_count(res_id, med.value, int(count.value))
            else:
                site.actions.log_observation(res_id, "FALL", "Recorded by hand")
            ui.notify("Saved.")
        ui.button("Save", on_click=save).props("dense outline")


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

        choices = ui.column().classes("w-full")

        async def from_photo(e):
            data = await e.file.read()
            upload.reset()
            choices.clear()
            try:
                found = read_pack_codes(data)
            except Exception:
                found = []
            if not found:
                ui.notify("No pack code found. Photograph one label close up (the pharmacy's "
                          "'Show large' helps), or type the code instead.", type="warning")
            elif len(found) == 1:
                code.value = found[0]
                scan(found[0])
            else:
                with choices:
                    ui.label(f"{len(found)} pack codes in that photo. Which pack are you holding?").classes(
                        "text-sm font-bold")
                    for text in found:
                        ui.button(text, on_click=lambda t=text: (scan(t), choices.clear())).props(
                            "dense outline no-caps").classes("font-mono text-xs")

        ui.button("Scan typed code", on_click=lambda: scan(code.value))
        upload = ui.upload(label="Or upload a photo of the label", auto_upload=True,
                           on_upload=from_photo).props('accept="image/*"').classes("w-full")