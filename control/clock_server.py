"""Shared demo clock; never partitioned."""
# A demo control, not data: the network switch never blocks it, so an offline site
# still moves to 18:00 with everyone else.
#
# Time is in demo-clock minutes: 0 = 14:00 on demo day (see core/types.py).
# The Synthrax demo story starts at 12:00, when the care home's wifi drops.
#
# Run: python -m control.clock_server      (port 8000)
import os

try:                                # read CLOCK_PORT and DEMO_START_MINUTE from .env
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import math
from datetime import datetime

import uvicorn
from fastapi import FastAPI


def real_minute() -> int:
    """The real time right now, in demo minutes (minute 0 = 14:00 today)."""
    t = datetime.now()
    return t.hour * 60 + t.minute - 14 * 60


def start_minute() -> int:
    """DEMO_START_MINUTE: a number (-120 = 12:00, the demo story) or 'now' (the real time)."""
    value = os.getenv("DEMO_START_MINUTE", "-120").split("#")[0].strip()
    return real_minute() if value.lower() == "now" else int(value)


START_MINUTE = start_minute()
LIVE = os.getenv("DEMO_LIVE_CLOCK", "0").split("#")[0].strip().lower() in ("1", "true", "yes")

app = FastAPI(title="Synthrax demo clock")


def _real_now() -> float:
    """The real time in demo minutes, including seconds, so a live clock turns over on the real minute."""
    t = datetime.now()
    return t.hour * 60 + t.minute + t.second / 60 - 14 * 60


state = {"minute": START_MINUTE, "offset": START_MINUTE - math.floor(_real_now())}


def current() -> int:
    """With DEMO_LIVE_CLOCK=1 the clock also moves forward in real time; otherwise only the buttons move it."""
    if LIVE:
        return math.floor(_real_now()) + state["offset"]
    return state["minute"]


def _set(minute: int) -> dict:
    state["minute"], state["offset"] = minute, minute - math.floor(_real_now())
    return {"minute": minute}


@app.get("/clock")
def get_clock():
    return {"minute": current()}


@app.post("/clock/advance")
def advance(minutes: int = 60):
    """Move time forward, e.g. the '+1 hour' button."""
    return _set(current() + minutes)


@app.post("/clock/set")
def set_clock(minute: int):
    """Jump to an exact time, e.g. 'Next round' sends 240 for 18:00."""
    return _set(minute)


@app.post("/clock/reset")
def reset():
    """Back to the start: 12:00 for the demo story, or the real time with DEMO_START_MINUTE=now."""
    return _set(start_minute())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("CLOCK_PORT", "8000")))