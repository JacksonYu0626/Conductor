"""
services/scheduler.py — unified APScheduler wrapper for Conductor.

Handles two job types:
  • script   — runs a Python script via services/runner.py
  • tableau  — renders Tableau views and emails them via services/tableau_runner.py

Job ID conventions:
  script_schedule_{id}   for script-type schedules
  tableau_schedule_{id}  for tableau-type schedules
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.events import EVENT_JOB_MISSED
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from database import SessionLocal
from models import Schedule

log = logging.getLogger(__name__)

scheduler = BackgroundScheduler(
    timezone="America/Los_Angeles",
    # executors={"default": ThreadPoolExecutor(max_workers=20)},
    executors={
        "default": ThreadPoolExecutor(max_workers=5),
        "tableau": ThreadPoolExecutor(max_workers=15),
    },
    job_defaults={
        "misfire_grace_time": 300,
        "coalesce": True,
        "max_instances": 1,
    },
)

# ── Script-schedule trigger building ──────────────────────────────────────────
DAY_MAP  = {
    "Monday": "mon", "Tuesday": "tue", "Wednesday": "wed",
    "Thursday": "thu", "Friday": "fri", "Saturday": "sat", "Sunday": "sun",
}
WEEK_MAP = {"1st": "1", "2nd": "2", "3rd": "3", "4th": "4"}


def _once_or_hourly_trigger(schedule: Schedule, recurrence: str):
    """Shared 'once'/'hourly' trigger logic — used by both script and Tableau schedules."""
    tz_user = pytz.timezone(schedule.timezone or "UTC")

    if recurrence == "once":
        if not schedule.run_at_utc:
            return None
        run_at = pytz.UTC.localize(schedule.run_at_utc)
        return DateTrigger(run_date=run_at)

    if recurrence == "hourly":
        if not schedule.run_at_utc:
            return None
        start_local = pytz.UTC.localize(schedule.run_at_utc).astimezone(tz_user)
        every = max(int(getattr(schedule, "interval_hours", 1) or 1), 1)

        # "To" time — defaults to 5pm same-tz if not configured (preserves
        # legacy Tableau business-hours behavior for existing schedules).
        end_hour = 17
        if schedule.hourly_end_time:
            try:
                end_hour = int(schedule.hourly_end_time.split(":")[0])
            except (ValueError, IndexError):
                end_hour = 17
        # Midnight ("12:00 AM") means "end of day", and any end <= start
        # is treated the same way — run through the last hour of the day.
        if end_hour <= start_local.hour:
            end_hour = 23

        # Days of week — blank means Mon-Fri (preserves existing behavior)
        days = schedule.days_of_week or []
        dow = ",".join(DAY_MAP.get(d, "") for d in days if DAY_MAP.get(d)) or "mon-fri"

        return CronTrigger(
            day_of_week=dow,
            hour=f"{start_local.hour}-{end_hour}/{every}",
            minute=start_local.minute,
            timezone=tz_user,
            start_date=start_local,
        )

    return None


def _make_script_trigger(schedule: Schedule) -> CronTrigger:
    freq = schedule.frequency

    # "Once" / "hourly" — aligned with Tableau's recurrence/run_at_utc/timezone/interval_hours
    if freq in ("once", "hourly"):
        return _once_or_hourly_trigger(schedule, freq)

    hour, minute = schedule.run_time.split(":")
    freq = schedule.frequency
    tz_user = pytz.timezone(schedule.timezone or "America/Los_Angeles")

    # Build start_date kwarg — combine start_date (midnight) with the run_time
    # so APScheduler never fires before that exact moment.
    start_kw = {}
    if schedule.start_date:
        sd = schedule.start_date
        start_kw["start_date"] = sd.replace(hour=int(hour), minute=int(minute),
                                             second=0, microsecond=0)

    if freq == "daily":
        return CronTrigger(hour=int(hour), minute=int(minute), timezone=tz_user, **start_kw)

    elif freq == "weekly":
        days = schedule.days_of_week or []
        dow  = ",".join(DAY_MAP.get(d, "mon") for d in days) or "mon"
        return CronTrigger(day_of_week=dow, hour=int(hour), minute=int(minute),
                           timezone=tz_user, **start_kw)

    elif freq == "monthly":
        wom = schedule.week_of_month or "start"
        if wom == "start":
            # 1st calendar day of the month
            return CronTrigger(day="1",
                               hour=int(hour), minute=int(minute), timezone=tz_user, **start_kw)
        elif wom == "end":
            # Last calendar day of the month
            return CronTrigger(day="last",
                               hour=int(hour), minute=int(minute), timezone=tz_user, **start_kw)
        else:
            # Legacy 1st/2nd/3rd/4th support for existing schedules
            week_num = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4}.get(wom, 1)
            day_start = (week_num - 1) * 7 + 1
            day_end   = week_num * 7
            created = schedule.created_at or datetime.now()
            dow = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][created.weekday()]
            return CronTrigger(day=f"{day_start}-{day_end}", day_of_week=dow,
                               hour=int(hour), minute=int(minute), timezone=tz_user, **start_kw)

    elif freq == "quarterly":
        wom = schedule.week_of_month or "start"
        if wom == "start":
            return CronTrigger(month="1,4,7,10", day="1",
                               hour=int(hour), minute=int(minute), timezone=tz_user, **start_kw)
        elif wom == "end":
            return CronTrigger(month="3,6,9,12", day="last",
                               hour=int(hour), minute=int(minute), timezone=tz_user, **start_kw)
        else:
            week_num = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4}.get(wom, 1)
            day_start = (week_num - 1) * 7 + 1
            day_end   = week_num * 7
            created = schedule.created_at or datetime.now()
            dow = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][created.weekday()]
            return CronTrigger(month="1,4,7,10",
                               day=f"{day_start}-{day_end}", day_of_week=dow,
                               hour=int(hour), minute=int(minute), timezone=tz_user, **start_kw)

    return CronTrigger(hour=int(hour), minute=int(minute), timezone=tz_user, **start_kw)


# ── Tableau-schedule trigger building ─────────────────────────────────────────

def _make_tableau_trigger(schedule: Schedule):
    recurrence = (schedule.recurrence or "once").lower()
    tz_user    = pytz.timezone(schedule.timezone or "UTC")

    if recurrence == "once":
        if not schedule.run_at_utc:
            return None
        run_at = pytz.UTC.localize(schedule.run_at_utc)
        return DateTrigger(run_date=run_at)

    start_local = pytz.UTC.localize(schedule.run_at_utc).astimezone(tz_user)
    hour, minute = start_local.hour, start_local.minute

    # if recurrence == "hourly":
    #     every = max(int(getattr(schedule, "interval_hours", 1) or 1), 1)
    #     return CronTrigger(
    #         hour=f"*/{every}",
    #         minute=minute,
    #         timezone=tz_user,
    #         start_date=start_local,
    #     )
    
    if recurrence == "hourly":
        every = max(int(getattr(schedule, "interval_hours", 1) or 1), 1)
        return CronTrigger(
            day_of_week="mon-fri",
            hour=f"{start_local.hour}-17/{every}",  # 7:10 AM to 5:10 PM
            minute=minute,
            timezone=tz_user,
            start_date=start_local,
        )

    if recurrence == "daily":
        return CronTrigger(hour=hour, minute=minute,
                           timezone=tz_user, start_date=start_local)

    if recurrence == "weekly":
        # Honor user-selected days_of_week; fall back to start date's weekday
        days = schedule.days_of_week or []
        if days:
            dow = ",".join(DAY_MAP.get(d, "mon") for d in days)
        else:
            dow = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][start_local.weekday()]
        return CronTrigger(day_of_week=dow, hour=hour, minute=minute,
                           timezone=tz_user, start_date=start_local)

    if recurrence == "monthly":
        wom = schedule.week_of_month or "start"
        if wom == "start":
            # 1st calendar day of the month (aligned with script trigger)
            return CronTrigger(day="1",
                               hour=hour, minute=minute,
                               timezone=tz_user, start_date=start_local)
        elif wom == "end":
            # Last calendar day of the month (aligned with script trigger)
            return CronTrigger(day="last",
                               hour=hour, minute=minute,
                               timezone=tz_user, start_date=start_local)
        else:
            # Legacy 1st/2nd/3rd/4th support
            week_num = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4}.get(wom, 1)
            day_start = (week_num - 1) * 7 + 1
            day_end   = week_num * 7
            dow = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][start_local.weekday()]
            return CronTrigger(
                day=f"{day_start}-{day_end}", day_of_week=dow,
                hour=hour, minute=minute,
                timezone=tz_user, start_date=start_local,
            )

    if recurrence == "quarterly":
        wom    = schedule.week_of_month or "start"
        if wom == "start":
            # Jan/Apr/Jul/Oct, 1st calendar day (aligned with script trigger)
            return CronTrigger(month="1,4,7,10", day="1",
                               hour=hour, minute=minute,
                               timezone=tz_user, start_date=start_local)
        elif wom == "end":
            # Mar/Jun/Sep/Dec, last calendar day (aligned with script trigger)
            return CronTrigger(month="3,6,9,12", day="last",
                               hour=hour, minute=minute,
                               timezone=tz_user, start_date=start_local)
        else:
            week_num = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4}.get(wom, 1)
            day_start = (week_num - 1) * 7 + 1
            day_end   = week_num * 7
            dow = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][start_local.weekday()]
            return CronTrigger(
                month="1,4,7,10",
                day=f"{day_start}-{day_end}", day_of_week=dow,
                hour=hour, minute=minute,
                timezone=tz_user, start_date=start_local,
            )

    # Fallback
    if schedule.run_at_utc:
        run_at = pytz.UTC.localize(schedule.run_at_utc)
        return DateTrigger(run_date=run_at)
    return None


# ── Job execution dispatchers ─────────────────────────────────────────────────

def _run_script_job(script_id: int, schedule_id: int):
    from services.runner import run_script
    run_script(script_id, trigger="schedule", triggered_by="scheduler",
               schedule_id=schedule_id)


def _run_tableau_job(schedule_id: int):
    from services.tableau_runner import run_tableau_schedule
    run_tableau_schedule(schedule_id, triggered_by="scheduler")


def _run_sharepoint_job(schedule_id: int):
    from services.sharepoint_runner import run_sharepoint_schedule
    run_sharepoint_schedule(schedule_id, triggered_by="scheduler")




# ── Public API ────────────────────────────────────────────────────────────────

def _job_id(schedule: Schedule) -> str:
    return f"{schedule.schedule_type}_schedule_{schedule.id}"


def add_or_update_schedule(schedule: Schedule) -> None:
    """Add or replace the APScheduler job for the given schedule."""
    jid = _job_id(schedule)

    # Remove existing job
    try:
        scheduler.remove_job(jid)
    except Exception:
        pass

    if not schedule.is_active:
        return

    try:
        if schedule.schedule_type == "script":
            if not schedule.script_id:
                return
            if schedule.frequency in ("once", "hourly"):
                if not schedule.run_at_utc:
                    return
                if schedule.frequency == "once":
                    now = datetime.now(timezone.utc).replace(tzinfo=None)
                    if schedule.run_at_utc <= now:
                        _mark_expired(schedule)
                        return
            elif not schedule.run_time:
                return
            trigger = _make_script_trigger(schedule)
            if trigger is None:
                log.warning(f"[scheduler] Could not build trigger for script schedule {schedule.id}")
                return
            scheduler.add_job(
                _run_script_job,
                trigger=trigger,
                id=jid,
                args=[schedule.script_id, schedule.id],
                replace_existing=True,
                misfire_grace_time=3600,
            )
            log.info(f"[scheduler] Added script job {jid}")

        elif schedule.schedule_type == "sharepoint":
            if schedule.recurrence == "once" and schedule.run_at_utc:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                if schedule.run_at_utc <= now:
                    _mark_expired(schedule)
                    return
            trigger = _make_tableau_trigger(schedule)  # same timing logic as Tableau
            if trigger is None:
                log.warning(f"[scheduler] Could not build trigger for sharepoint schedule {schedule.id}")
                return
            scheduler.add_job(
                _run_sharepoint_job,
                trigger=trigger,
                id=jid,
                args=[schedule.id],
                replace_existing=True,
                misfire_grace_time=3600,
            )
            schedule.apscheduler_id = jid
            schedule.status         = "scheduled"
            db = SessionLocal()
            try:
                db.merge(schedule); db.commit()
            finally:
                db.close()
            log.info(f"[scheduler] Added sharepoint job {jid}")

        elif schedule.schedule_type == "tableau":
            # One-time schedule: check if it's in the past
            if schedule.recurrence == "once" and schedule.run_at_utc:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                if schedule.run_at_utc <= now:
                    _mark_expired(schedule)
                    return

            trigger = _make_tableau_trigger(schedule)
            if trigger is None:
                log.warning(f"[scheduler] Could not build trigger for tableau schedule {schedule.id}")
                return

            scheduler.add_job(
                _run_tableau_job,
                trigger=trigger,
                id=jid,
                args=[schedule.id],
                replace_existing=True,
                misfire_grace_time=3600,
                executor="tableau"
            )

            # Log a preview of upcoming fire times (helps diagnose missed runs)
            try:
                job = scheduler.get_job(jid)
                if job and job.next_run_time:
                    log.info(f"[scheduler] Tableau job {jid} trigger={trigger} next_run={job.next_run_time}")
            except Exception:
                pass

            schedule.apscheduler_id = jid
            schedule.status         = "scheduled"
            db = SessionLocal()
            try:
                db.merge(schedule)
                db.commit()
            finally:
                db.close()

            log.info(f"[scheduler] Added tableau job {jid}")

    except Exception as e:
        log.error(f"[scheduler] Failed to add job for schedule {schedule.id}: {e}")


def remove_schedule(schedule_id: int, schedule_type: str = "script") -> None:
    jid = f"{schedule_type}_schedule_{schedule_id}"
    try:
        scheduler.remove_job(jid)
        log.info(f"[scheduler] Removed job {jid}")
    except Exception:
        pass


def get_next_run_utc(schedule_id: int, schedule_type: str = "script"):
    """
    Return the next scheduled run time as a naive UTC datetime, or None if
    the job isn't registered or has no upcoming runs.
    """
    jid = f"{schedule_type}_schedule_{schedule_id}"
    try:
        job = scheduler.get_job(jid)
    except Exception:
        return None
    if not job or not job.next_run_time:
        return None
    try:
        # job.next_run_time is timezone-aware; convert to naive UTC
        return job.next_run_time.astimezone(pytz.UTC).replace(tzinfo=None)
    except Exception:
        return None


def _mark_expired(schedule: Schedule) -> None:
    schedule.status = "expired"
    db = SessionLocal()
    try:
        db.merge(schedule)
        db.commit()
    finally:
        db.close()


def _on_job_missed(event):
    """Email alert on missed job (schedule slip)."""
    job_id = event.job_id
    scheduled_run_time = event.scheduled_run_time
    log.warning(f"[scheduler] Missed job: {job_id} scheduled for {scheduled_run_time}")

    # Parse type and id from job_id: e.g. "script_schedule_42"
    parts = job_id.rsplit("_", 1)
    if len(parts) != 2:
        return
    try:
        schedule_id = int(parts[1])
    except ValueError:
        return

    db = SessionLocal()
    try:
        s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
        if not s:
            return
        try:
            import pytz
            tz       = pytz.timezone("America/Los_Angeles")
            local_t  = scheduled_run_time.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")
        except Exception:
            local_t = str(scheduled_run_time)

        try:
            from services.email_service import send_run_notification
            send_run_notification(
                recipients=s.recipients or [],
                script_name=s.name or f"Schedule #{s.id}",
                status="missed",
                duration_ms=0,
                output="",
                error=f"Scheduled run at {local_t} was missed. The server may have been busy.",
                started_at=scheduled_run_time,
            )
        except Exception as e:
            log.error(f"[scheduler] Could not send misfire email: {e}")
    finally:
        db.close()


def start_scheduler() -> None:
    db = SessionLocal()
    try:
        schedules = db.query(Schedule).filter(Schedule.is_active == True).all()
        for s in schedules:
            try:
                add_or_update_schedule(s)
            except Exception as e:
                log.error(f"[scheduler] Failed to load schedule {s.id}: {e}")

        log.info(f"[scheduler] Started with {len(schedules)} active schedule(s)")
    finally:
        db.close()

    scheduler.add_listener(_on_job_missed, EVENT_JOB_MISSED)
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
