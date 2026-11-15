"""Demo clock: time moves and Next round lands on the right round."""
from fastapi.testclient import TestClient

from control.clock_server import START_MINUTE, app
from node.clock_client import fmt, from_test_hours, minute_of, next_round

def test_minute_zero_is_two_pm():
    assert minute_of("14:00") == 0
    assert minute_of("18:00") == 240
    assert minute_of("12:00") == -120


def test_formatting():
    assert fmt(240) == "18:00 today"
    assert fmt(-1680) == "10:00 yesterday"
    assert fmt(minute_of("08:00", day=1)) == "08:00 tomorrow"


def test_rule_case_hours_convert_to_minutes():
    assert from_test_hours(0) == 240              # rule test cases count from 18:00
    assert from_test_hours(-32) == -1680          # INR yesterday at 10:00
    assert from_test_hours(-5.25) == minute_of("12:45")

def test_next_round_from_demo_start():
    assert next_round(minute_of("12:00")) == minute_of("18:00")   # 12:00 itself doesn't count


def test_next_round_wraps_to_tomorrow():
    assert next_round(minute_of("22:30")) == minute_of("08:00", day=1)


def test_next_round_between_rounds():
    assert next_round(minute_of("09:15")) == minute_of("12:00")

def test_demo_story_times():
    assert fmt(from_test_hours(-32)) == "10:00 yesterday"        # INR blood test
    assert fmt(minute_of("12:00")) == "12:00 today"              # care home wifi drops
    assert fmt(minute_of("14:00")) == "14:00 today"              # GP changes 5mg to 3mg
    assert fmt(minute_of("16:00")) == "16:00 today"              # R7 warns the GP
    assert next_round(minute_of("12:00")) == minute_of("18:00")  # the 18:00 round, R1 fires

def test_server_starts_at_noon_and_moves():
    client = TestClient(app)
    client.post("/clock/reset")
    assert client.get("/clock").json()["minute"] == START_MINUTE == minute_of("12:00")
    client.post("/clock/advance", params={"minutes": 60})
    assert client.get("/clock").json()["minute"] == minute_of("13:00")
    client.post("/clock/set", params={"minute": 240})
    assert client.get("/clock").json()["minute"] == minute_of("18:00")
    client.post("/clock/reset")
    assert client.get("/clock").json()["minute"] == START_MINUTE

def test_clock_can_start_at_the_real_time(monkeypatch):
    from datetime import datetime
    import control.clock_server as cs
    monkeypatch.setenv("DEMO_START_MINUTE", "now")
    t = datetime.now()
    assert abs(cs.start_minute() - (t.hour * 60 + t.minute - 14 * 60)) <= 1


def test_live_clock_moves_with_real_time(monkeypatch):
    import control.clock_server as cs
    real = [600.0]
    monkeypatch.setattr(cs, "_real_now", lambda: real[0])
    monkeypatch.setattr(cs, "LIVE", True)
    cs._set(240)
    real[0] += 2.5
    assert cs.current() == 242
    cs.advance(60)
    assert cs.current() == 302
    monkeypatch.setattr(cs, "LIVE", False)
    cs.reset()


def test_live_clock_turns_over_with_the_real_minute(monkeypatch):
    import control.clock_server as cs
    from node.clock_client import fmt
    real = [-716.8]
    monkeypatch.setattr(cs, "_real_now", lambda: real[0])
    monkeypatch.setattr(cs, "LIVE", True)
    cs._set(-717)
    assert fmt(cs.current()) == "02:03 today"
    real[0] = -715.9                                                      
    assert fmt(cs.current()) == "02:04 today"
    monkeypatch.setattr(cs, "LIVE", False)
    cs.reset()