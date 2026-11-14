"""The one place that calls the LLM.

Everything else in node/agent/ goes through complete_json(). It returns a
dict, or None when there is no usable answer (no key, offline, timeout,
bad JSON). Callers treat None as "fall back": a manual form or a
rule-based result. It never raises.

DEMO_MODE=1 -> known demo inputs return the cached answer in fixtures/
               and the API is never called.
DEMO_MODE=0 -> call the API; if that fails, still try the fixture.

The API key is read from the environment on the node and never reaches
the browser. Swap providers by editing _call_api() only.
"""
import json
import os
from pathlib import Path
from typing import Optional

try:                                # .env is optional in tests
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:                 # pragma: no cover
    pass

FIXTURES = Path(__file__).parent / 'fixtures'
API_URL = 'https://api.anthropic.com/v1/messages'
DEFAULT_MODEL = 'claude-haiku-5-5'
TIMEOUT_SECONDS = 20


def demo_mode() -> bool:
    return os.environ.get('DEMO_MODE', '1').split('#')[0].strip().lower() in ('1', 'true', 'yes')


def available() -> bool:
    """True if a live LLM call could be made. The UI can use this to show
    'Needs a connection' on LLM buttons."""
    return bool(os.environ.get('LLM_API_KEY', '').strip()) and not demo_mode()


def _normalise(text: str) -> str:
    return ' '.join(text.lower().split())


def fixture_for(text: str) -> Optional[dict]:
    """Cached answer for a known demo input: fixtures/NAME.txt -> fixtures/NAME.json."""
    wanted = _normalise(text)
    if not wanted:
        return None
    for txt in sorted(FIXTURES.glob('*.txt')):
        try:
            if _normalise(txt.read_text(encoding='utf-8')) != wanted:
                continue
            data = json.loads(txt.with_suffix('.json').read_text(encoding='utf-8'))
            return data if isinstance(data, dict) and data else None
        except (OSError, ValueError):
            return None
    return None


def extract_json(text: str) -> Optional[dict]:
    """Pull the first JSON object out of a model reply (handles code fences and chatter)."""
    start, end = text.find('{'), text.rfind('}')
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _call_api(system: str, user: str) -> Optional[str]:
    """Provider-specific part: Anthropic Messages API over httpx. Returns reply text."""
    key = os.environ.get('LLM_API_KEY', '').strip()
    if not key:
        return None
    import httpx                    # imported here so tests run without it
    response = httpx.post(
        API_URL,
        headers={
            'x-api-key': key,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json',
        },
        json={
            'model': os.environ.get('LLM_MODEL', DEFAULT_MODEL),
            'max_tokens': 1024,
            'system': system,
            'messages': [{'role': 'user', 'content': user}],
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    blocks = response.json().get('content', [])
    return ''.join(b.get('text', '') for b in blocks if b.get('type') == 'text')


def complete_json(system: str, user: str, fixture_text: str = '') -> Optional[dict]:
    """Ask the LLM for a JSON object.

    fixture_text is the raw input (the note or letter) used to look up a
    cached demo answer. Returns None on any failure.
    """
    cached = fixture_for(fixture_text) if fixture_text else None
    if demo_mode():
        return cached
    try:
        reply = _call_api(system, user)
    except Exception:               # network, HTTP status, timeout, bad payload
        reply = None
    parsed = extract_json(reply) if reply else None
    return parsed if parsed is not None else cached
