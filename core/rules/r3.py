"""R3: pack/record mismatch.

Needs pack codes. A scan is an OBSERVATION with payload
{'kind': 'PACK_SCANNED', 'version': N, 'pack_resident': '<resident id>'}
and rx_id set to the medicine it was scanned against. R3 looks at the
latest scan for each medicine.

Wrong resident's pack -> don't use this pack.
Newer pack            -> a change exists that the home has not received.
Older pack            -> don't use this pack.

Hold-and-confirm and standard medicines get HOLD. Never-omit medicines are
never held: they get GIVE_AND_ESCALATE with wording that says which pack
or dose to use.
"""
from core.rules.common import active_rxs, observations
from core.types import Flag, NodeState, SyncState

MSG_WRONG_RESIDENT = ("{drug}: don't use this pack. It was dispensed for another resident. "
                      "Find this resident's own pack.")
MSG_NEWER = ("HOLD {drug}. Pack is v{pack}, your record is v{rec}: a change exists you "
             "haven't received. Confirm the dose with the prescriber before giving.")
MSG_OLDER = ("{drug}: don't use this pack. Pack is v{pack}, your record is v{rec}. "
             "Ask the pharmacy for the current pack.")
MSG_NEVER_OMIT_NEWER = ("GIVE {drug} ON TIME at the last confirmed dose. Pack is v{pack}, your "
                        "record is v{rec}: a change exists you haven't received. "
                        "Confirm the dose with the prescriber now.")
MSG_NEVER_OMIT_BAD_PACK = ("{drug} must not be missed, but don't use this pack ({why}). "
                           "Give on time from the correct pack and tell the pharmacy now.")


def check(state: NodeState, now: int, sync: SyncState) -> list[Flag]:
    flags = []
    for rx in active_rxs(state):
        scans = observations(state, rx.id, 'PACK_SCANNED')
        if not scans:
            continue
        scan = scans[-1].payload
        never_omit = rx.risk_group == 'never_omit'
        pack_resident = scan.get('pack_resident')
        pack = scan.get('version')
        text = dict(drug=rx.drug, pack=pack, rec=rx.version)

        if pack_resident and pack_resident != rx.resident_id:
            msg = (MSG_NEVER_OMIT_BAD_PACK.format(why='dispensed for another resident', **text)
                   if never_omit else MSG_WRONG_RESIDENT.format(**text))
        elif pack is None or int(pack) == rx.version:
            continue
        elif int(pack) > rx.version:
            msg = (MSG_NEVER_OMIT_NEWER if never_omit else MSG_NEWER).format(**text)
        else:
            msg = (MSG_NEVER_OMIT_BAD_PACK.format(why=f'pack is v{pack}, record is v{rx.version}', **text)
                   if never_omit else MSG_OLDER.format(**text))
        flags.append(Flag(
            rule='R3',
            rx_id=rx.id,
            resident_id=rx.resident_id,
            action='GIVE_AND_ESCALATE' if never_omit else 'HOLD',
            message=msg,
        ))
    return flags
