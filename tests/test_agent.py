"""Agent layer: note parsing and GP summary, with the LLM mocked or off."""
import pytest

from core.schedule import at
from core.types import Event
from node.agent import llm, parse_note as pn, summarise as sm
from node.agent.parse_note import parse_note, to_draft_events
from node.agent.summarise import summarise
from tests.factories import FUROSEMIDE, WARFARIN, demo_state, ev

NOTE = 'Doris refusing her water tablet this morning, only 3 left in the pack'


@pytest.fixture
def doris_rxs():
    return [rx for rx in demo_state().rx.values() if rx.resident_id == 'doris']


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setenv('DEMO_MODE', '1')
    monkeypatch.delenv('LLM_API_KEY', raising=False)


def fake_llm(monkeypatch, module, reply):
    monkeypatch.setattr(module.llm, 'complete_json', lambda *a, **k: reply)


# --- llm.py -----------------------------------------------------------------

def test_demo_mode_returns_the_cached_answer_ignoring_case_and_spacing(demo_on):
    answer = llm.complete_json('sys', 'user', fixture_text='  ' + NOTE.upper() + '\n')
    assert len(answer['items']) == 2


def test_demo_mode_returns_none_for_unknown_input(demo_on):
    assert llm.complete_json('sys', 'user', fixture_text='something else') is None


def test_api_failure_never_raises_and_falls_back_to_the_fixture(monkeypatch):
    monkeypatch.setenv('DEMO_MODE', '0')

    def boom(system, user):
        raise RuntimeError('network down')
    monkeypatch.setattr(llm, '_call_api', boom)
    assert llm.complete_json('sys', 'user') is None
    assert llm.complete_json('sys', 'user', fixture_text=NOTE) is not None


def test_live_reply_is_parsed_out_of_surrounding_text(monkeypatch):
    monkeypatch.setenv('DEMO_MODE', '0')
    monkeypatch.setattr(llm, '_call_api', lambda s, u: 'Sure, here it is:\n{"a": 1}\nHope that helps.')
    assert llm.complete_json('sys', 'user') == {'a': 1}


def test_env_example_style_demo_mode_value(monkeypatch):
    monkeypatch.setenv('DEMO_MODE', '1            # 1 = use fixtures')
    assert llm.demo_mode() is True


# --- parse_note -------------------------------------------------------------

def test_doris_note_becomes_two_items(demo_on, doris_rxs):
    parsed = parse_note(NOTE, doris_rxs)
    assert [(i.kind, i.rx_id, i.count) for i in parsed.items] == [
        ('refusal', FUROSEMIDE, None),
        ('stock_count', FUROSEMIDE, 3),
    ]


def test_doris_note_drafts_feed_r5(demo_on, doris_rxs):
    note, stock = to_draft_events(parse_note(NOTE, doris_rxs), 'doris', NOTE)
    assert note['payload']['kind'] == 'NOTE' and note['payload']['text'] == NOTE
    assert note['payload']['summary'] and len(note['payload']['items']) == 2
    assert (stock['rx_id'], stock['payload']['kind'], stock['payload']['stock_doses']) == (
        FUROSEMIDE, 'STOCK_COUNT', 3)
    for draft in (note, stock):
        Event(id='x', author='carehome', created_at=0, **draft)   # fits the shared model


@pytest.mark.parametrize('reply', [
    None,                                              # LLM unreachable
    {},                                                # empty object
    {'items': 'not a list'},
    {'summary': 's', 'items': [{'kind': 'prescribe', 'detail': 'x', 'source_text': 'x'}]},   # unknown kind
    {'summary': 's', 'items': [{'kind': 'refusal'}]},  # missing fields
    {'items': []},                                     # no summary
])
def test_bad_llm_output_falls_back_to_manual_form(monkeypatch, doris_rxs, reply):
    fake_llm(monkeypatch, pn, reply)
    assert parse_note('some note', doris_rxs) is None


def test_made_up_rx_id_is_dropped(monkeypatch, doris_rxs):
    fake_llm(monkeypatch, pn, {'summary': 'Refused.', 'items': [{'kind': 'refusal', 'rx_id': 'rx-invented',
                                          'drug': 'Aspirin', 'detail': 'Refused.',
                                          'source_text': 'refused'}]})
    assert parse_note('refused', doris_rxs).items[0].rx_id is None


def test_empty_note_returns_none(demo_on, doris_rxs):
    assert parse_note('   ', doris_rxs) is None


def test_prompt_does_not_contain_the_residents_name(doris_rxs):
    prompt = pn._user_prompt('refused tablets', doris_rxs)
    assert 'Patel' not in prompt and 'doris' not in prompt.replace('rx-doris', '')


# --- summarise --------------------------------------------------------------

def margaret_events():
    return [
        ev('OBSERVATION', WARFARIN, at(8), kind='INR_TAKEN'),
        ev('SAFETY_FLAG', WARFARIN, at(18), rule='R1', action='HOLD'),
        ev('DOSE_WITHHELD', WARFARIN, at(18, 5), reason='safety hold'),
        ev('REPEAT_REQUESTED', WARFARIN, at(18, 20), qty=28, auto_drafted=True),
    ]


def test_fallback_summary_with_llm_off(demo_on):
    summary = summarise(margaret_events(), demo_state().rx)
    assert summary.source == 'rules'
    assert len(summary.lines) == 3
    assert summary.urgency == 'urgent'
    assert 'Warfarin' in summary.lines[0]
    assert 'repeat request' in summary.lines[2]


def test_llm_summary_is_used_when_valid(monkeypatch):
    fake_llm(monkeypatch, sm, {'lines': ['a', 'b', 'c'], 'urgency': 'soon'})
    summary = summarise(margaret_events()[:1], demo_state().rx)
    assert (summary.source, summary.lines, summary.urgency) == ('llm', ['a', 'b', 'c'], 'soon')


def test_llm_cannot_downgrade_urgency(monkeypatch):
    fake_llm(monkeypatch, sm, {'lines': ['a', 'b', 'c'], 'urgency': 'routine'})
    assert summarise(margaret_events(), demo_state().rx).urgency == 'urgent'


@pytest.mark.parametrize('reply', [
    {'lines': ['only', 'two']},
    {'lines': ['a', 'b', 'c'], 'urgency': 'panic'},
    {'lines': ['a', '', 'c']},
    {'text': 'free text'},
])
def test_invalid_llm_summary_falls_back_to_rules(monkeypatch, reply):
    fake_llm(monkeypatch, sm, reply)
    assert summarise(margaret_events(), demo_state().rx).source == 'rules'


def test_empty_inbox_summary(demo_on):
    summary = summarise([], {})
    assert summary.urgency == 'routine' and len(summary.lines) == 3
