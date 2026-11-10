"""
Pacific time helpers (America/Los_Angeles) without needing the tzdata package,
which Windows Python doesn't ship with.

Run logs are stored in UTC. The UI shows and filters by Pacific dates, so the
charts and the Run history date filter both convert through these helpers to
stay in sync — including across daylight-saving changes.

US rule: daylight time runs from the 2nd Sunday of March at 2:00 AM local
to the 1st Sunday of November at 2:00 AM local.
"""
from datetime import datetime, timedelta, timezone

_PST = timedelta(hours=-8)
_PDT = timedelta(hours=-7)


def _nth_sunday(year: int, month: int, n: int) -> datetime:
    d = datetime(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)  # first Sunday
    return d + timedelta(weeks=n - 1)


def _dst_window_utc(year: int):
    # 2:00 AM PST = 10:00 UTC (start); 2:00 AM PDT = 09:00 UTC (end)
    start = _nth_sunday(year, 3, 2) + timedelta(hours=10)
    end = _nth_sunday(year, 11, 1) + timedelta(hours=9)
    return start, end


def offset_for_utc(utc_naive: datetime) -> timedelta:
    start, end = _dst_window_utc(utc_naive.year)
    return _PDT if start <= utc_naive < end else _PST


def to_local(dt: datetime) -> datetime:
    """UTC (naive or aware) -> naive Pacific local time."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt + offset_for_utc(dt)


def to_utc(local_naive: datetime) -> datetime:
    """Naive Pacific local time -> naive UTC."""
    guess = local_naive - _PST                     # assume standard time first
    off = offset_for_utc(guess)
    return local_naive - off


def local_day_start_utc(ymd: str) -> datetime:
    """'YYYY-MM-DD' (Pacific) -> UTC instant of that day's midnight."""
    return to_utc(datetime.strptime(ymd, "%Y-%m-%d"))
