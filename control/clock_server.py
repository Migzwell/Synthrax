"""Shared demo clock; never partitioned."""
# A demo control, not data: the network switch never blocks it, so an offline site
# still moves to 18:00 with everyone else.
# Time is in demo-clock minutes: 0 = 14:00 on demo day (see core/types.py).
# The Synthrax demo story starts at 12:00, when the care home's wifi drops.
import os

try:                                # read CLOCK_PORT and DEMO_START_MINUTE from .env
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import uvicorn
from fastapi import FastAPI

START_MINUTE = int(os.getenv("DEMO_START_MINUTE", "-120"))   # -120 = 12:00 today

app = FastAPI(title="Synthrax demo clock")
state = {"minute": START_MINUTE}


@app.get("/clock")
def get_clock():
    return {"minute": state["minute"]}


@app.post("/clock/advance")
def advance(minutes: int = 60):
    """Move time forward, e.g. the '+1 hour' button."""
    state["minute"] += minutes
    return {"minute": state["minute"]}


@app.post("/clock/set")
def set_clock(minute: int):
    """Jump to an exact time, e.g. 'Next round' sends 240 for 18:00."""
    state["minute"] = minute
    return {"minute": state["minute"]}


@app.post("/clock/reset")
def reset():
    """Back to the start of the demo story (12:00), for rehearsals."""
    state["minute"] = START_MINUTE
    return {"minute": state["minute"]}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("CLOCK_PORT", "8000")))