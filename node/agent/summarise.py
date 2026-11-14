"""GP inbox summary.

summarise() gives the GP three short lines on a resident's recent events
plus an urgency for triage. It always returns a Summary: if the LLM is
unavailable or its output fails validation, a rule-based summary is used
(worse wording, same facts). summary.source says which one the GP is reading.

The summary is a reading aid only. It never changes a record.
"""
import json

from pydantic import ValidationError

from core.schedule import hhmm
from core.types import Event, Rx
from node.agent import llm
from node.agent.schemas import Summary

MAX_EVENTS = 30

SYSTEM = """You summarise recent medicines events for one care home resident so a GP
can triage their inbox. Reply with one JSON object and nothing else:
{"lines": ["<line 1>", "<line 2>", "<line 3>"], "urgency": "routine" | "soon" | "urgent"}
Rules:
- Exactly 3 lines, each under 140 characters, plain clinical English.
- Line 1: the most important thing the GP needs to know. Line 2: what the
  care home has done or given. Line 3: what is waiting for the GP.
- Use only facts in the events. If nothing is waiting, say so.
- "urgent" if there is a safety flag, a withheld high-risk medicine or a missed
  never-omit medicine; "soon" if a request or proposed change is waiting.
- Do not recommend doses or treatment."""


def _drug(e: Event, rxs: dict[str, Rx]) -> str:
    rx = rxs.get(e.rx_id or '')
    return rx.drug if rx else (e.payload.get('drug') or 'medicine')


def _event_line(e: Event, rxs: dict[str, Rx]) -> dict:
    # Data minimisation: no resident name or id, only what the summary needs.
    keep = ('kind', 'dose', 'reason', 'summary', 'stock_doses', 'version', 'qty',
            'rule', 'action', 'message')
    return {'time': hhmm(e.created_at), 'type': e.type, 'drug': _drug(e, rxs),
            'by': e.author, **{k: e.payload[k] for k in keep if k in e.payload}}


def rule_based_summary(events: list[Event], rxs: dict[str, Rx]) -> Summary:
    """Deterministic fallback. Works offline and with the LLM switched off."""
    flags = [e for e in events if e.type == 'SAFETY_FLAG']
    withheld = [e for e in events if e.type == 'DOSE_WITHHELD']
    given = [e for e in events if e.type == 'DOSE_GIVEN']
    observations = [e for e in events if e.type == 'OBSERVATION']
    proposals = [e for e in events if e.type == 'CHANGE_PROPOSED']
    requests = [e for e in events if e.type == 'REPEAT_REQUESTED']

    if flags:
        last = flags[-1]
        line1 = f'{len(flags)} safety flag(s); latest: {_drug(last, rxs)} at {hhmm(last.created_at)}.'
    elif observations:
        last = observations[-1]
        what = (last.payload.get('summary')
                or str(last.payload.get('kind', 'observation')).replace('_', ' ').lower())
        line1 = f'Latest observation at {hhmm(last.created_at)}: {what}.'
    else:
        line1 = 'No safety flags or new observations.'

    if withheld:
        last = withheld[-1]
        reason = last.payload.get('reason', 'reason not recorded')
        line2 = (f'{len(given)} dose(s) given, {len(withheld)} withheld; '
                 f'latest withheld: {_drug(last, rxs)} ({reason}).')
    else:
        line2 = f'{len(given)} dose(s) given, none withheld.'

    waiting = []
    if proposals:
        waiting.append(f'{len(proposals)} proposed change(s)')
    if requests:
        waiting.append(f'{len(requests)} repeat request(s)')
    line3 = ('Waiting for you: ' + ' and '.join(waiting) + '.') if waiting else 'Nothing waiting for you.'

    urgency = 'urgent' if flags else ('soon' if waiting or withheld else 'routine')
    lines = [line[:157] + '...' if len(line) > 160 else line for line in (line1, line2, line3)]
    return Summary(lines=lines, urgency=urgency, source='rules')


def summarise(events: list[Event], rxs: dict[str, Rx]) -> Summary:
    """Three-line summary of one resident's recent events. Never returns None."""
    recent = sorted(events, key=lambda e: (e.created_at, e.lamport))[-MAX_EVENTS:]
    fallback = rule_based_summary(recent, rxs)
    if not recent:
        return fallback
    user = 'Events, oldest first:\n' + json.dumps([_event_line(e, rxs) for e in recent])
    raw = llm.complete_json(SYSTEM, user)
    if raw is None:
        return fallback
    try:
        summary = Summary.model_validate({**raw, 'source': 'llm'})
    except ValidationError:
        return fallback
    # The rules, not the model, have the last word on urgency going down.
    if fallback.urgency == 'urgent':
        summary.urgency = 'urgent'
    return summary
