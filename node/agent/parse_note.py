"""Carer note -> structured items.

parse_note() turns a messy note ("Doris refusing her water tablet, only 3
left") into validated items. to_draft_events() turns those into draft
OBSERVATION events (one NOTE, plus a STOCK_COUNT per counted medicine) for
staff to confirm. Nothing here writes to the log:
the UI shows the drafts next to the source text and a human confirms.

Returns None when the LLM is unavailable or its output fails validation;
the UI then shows the manual form.
"""
import json
from typing import Optional

from pydantic import ValidationError

from core.types import Rx
from node.agent import llm
from node.agent.schemas import NoteParse

SYSTEM = """You turn a care home carer's free-text note into structured items.
Reply with one JSON object and nothing else:
{"summary": "<one short line summing up the note>",
 "items": [{"kind": "refusal" | "stock_count" | "fall" | "symptom" | "other",
            "rx_id": "<id from the medicines list, or null>",
            "drug": "<drug name, or null>",
            "detail": "<one short plain-English sentence>",
            "count": <number of doses left, only for stock_count, else null>,
            "source_text": "<the exact words in the note this item came from>"}]}
Rules:
- One item per separate fact. A refusal and a stock level are two items.
- Match everyday names to the medicines list (e.g. "water tablet" is a diuretic).
  If you are not sure which medicine is meant, use null for rx_id and drug.
- Only use rx_id values that appear in the medicines list.
- Record what the note says. Do not give advice, doses or instructions."""


def _user_prompt(note: str, rxs: list[Rx]) -> str:
    # Data minimisation: medicines and the note only. No name, age or room.
    meds = [{'rx_id': rx.id, 'drug': rx.drug, 'dose': rx.dose} for rx in rxs]
    return f'Medicines list:\n{json.dumps(meds)}\n\nCarer note:\n{note.strip()}'


def parse_note(note: str, rxs: list[Rx]) -> Optional[NoteParse]:
    """Structured items from a carer note, or None to fall back to the manual form."""
    if not note or not note.strip():
        return None
    raw = llm.complete_json(SYSTEM, _user_prompt(note, rxs), fixture_text=note)
    if raw is None:
        return None
    try:
        parsed = NoteParse.model_validate(raw)
    except ValidationError:
        return None
    known = {rx.id: rx for rx in rxs}
    for item in parsed.items:
        if item.rx_id not in known:
            item.rx_id = None        # never trust an id the model made up
        else:
            item.drug = known[item.rx_id].drug
    return parsed


def to_draft_events(parsed: NoteParse, resident_id: str, note: str) -> list[dict]:
    """Draft OBSERVATION events for staff to confirm.

    Always one NOTE (payload text, summary, items). Each stock count that
    names a known medicine also gets a STOCK_COUNT (payload stock_doses),
    which replaces the stock estimate and so feeds rule R5.
    The UI adds id, author, created_at and lamport when staff confirm.
    """
    drafts = [{
        'type': 'OBSERVATION',
        'resident_id': resident_id,
        'rx_id': None,
        'payload': {
            'kind': 'NOTE',
            'text': note.strip(),
            'summary': parsed.summary,
            'items': [item.model_dump() for item in parsed.items],
        },
    }]
    for item in parsed.items:
        if item.kind == 'stock_count' and item.count is not None and item.rx_id is not None:
            drafts.append({
                'type': 'OBSERVATION',
                'resident_id': resident_id,
                'rx_id': item.rx_id,
                'payload': {'kind': 'STOCK_COUNT', 'stock_doses': item.count,
                            'source_text': item.source_text},
            })
    return drafts
