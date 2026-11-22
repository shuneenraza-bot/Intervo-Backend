"""Server-side check of the blink liveness evidence.

The browser reports the eye-blink score (0 = open, 1 = closed) of every frame it looked at
while the user was asked to blink. The server re-checks that the series is a plausible live
blink: enough frames, in time order, within the time window, with open eyes followed by
closed eyes. This is not proof against a modified client (only server-side video analysis
would be); it stops a request that simply claims "blinked" and makes a forged one carry a
full, consistent series."""

from pydantic import BaseModel, Field

EYES_OPEN = 0.35  # same thresholds as the browser's check (Camera.jsx)
EYES_CLOSED = 0.55
MIN_SAMPLES = 5
MAX_SAMPLES = 300
MAX_WINDOW_MS = 6000  # the browser gives the user 4 s; the rest is slack
MIN_SPAN_MS = 150  # a blink cannot be proven from frames that all arrived in a blink of an eye


class BlinkSample(BaseModel):
    t: int = Field(ge=0, le=600_000)  # milliseconds since the check started
    v: float = Field(ge=0, le=1)  # eyeBlink score of that frame


def blink_ok(samples: list[BlinkSample]) -> bool:
    if not (MIN_SAMPLES <= len(samples) <= MAX_SAMPLES):
        return False
    times = [s.t for s in samples]
    if any(b <= a for a, b in zip(times, times[1:])):  # strictly increasing
        return False
    span = times[-1] - times[0]
    if span > MAX_WINDOW_MS or span < MIN_SPAN_MS:
        return False
    seen_open = False
    for s in samples:
        if s.v < EYES_OPEN:
            seen_open = True
        elif s.v > EYES_CLOSED and seen_open:
            return True
    return False
