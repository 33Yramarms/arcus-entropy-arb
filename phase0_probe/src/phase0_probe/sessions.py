"""US-equity session calendar (NYSE) + Arcus RTH-margin window, for classifying funding hours. Pure functions, ints only.

Sources:
* NYSE holidays / early closes 2026: https://www.nyse.com/trade/hours-calendars/ (checked 2026-11-27 MYT): closed
  Jan 1, Jan 19, Feb 16, Apr 3, May 25, Jun 19, Jul 3, Sep 7, Nov 26, Dec 25; early close 13:00 ET on Fri 2026-11-27
  and Thu 2026-12-24. Regular session 09:30–16:00 America/New_York.
* Arcus ``regularTradingHours`` (GET /v1/markets, get-markets.md ``RegularTradingHours``): for the equity markets
  ``startSecondsOfDay`` 14400 (04:00) → ``endSecondsOfDay`` 72000 (20:00) America/New_York, half-open; "weekend and
  holiday closures are venue-calendar concerns layered on top and are NOT encoded here". Outside that window Arcus
  uses ``offHoursInitialMarginFraction`` and pins funding to SOFR + 0.5 %/yr (get-markets.md ``fundingRate``).
  [待实测确认] whether Arcus shortens its 20:00 window on NYSE early-close days (the schema has no field for it).

Labels:
* ``RTH``      — NYSE regular session (09:30–16:00 ET; 09:30–13:00 on early-close days), trading days only.
* ``EXT``      — trading day, inside the Arcus window (04:00–20:00 ET) but outside NYSE RTH (pre/post market).
* ``CLOSED``   — overnight (20:00–04:00 ET), weekends and NYSE holidays.
``OFF_HOURS`` (the user's second bucket) = ``EXT`` ∪ ``CLOSED``.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HOUR_MS = 3_600_000
NYSE_HOLIDAYS = frozenset(dt.date.fromisoformat(d) for d in (
    "2025-11-27", "2025-12-25",
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06",
    "2027-11-25", "2027-12-24"))
NYSE_EARLY_CLOSE = {dt.date.fromisoformat(d): dt.time(13, 0) for d in (
    "2025-11-28", "2025-12-24", "2026-11-27", "2026-12-24", "2027-11-26")}
RTH_OPEN, RTH_CLOSE = dt.time(9, 30), dt.time(16, 0)
ARCUS_WIN_OPEN, ARCUS_WIN_CLOSE = dt.time(4, 0), dt.time(20, 0)     # Arcus regularTradingHours 14400 → 72000 s


def to_et(ts_ms: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts_ms // 1000, tz=dt.timezone.utc).astimezone(ET)


def is_trading_day(d: dt.date) -> bool:
    return d.weekday() < 5 and d not in NYSE_HOLIDAYS


def rth_close(d: dt.date) -> dt.time:
    return NYSE_EARLY_CLOSE.get(d, RTH_CLOSE)


def session_at(ts_ms: int) -> str:
    """Label of the instant ``ts_ms`` (epoch ms): RTH / EXT / CLOSED (half-open intervals, close is outside)."""
    t = to_et(ts_ms)
    d, tod = t.date(), t.time()
    if not is_trading_day(d):
        return "CLOSED"
    if RTH_OPEN <= tod < rth_close(d):
        return "RTH"
    if ARCUS_WIN_OPEN <= tod < ARCUS_WIN_CLOSE:
        return "EXT"
    return "CLOSED"


def funding_hour_session(hour_ms: int) -> str:
    """Session of the hourly funding payment stamped at ``hour_ms``. The rate accrues over [H − 1 h, H) (HL: premium
    averaged over the hour; Arcus: the funder's in-progress forecast for the hour), so the interval is labelled by its
    MIDPOINT H − 30 min. Consequence: on a full day the payments at 10:00 … 16:00 ET (7 per day) are RTH; on an early
    close day 10:00 … 13:00 ET (4)."""
    return session_at(hour_ms - HOUR_MS // 2)


def bucket(label: str) -> str:
    return "RTH" if label == "RTH" else "OFF_HOURS"
