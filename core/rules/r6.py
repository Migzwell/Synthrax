"""R6: interaction check.

Pharmacy only. Runs on every changed or new prescription waiting to be dispensed
(version newer than the last pack), against all of that resident's current medicines.
A dangerous pair or methotrexate written as daily -> BLOCK (no dispensing) or REVIEW.
"""
from core.interactions import INTERACTIONS, WEEKLY_ONLY, matches
from core.rules.common import active_rxs
from core.types import Flag, NodeState, SyncState

MSG_PAIR = "{drug} with {other}: {risk} risk. {what}"
MSG_WEEKLY = "{drug}: {risk} ('{freq}'). Do not dispense: confirm with the prescriber."
WHAT = {"BLOCK": "Do not dispense: contact the prescriber.",
        "REVIEW": "Pharmacist review needed before dispensing."}


def check(state: NodeState, now: int, sync: SyncState) -> list[Flag]:
    flags = []
    meds = active_rxs(state)
    for rx in meds:
        if rx.version <= rx.dispensed_version:
            continue                                    # nothing new waiting to be dispensed
        for name, risk in WEEKLY_ONLY.items():
            freq = (rx.frequency or "").lower()
            if matches(rx.drug, name) and "daily" in freq and "week" not in freq:
                flags.append(Flag(rule="R6", rx_id=rx.id, resident_id=rx.resident_id, action="BLOCK",
                                  message=MSG_WEEKLY.format(drug=rx.drug, risk=risk, freq=rx.frequency)))
        # Check against what the resident already has (dispensed), so a new risky medicine is flagged
        # and an unrelated, already-safe change (e.g. warfarin 5mg -> 3mg) isn't held up by it.
        others = [o for o in meds if o.resident_id == rx.resident_id and o.id != rx.id and o.dispensed_version > 0]
        for a, b, risk, action in INTERACTIONS:
            for other in others:
                if (matches(rx.drug, a) and matches(other.drug, b)) or (matches(rx.drug, b) and matches(other.drug, a)):
                    flags.append(Flag(rule="R6", rx_id=rx.id, resident_id=rx.resident_id, action=action,
                                      message=MSG_PAIR.format(drug=rx.drug, other=other.drug, risk=risk,
                                                              what=WHAT[action])))
    return flags