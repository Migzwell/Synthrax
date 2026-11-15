"""Hold-and-confirm and never-omit lists.

Demo lists, hard-coded. Ethan signs off the grouping.
"""
from core.types import RiskGroup

HOLD_AND_CONFIRM = {
    'warfarin', 'apixaban', 'rivaroxaban', 'methotrexate',
    'morphine', 'oxycodone', 'fentanyl',
}
NEVER_OMIT = {'co-careldopa', 'sinemet', 'insulin', 'levetiracetam'}  


def risk_group_for(drug: str) -> RiskGroup:
    """Risk group for a drug name such as 'Warfarin 5mg' or 'co-careldopa 25/100'."""
    name = drug.strip().lower()
    if any(name.startswith(d) for d in NEVER_OMIT):
        return 'never_omit'
    if any(name.startswith(d) for d in HOLD_AND_CONFIRM):
        return 'hold_and_confirm'
    return 'standard'


def is_high_risk(group: RiskGroup) -> bool:
    return group in ('hold_and_confirm', 'never_omit')