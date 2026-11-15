"""Everything a person can do at a site, as safe one-line calls for the screens."""
import re
import uuid
from typing import Callable, Optional

from core.types import Event
from .store import EventStore

# Which site may do what. "Only the GP changes medicines" (Synthrax overview).
ALLOWED = {
    "give_dose": {"carehome"},
    "withhold_dose": {"carehome"},
    "acknowledge_change": {"carehome"},
    "request_repeat": {"carehome"},
    "log_observation": {"carehome"},
    "log_inr_taken": {"carehome"},
    "record_stock_count": {"carehome"},
    "scan_pack": {"carehome"},
    "prescribe": {"gp"},
    "change_dose": {"gp"},
    "confirm_no_change": {"gp"},
    "stop_medicine": {"gp"},
    "approve_request": {"gp"},
    "reject_request": {"gp"},
    "review_conflict": {"gp"},
    "dispense": {"pharmacy"},
}
SITE_NAMES = {"carehome": "the care home", "gp": "the GP", "pharmacy": "the pharmacy"}

# Vocabulary from seed_data.json
WITHHELD_REASONS = {"refused", "asleep", "safety hold", "in hospital"}
OBSERVATION_KINDS = {"INR_TAKEN", "HOSPITAL_DISCHARGE", "GP_VISIT", "FALL", "STOCK_COUNT", "REFUSING", "NOTE"}
PACK_CODE = re.compile(r"(?P<resident>[^|]+)\|(?P<medication>[^|]+)\|(?P<drug>[^|]+)\|(?P<dose>[^|]+)\|v(?P<version>\d+)")


def pack_code(resident_id: str, rx_id: str, drug: str, dose: str, version: int) -> str:
    """e.g. 'R1|M1|warfarin|3mg|v2', the format printed on pharmacy labels."""
    return f"{resident_id}|{rx_id}|{drug.lower()}|{dose}|v{version}"


class Actions:
    def __init__(self, node_id: str, store: EventStore, now: Callable[[], int]):
        self.node_id = node_id
        self.store = store
        self.now = now                       # the demo clock

    # ---------- the one place events are made ----------

    def _emit(self, action: str, type_: str, resident_id: str, rx_id: Optional[str] = None,
              payload: Optional[dict] = None, seen_version: Optional[int] = None) -> Event:
        if self.node_id not in ALLOWED[action]:
            who = " or ".join(SITE_NAMES[s] for s in sorted(ALLOWED[action]))
            raise PermissionError(f"Only {who} can {action.replace('_', ' ')}.")
        event = Event(id=str(uuid.uuid4()), resident_id=resident_id, rx_id=rx_id, type=type_,
                      payload=payload or {}, author=self.node_id, created_at=self.now(),
                      lamport=self.store.max_lamport() + 1, seen_version=seen_version)
        self.store.add(event)
        return event

    # ---------- care home ----------

    def give_dose(self, resident_id: str, rx_id: str, slot: Optional[int] = None,
                  dose: str = "", version: int = 1, staff_name: str = "") -> Event:
        """Record a dose as given. `slot` is when it was due (None for when-required medicines)."""
        return self._emit("give_dose", "DOSE_GIVEN", resident_id, rx_id,
                          {"slot": slot, "given_at": self.now(), "dose": dose, "version": version,
                           "staff_name": staff_name})

    def withhold_dose(self, resident_id: str, rx_id: str, reason: str, slot: Optional[int] = None,
                      staff_name: str = "") -> Event:
        """Record a dose not given: refused, asleep, safety hold or in hospital."""
        reason = reason.strip().replace("_", " ").lower()
        if reason not in WITHHELD_REASONS:
            raise ValueError(f"Reason must be one of: {', '.join(sorted(WITHHELD_REASONS))}.")
        return self._emit("withhold_dose", "DOSE_WITHHELD", resident_id, rx_id,
                          {"slot": slot, "reason": reason, "staff_name": staff_name})

    def acknowledge_change(self, resident_id: str, rx_id: str, version: int, staff_name: str = "") -> Event:
        """The 'Acknowledge' tap in the change inbox (clears R7 at the GP)."""
        return self._emit("acknowledge_change", "RX_ACKNOWLEDGED", resident_id, rx_id,
                          {"version": version, "staff_name": staff_name})

    def request_repeat(self, resident_id: str, rx_id: str, qty: int, auto_drafted: bool = False) -> Event:
        return self._emit("request_repeat", "REPEAT_REQUESTED", resident_id, rx_id,
                          {"qty": qty, "auto_drafted": auto_drafted})

    def log_observation(self, resident_id: str, kind: str, detail: str = "",
                        rx_id: Optional[str] = None) -> Event:
        """INR taken, hospital discharge, GP visit, fall, stock count or refusing."""
        kind = kind.strip().upper()
        if kind not in OBSERVATION_KINDS:
            raise ValueError(f"Kind must be one of: {', '.join(sorted(OBSERVATION_KINDS))}.")
        return self._emit("log_observation", "OBSERVATION", resident_id, rx_id, {"kind": kind, "detail": detail})

    def log_inr_taken(self, resident_id: str, rx_id: str, detail: str = "") -> Event:
        """An INR blood test was taken: R1 now expects a dosing instruction."""
        return self._emit("log_inr_taken", "OBSERVATION", resident_id, rx_id,
                          {"kind": "INR_TAKEN", "detail": detail})

    def record_stock_count(self, resident_id: str, rx_id: str, stock_doses: int) -> Event:
        if stock_doses < 0:
            raise ValueError("Stock can't be negative.")
        return self._emit("record_stock_count", "OBSERVATION", resident_id, rx_id,
                          {"kind": "STOCK_COUNT", "stock_doses": stock_doses})

    def scan_pack(self, resident_id: str, rx_id: str, code: str) -> Event:
        """A pack label was scanned while giving `rx_id` to `resident_id`. R3 compares the pack's
        resident, medication and version with the record (newer, older or wrong pack)."""
        m = PACK_CODE.fullmatch(code.strip())
        if not m:
            raise ValueError("That isn't a Synthrax pack code (expected e.g. R1|M1|warfarin|3mg|v2).")
        return self._emit("scan_pack", "OBSERVATION", resident_id, rx_id,
                          {"kind": "PACK_SCANNED", "pack_code": code.strip(), "version": int(m["version"]),
                           "pack_resident": m["resident"], "pack_medication": m["medication"]})

    # ---------- GP ----------

    def prescribe(self, resident_id: str, drug: str, dose: str, times: Optional[list] = None,
                  frequency: str = "") -> Event:
        """A new medicine. Gets the next free id (M8, M9...). The pharmacy's R6 checks it before dispensing."""
        if not drug.strip() or not dose.strip():
            raise ValueError("A drug and a dose are needed.")
        used = {e.rx_id for e in self.store.all() if e.type == "RX_CREATED" and e.rx_id}
        n = len(used) + 1
        while f"M{n}" in used:
            n += 1
        return self._emit("prescribe", "RX_CREATED", resident_id, f"M{n}",
                          {"drug": drug.strip(), "dose": dose.strip(), "times": list(times or []),
                           "frequency": frequency.strip() or None, "needs_ack": True})

    def change_dose(self, resident_id: str, rx_id: str, dose: str, seen_version: int,
                    old_dose: str = "", reason: str = "") -> Event:
        """`seen_version` is the version being replaced; that's how conflicts are detected."""
        if not dose.strip():
            raise ValueError("A new dose is needed.")
        return self._emit("change_dose", "RX_CHANGED", resident_id, rx_id,
                          {"dose": dose, "old_dose": old_dose, "reason": reason}, seen_version=seen_version)

    def confirm_no_change(self, resident_id: str, rx_id: str, reason: str, version: int = 1) -> Event:
        """e.g. 'INR 2.6, in range, continue 5mg' (closes R1)."""
        return self._emit("confirm_no_change", "RX_CONFIRMED", resident_id, rx_id,
                          {"reason": reason, "version": version})

    def stop_medicine(self, resident_id: str, rx_id: str, reason: str = "") -> Event:
        return self._emit("stop_medicine", "RX_STOPPED", resident_id, rx_id, {"reason": reason})

    def approve_request(self, resident_id: str, request_id: str, rx_id: Optional[str] = None) -> Event:
        return self._emit("approve_request", "REQUEST_APPROVED", resident_id, rx_id, {"request": request_id})

    def reject_request(self, resident_id: str, request_id: str, reason: str = "",
                       rx_id: Optional[str] = None) -> Event:
        return self._emit("reject_request", "REQUEST_REJECTED", resident_id, rx_id,
                          {"request": request_id, "reason": reason})

    def review_conflict(self, resident_id: str, rx_id: str, group: str, chosen: str, note: str = "") -> Event:
        """The GP's decision on a conflict card after reconnect."""
        return self._emit("review_conflict", "CONFLICT_RESOLVED", resident_id, rx_id,
                          {"group": group, "chosen": chosen, "note": note})

    # ---------- pharmacy ----------

    def dispense(self, resident_id: str, rx_id: str, version: int, qty: int, drug: str = "",
                 dose: str = "", request_id: Optional[str] = None) -> Event:
        """A new pack. With drug and dose, the label's pack code is added (e.g. R1|M1|warfarin|3mg|v2)."""
        payload = {"version": version, "qty": qty}
        if drug and dose:
            payload["pack_code"] = pack_code(resident_id, rx_id, drug, dose, version)
        if request_id:
            payload["request"] = request_id
        return self._emit("dispense", "DISPENSED", resident_id, rx_id, payload)