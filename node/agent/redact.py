"""Removes residents' names from text before it is sent to the LLM.

The note box works out who a note is about locally, then sends Claude only
"the resident". Surnames, first names and nicknames (e.g. "Mags") are all removed.
"""
import re
from typing import Iterable


def redact(text: str, names: Iterable[str]) -> str:
    """Replace every name (whole words, any case, longest first) with 'the resident'."""
    out = text
    for name in sorted({n.strip() for n in names if n and n.strip()}, key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(name)}\b", "the resident", out, flags=re.IGNORECASE)
    return re.sub(r"\bthe resident the resident\b", "the resident", out)   # "Doris Patel" -> one phrase


def all_names(residents: list[dict]) -> list[str]:
    """Every name and nickname in the seed's residents list."""
    names = []
    for r in residents:
        names += [r["name"], *r["name"].split(), *r.get("aliases", [])]
    return names