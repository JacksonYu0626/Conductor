"""
Analytics router — time-series run stats for the Summary dashboard chart.
Scoped to current user's data (admin sees all).
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from database import get_db
from models import RunLog, Script, Schedule, User
from deps import get_current_user, is_admin
from datetime import datetime, timezone, timedelta
from typing import Literal, Optional, Dict, Tuple, Any
import time
import os

router = APIRouter(prefix="/analytics", tags=["analytics"])

LOCAL_TZ_OFFSET = timedelta(hours=-7)   # PDT; change to -8 for PST

_ANALYTICS_CACHE: Dict[Tuple[Any, ...], Tuple[float, dict]] = {}
_ANALYTICS_CACHE_TTL_SECONDS = int(os.getenv("CONDUCTOR_ANALYTICS_CACHE_SECONDS", "300"))

def _cache_get(key: tuple):
    item = _ANALYTICS_CACHE.get(key)
    if not item:
        return None
    ts, value = item
    if time.time() - ts <= _ANALYTICS_CACHE_TTL_SECONDS:
        return value
    _ANALYTICS_CACHE.pop(key, None)
    return None

def _cache_set(key: tuple, value: dict):
    _ANALYTICS_CACHE[key] = (time.time(), value)
    return value


def _to_local(dt: datetime) -> datetime:
    # Pacific time with daylight saving handled (was a fixed -7h offset)
    from services.pacific_time import to_local
    return to_local(dt)


def _window_start(period: str) -> datetime:
    now_local = _to_local(datetime.now(timezone.utc))
    if period == "day":
        start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        monday = now_local - timedelta(days=now_local.weekday())
        start  = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "month":
        start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == "year":
        start = now_local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == "last14":
        start = (now_local - timedelta(days=13)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    from services.pacific_time import to_utc
    return to_utc(start)


def _bucket_label(dt: datetime, period: str) -> str:
    if period == "day":
        h = dt.strftime("%I").lstrip("0") or "12"
        return f"{h} {dt.strftime('%p')}"
    if period == "week":
        return f"{dt.strftime('%a')} {dt.day}"
    if period == "month":
        return str(dt.day)
    if period == "year":
        return dt.strftime("%b")
    if period == "last14":
        return f"{dt.strftime('%b')} {dt.day}"
    return str(dt)


def _truncate(dt: datetime, period: str) -> datetime:
    if period == "day":
        return dt.replace(minute=0, second=0, microsecond=0)
    if period == "week":
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "month":
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "year":
        return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period == "last14":
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return dt


def _all_bucket_keys(period: str) -> list:
    """Every bucket in the window up to now, so empty days/hours show as 0."""
    now_local = _to_local(datetime.now(timezone.utc))
    start = _to_local(_window_start(period).replace(tzinfo=timezone.utc))
    keys = []
    if period == "day":
        k = start
        while k <= now_local:
            keys.append(k)
            k += timedelta(hours=1)
    elif period == "year":
        for m in range(1, now_local.month + 1):
            keys.append(start.replace(month=m))
    else:  # week, month, last14 — one bucket per day
        k = start
        while k <= now_local:
            keys.append(k)
            k += timedelta(days=1)
    return keys


def _bucket_range(key: datetime, period: str) -> Tuple[str, str]:
    """Local date range (YYYY-MM-DD) a bucket covers — used to open Run History for it."""
    if period == "year":
        nxt = key.replace(year=key.year + 1, month=1) if key.month == 12 else key.replace(month=key.month + 1)
        end = min(nxt - timedelta(days=1), _to_local(datetime.now(timezone.utc)))
        return key.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    d = key.strftime("%Y-%m-%d")
    return d, d


@router.get("/runs")
def run_analytics(
    period:   Literal["day", "week", "month", "year", "last14"] = Query(default="week"),
    job_type: Optional[str] = Query(default="all"),
    db:       Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    admin = is_admin(current_user)
    cache_key = ("analytics_runs", "admin" if admin else "user", current_user.id if not admin else 0, period, job_type or "all")
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    since = _window_start(period)

    q = (
        db.query(RunLog)
        .filter(RunLog.started_at >= since)
        .filter(RunLog.status.in_(["success", "failed", "stopped"]))
        .order_by(RunLog.started_at)
    )

    if not admin:
        owned_script_ids = [
            s.id for s in db.query(Script.id).filter(Script.owner_id == current_user.id).all()
        ]
        owned_schedule_ids = [
            s.id for s in db.query(Schedule.id).filter(Schedule.owner_id == current_user.id).all()
        ]
        from sqlalchemy import or_
        q = q.filter(
            or_(
                RunLog.script_id.in_(owned_script_ids),
                RunLog.schedule_id.in_(owned_schedule_ids),
                # Catch orphaned logs (script/schedule deleted) via snapshotted owner_id
                RunLog.owner_id == current_user.id,
            )
        )

    # Runs per job type over the same window, ignoring the job-type filter
    # (feeds the "Runs by job type" donut).
    from sqlalchemy import func as _func
    type_q = q.with_entities(RunLog.log_type, _func.count(RunLog.id)).order_by(None).group_by(RunLog.log_type)
    if job_type and job_type != "all":
        q = q.filter(RunLog.log_type == job_type)

    logs = q.all()

    buckets: dict = {}
    for k in _all_bucket_keys(period):
        buckets[k] = {"total": 0, "success": 0, "failed": 0}
    durations = []
    for log in logs:
        local_dt = _to_local(log.started_at)
        key = _truncate(local_dt, period)
        if key not in buckets:
            buckets[key] = {"total": 0, "success": 0, "failed": 0}
        buckets[key]["total"]   += 1
        buckets[key]["success"] += 1 if log.status == "success" else 0
        buckets[key]["failed"]  += 1 if log.status == "failed"  else 0
        if log.status == "success" and log.duration_ms:
            durations.append(log.duration_ms)

    by_type = {"script": 0, "tableau": 0, "sharepoint": 0}
    try:
        for lt, cnt in type_q.all():
            by_type[(lt or "script")] = by_type.get(lt or "script", 0) + int(cnt or 0)
    except Exception:
        pass

    sorted_keys = sorted(buckets)
    labels  = [_bucket_label(k, period) for k in sorted_keys]
    total   = [buckets[k]["total"]   for k in sorted_keys]
    success = [buckets[k]["success"] for k in sorted_keys]
    failed  = [buckets[k]["failed"]  for k in sorted_keys]

    all_total   = sum(total)
    all_success = sum(success)
    all_failed  = sum(failed)

    now_local = _to_local(datetime.now(timezone.utc))
    period_labels = {
        "day":   "Today",
        "week":  f"This week (Mon {str((now_local - timedelta(days=now_local.weekday())).day)} "
                 f"{(now_local - timedelta(days=now_local.weekday())).strftime('%b')} – now)",
        "month": now_local.strftime("%B %Y"),
        "year":  str(now_local.year),
    }

    result = {
        "period":       period,
        "period_label": period_labels.get(period, period),
        "job_type":     job_type or "all",
        "labels":       labels,
        "total":        total,
        "success":      success,
        "failed":       failed,
        "buckets":      [{"label": _bucket_label(k, period), "from": _bucket_range(k, period)[0], "to": _bucket_range(k, period)[1]} for k in sorted_keys],
        "by_type":      by_type,
        "summary": {
            "avg_duration_ms": int(sum(durations) / len(durations)) if durations else 0,
            "total":        all_total,
            "success":      all_success,
            "failed":       all_failed,
            "success_rate": round(all_success / all_total * 100, 1) if all_total else 0,
            "failure_rate": round(all_failed  / all_total * 100, 1) if all_total else 0,
        }
    }
    return _cache_set(cache_key, result)
