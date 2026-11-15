"""Pydantic models for LLM output.

No free-text model output becomes a record: every reply is validated
against one of these, and anything that fails falls back to a manual form.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

NoteKind = Literal['refusal', 'stock_count', 'fall', 'symptom', 'other']


class NoteItem(BaseModel):
    kind: NoteKind
    rx_id: Optional[str] = None      # one of the resident's medicines, or None
    drug: Optional[str] = None       # drug name as understood
    detail: str = Field(min_length=1, max_length=200)   # short plain-English summary
    count: Optional[int] = Field(default=None, ge=0, le=1000)   # for stock_count
    source_text: str = Field(min_length=1)   # the words in the note this came from


class NoteParse(BaseModel):
    summary: str = Field(min_length=1, max_length=200)   # one line for the record
    items: list[NoteItem] = Field(max_length=10)

Urgency = Literal['routine', 'soon', 'urgent']


class Summary(BaseModel):
    lines: list[str]                 # exactly 3 short lines
    urgency: Urgency = 'routine'
    source: Literal['llm', 'rules'] = 'llm'   # shown to the GP

    @field_validator('lines')
    @classmethod
    def three_short_lines(cls, lines: list[str]) -> list[str]:
        lines = [' '.join(str(line).split()) for line in lines]
        if len(lines) != 3 or not all(lines):
            raise ValueError('summary must have exactly 3 non-empty lines')
        if any(len(line) > 160 for line in lines):
            raise ValueError('summary lines must be 160 characters or fewer')
        return lines
