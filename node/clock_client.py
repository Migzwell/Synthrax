"""Reads and moves the demo clock."""
# Every rule must use now(), never datetime.now(), so the whole demo follows one clock.
# Times are demo-clock minutes: 0 = 14:00 on demo day, 240 = 18:00, -1440 = 14:00 yesterday.
import os

import httpx

CLOCK_URL = os.getenv("CLOCK_URL", "http://localhost:8000")
DAY_START = 14 * 60                                    # minute 0 is 14:00
ROUNDS = ("08:00", "12:00", "18:00", "22:00")          # med rounds

_minute = int(os.getenv("DEMO_START_MINUTE", "-120"))  # last known time, used if the clock is unreachable

def minute_of(hhmm: str, day: int = 0) -> int:
    """'18:00' on demo day -> 240. day=-1 is yesterday, day=1 is tomorrow. Needs two-digit 'HH:MM'."""
    h, m = map(int, hhmm.split(":"))
    return day * 1440 + h * 60 + m - DAY_START


def fmt(minute: int) -> str:
    """240 -> '18:00 today', -1680 -> '10:00 yesterday'."""
    total = DAY_START + minute
    day = total // 1440
    label = {-1: "yesterday", 0: "today", 1: "tomorrow"}.get(day, f"day {day:+d}")
    return f"{(total // 60) % 24:02d}:{total % 60:02d} {label}"


def next_round(now: int) -> int:
    """The first med round strictly after `now`, e.g. 12:00 -> 18:00, 22:00 -> 08:00 tomorrow."""
    today = (now + DAY_START) // 1440
    slots = sorted(minute_of(t, d) for d in (today, today + 1) for t in ROUNDS)
    return next(s for s in slots if s > now)


def from_test_hours(t_hours: float) -> int:
    """Ethan's test cases count hours from 18:00. -32 (INR yesterday 10:00) -> -1680."""
    return round(t_hours * 60) + minute_of("18:00")

def now() -> int:
    return _minute


async def poll() -> int:
    """Fetch the current time. If the clock server is unreachable, keep the last known time."""
    global _minute
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            _minute = (await client.get(f"{CLOCK_URL}/clock")).json()["minute"]
    except httpx.HTTPError:
        pass
    return _minute


async def advance(minutes: int = 60) -> int:
    async with httpx.AsyncClient(timeout=1.0) as client:
        await client.post(f"{CLOCK_URL}/clock/advance", params={"minutes": minutes})
    return await poll()


async def jump_to_next_round() -> int:
    async with httpx.AsyncClient(timeout=1.0) as client:
        await client.post(f"{CLOCK_URL}/clock/set", params={"minute": next_round(now())})
    return await poll()
