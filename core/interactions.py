"""Small interaction table for R6."""
INTERACTIONS = [
    # (drug A, drug B, risk, action)   action: BLOCK stops dispensing; REVIEW needs a pharmacist
    ("warfarin", "ibuprofen", "Bleeding", "BLOCK"),
    ("warfarin", "naproxen", "Bleeding", "BLOCK"),
    ("warfarin", "aspirin", "Bleeding", "REVIEW"),
    ("sertraline", "tramadol", "Serotonin syndrome / seizures", "REVIEW"),
    ("sertraline", "ibuprofen", "Stomach bleeding (SSRI + NSAID)", "REVIEW"),
    ("morphine", "oxycodone", "Two opioids: breathing suppression", "REVIEW"),
]

WEEKLY_ONLY = {"methotrexate": "Must be ONCE WEEKLY. Written as daily"}

ALIASES = {"sinemet": "co-careldopa", "water tablet": "furosemide"}


def canonical(drug: str) -> str:
    name = drug.strip().lower()
    return ALIASES.get(name, name)


def matches(drug: str, name: str) -> bool:
    return canonical(drug).startswith(name)