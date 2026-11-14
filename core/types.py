"""Event, Rx, Resident, Flag, NodeState, SyncState."""
from typing import Any, Literal, Optional
from pydantic import BaseModel

NodeId = Literal["carehome", "gp", "pharmacy"]
RiskGroup = Literal["hold_and_confirm", "never_omit", "standard"]

EventType = Literal[
    "RX_CREATED",         # GP: payload drug, dose, times, frequency (optional, e.g. "once weekly")
    "RX_CHANGED",         # GP: payload dose, resolves (optional proposal id); seen_version = version it replaces
    "RX_STOPPED",         # GP
    "RX_CONFIRMED",       # GP: payload reason ("INR 2.6, in range, continue 5mg"); closes R1
    "RX_ACKNOWLEDGED",    # care home: payload version (R7)
    "CHANGE_PROPOSED",    # not in the Synthrax demo; kept so existing code still runs
    "DISPENSED",          # pharmacy: payload version, qty, request (optional)
    "DOSE_GIVEN",         # care home: payload slot (scheduled minute, None for PRN), given_at (minute)
    "DOSE_WITHHELD",      # care home: payload slot, reason ("refused" | "safety hold" | "asleep" | ...)
    "OBSERVATION",        # care home: payload kind (see ObservationKind) + details
    "REPEAT_REQUESTED",   # care home: payload qty, auto_drafted (bool)
    "REQUEST_APPROVED",   # GP: payload request (event id)
    "REQUEST_REJECTED",   # GP: payload request (event id)
    "SAFETY_FLAG",
    "CONFLICT_RESOLVED",  # GP reviews a conflict card after reconnect: payload group, chosen (event id), note
]

ObservationKind = Literal[
    "INR_TAKEN",          # test cases write "INR_taken": normalise with .upper() when loading
    "NOTE",               # messy carer note turned into records by the AI (payload text, summary, items)
    "PACK_SCANNED",       # payload pack_code, version, pack_resident, pack_medication (R3)
    "STOCK_COUNT",        # payload stock_doses: a counted stock level replaces the estimate (R5)
    "FALL",               # payload detail, e.g. "no injury" (slide idea: fall on warfarin)
    "REFUSING",           # payload detail
    "HOSPITAL_DISCHARGE", # payload detail
    "GP_VISIT",           # payload detail
    "LETTER_RECEIVED",    # not in the Synthrax demo
    "LETTER_READ",        # not in the Synthrax demo
]

# What a rule tells staff to do (Synthrax overview: hold, warn, block, flag).
#   HOLD   R1 warfarin, R3 pack mismatch          WARN  R2, R4, R7
#   BLOCK  R6 dangerous combination              REVIEW R6 "flag for pharmacist review"
#   INFO   R5 drafted repeat request
FlagAction = Literal["HOLD", "BLOCK", "REVIEW", "WARN", "INFO", "GIVE_AND_ESCALATE"]  # last one: not in Synthrax rules
SEVERITY = {"BLOCK": 4, "HOLD": 3, "GIVE_AND_ESCALATE": 2, "REVIEW": 2, "WARN": 1, "INFO": 0}


class Resident(BaseModel):
    id: str
    name: str
    age: int
    room: str


class Event(BaseModel):
    id: str                          # uuid4 string; same id = same event everywhere
    resident_id: str
    rx_id: Optional[str] = None      # test cases: medication_id
    type: EventType
    payload: dict[str, Any] = {}
    author: NodeId
    created_at: int                  # demo-clock minutes
    lamport: int = 0                 # display order only
    seen_version: Optional[int] = None


class Rx(BaseModel):
    id: str
    resident_id: str
    drug: str
    dose: str
    times: list[str] = []            # empty = PRN ("when required"): never late (R4), no stock maths (R5)
    frequency: Optional[str] = None  # e.g. "once weekly"; R6 checks methotrexate
    version: int = 1
    risk_group: RiskGroup = "standard"
    stopped: bool = False
    stock: int = 0                   # test cases: stock_doses
    acked_version: int = 1
    dispensed_version: int = 1
    last_changed_at: Optional[int] = None

    @property
    def prn(self) -> bool:
        return not self.times


class NodeState(BaseModel):
    residents: dict[str, Resident] = {}
    rx: dict[str, Rx] = {}
    events: list[Event] = []
    pending: dict[str, Event] = {}
    open_requests: dict[str, Event] = {}
    approved_requests: dict[str, Event] = {}
    unread_letters: dict[str, Event] = {}
    resolved_groups: set[str] = set()


class SyncState(BaseModel):
    online: bool = True
    last_seen: dict[str, int] = {}   # peer -> demo minute of last successful sync


class Flag(BaseModel):
    rule: str
    rx_id: Optional[str] = None
    resident_id: Optional[str] = None
    action: FlagAction
    message: str