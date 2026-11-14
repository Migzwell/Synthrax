"""Demo clock: time moves and Next round lands on the right round."""
from fastapi.testclient import TestClient

from control.clock_server import START_MINUTE, app
from node.clock_client import fmt, from_test_hours, minute_of, next_round


# ---------- time conversions ----------

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


# ---------- next round ----------

def test_next_round_from_demo_start():
    assert next_round(minute_of("12:00")) == minute_of("18:00")   # 12:00 itself doesn't count


def test_next_round_wraps_to_tomorrow():
    assert next_round(minute_of("22:30")) == minute_of("08:00", day=1)


def test_next_round_between_rounds():
    assert next_round(minute_of("09:15")) == minute_of("12:00")


# ---------- the Synthrax demo story ----------

def test_demo_story_times():
    assert fmt(from_test_hours(-32)) == "10:00 yesterday"        # INR blood test
    assert fmt(minute_of("12:00")) == "12:00 today"              # care home wifi drops
    assert fmt(minute_of("14:00")) == "14:00 today"              # GP changes 5mg to 3mg
    assert fmt(minute_of("16:00")) == "16:00 today"              # R7 warns the GP
    assert next_round(minute_of("12:00")) == minute_of("18:00")  # the 18:00 round, R1 fires


# ---------- clock server ----------

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