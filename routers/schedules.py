"""
routers/schedules.py — unified schedule management for Conductor.
"""
import json
import os
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict

import pytz
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from database import get_db
from models import Schedule, Script, Dashboard, User, RunLog
from schemas import ScriptScheduleCreate, ScriptScheduleUpdate, TableauScheduleCreate, TableauScheduleUpdate, ScheduleOut, SharepointScheduleCreate, ShareIn, ShareAccessIn, ShareOut
from deps import get_current_user, is_admin
from services import sharing

log = logging.getLogger(__name__)
router = APIRouter(prefix="/schedules", tags=["schedules"])


def _parse_start_date(d_str: Optional[str]) -> Optional[datetime]:
    if not d_str:
        return None
    try:
        return datetime.strptime(d_str, "%Y-%m-%d")
    except Exception:
        return None


def _parse_run_at_local(dt_str: str, tz_name: str) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        local_naive = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M")
        tz          = pytz.timezone(tz_name or "UTC")
        local_aware = tz.localize(local_naive)
        return local_aware.astimezone(pytz.UTC).replace(tzinfo=None)
    except Exception:
        return None


def _enrich(s: Schedule, db: Session) -> dict:
    script_name    = None
    dashboard_name = None

    if s.schedule_type == "script" and s.script_id:
        sc = db.query(Script).filter(Script.id == s.script_id).first()
        script_name = sc.name if sc else None
        name = script_name or f"Script #{s.script_id}"
    elif s.schedule_type == "tableau":
        if s.dashboard_id:
            d = db.query(Dashboard).filter(Dashboard.id == s.dashboard_id).first()
            dashboard_name = d.name if d else None
        name = s.name or dashboard_name or f"Tableau Schedule #{s.id}"
    elif s.schedule_type == "sharepoint":
        name = s.name or f"SharePoint Schedule #{s.id}"
    else:
        name = s.name or f"Schedule #{s.id}"

    try:
        view_urls = json.loads(s.view_urls_json or "[]")
    except Exception:
        view_urls = []

    next_run_utc = None
    try:
        if s.is_active:
            from services.scheduler import get_next_run_utc
            next_run_utc = get_next_run_utc(s.id, s.schedule_type or "script")
    except Exception:
        pass

    # Derive last_run from RunLog directly (single source of truth = started_at).
    # Query by script_id (not schedule_id) so manual runs from the Scripts page
    # are included — those have schedule_id=NULL in RunLog.
    from sqlalchemy import desc as _desc
    last_log = None
    if s.schedule_type == "script" and s.script_id:
        last_log = (
            db.query(RunLog)
            .filter(RunLog.script_id == s.script_id)
            .order_by(_desc(RunLog.started_at))
            .first()
        )
    else:
        # Tableau schedules have no script_id — fall back to schedule_id
        last_log = (
            db.query(RunLog)
            .filter(RunLog.schedule_id == s.id)
            .order_by(_desc(RunLog.started_at))
            .first()
        )
    last_run_utc    = last_log.started_at if last_log else None
    last_run_status = last_log.status     if last_log else None

    return {
        "id":             s.id,
        "schedule_type":  s.schedule_type,
        "name":           name,
        "script_id":      s.script_id,
        "script_name":    script_name,
        "frequency":      s.frequency,
        "run_time":       s.run_time,
        "days_of_week":   s.days_of_week or [],
        "week_of_month":  s.week_of_month or "start",
        "start_date":     s.start_date,
        "dashboard_id":   s.dashboard_id,
        "dashboard_name": dashboard_name,
        "email_to":       s.email_to,
        "cc_to":          s.cc_to,
        "fmt":            s.fmt,
        "view_urls":      view_urls,
        "filters":        json.loads(s.filters_json or "{}"),
        "recurrence":     s.recurrence,
        "run_at_utc":     s.run_at_utc,
        "timezone":       s.timezone,
        "interval_hours": s.interval_hours,
        "hourly_end_time": s.hourly_end_time,
        "is_active":      bool(s.is_active) if s.is_active is not None else True,
        "email_on_success": bool(s.email_on_success) if s.email_on_success is not None else True,
        "email_on_failure": bool(s.email_on_failure) if s.email_on_failure is not None else True,
        "recipients":     s.recipients or [],
        "status":         s.status,
        "last_run_utc":   last_run_utc,
        "last_run_status":last_run_status,
        "last_error":     getattr(s, "last_error", None),
        "next_run_utc":   next_run_utc,
        "created_at":     s.created_at,
        "owner_name":     s.owner.name  if s.owner else None,
        "owner_email":    s.owner.email if s.owner else None,
        # SharePoint fields (populated when schedule_type = 'sharepoint')
        "sharepoint_site_id":   s.sharepoint_site_id,
        "sharepoint_folder":    s.sharepoint_folder,
        "output_file_path":     getattr(s, "output_file_path", None),
        "append_timestamp_to_filename": bool(getattr(s, "append_timestamp_to_filename", False)),
        "source_folder":        getattr(s, "source_folder", None),
        "filename_pattern":     getattr(s, "filename_pattern", None),
        "date_format":          getattr(s, "date_format", None),
        "target_period":        getattr(s, "target_period", "current"),
        "destination_filename": getattr(s, "destination_filename", None),
        "upload_mode":          getattr(s, "upload_mode", "replace") or "replace",
        "target_sheet":         getattr(s, "target_sheet", None),
        "target_table":         getattr(s, "target_table", None),
        "notify_email_to":      getattr(s, "notify_email_to", None),
        "notify_cc_to":         getattr(s, "notify_cc_to", None),
        "sharepoint_site_name": _site_name(db, s.sharepoint_site_id),
    }


def _site_name(db: Session, site_id) -> Optional[str]:
    if not site_id:
        return None
    from models import SharepointSite
    st = db.query(SharepointSite.name).filter(SharepointSite.id == site_id).first()
    return st[0] if st else None


def _out(s: Schedule, db: Session, user: User) -> dict:
    """One schedule for the API, including the current user's sharing role."""
    d = _enrich(s, db)
    d.update(sharing.share_info(db, user, [s]).get(s.id, {}))
    return d


def _mark_edited(s: Schedule, user: User):
    s.last_edited_by_id = user.id
    s.last_edited_at = datetime.now(timezone.utc).replace(tzinfo=None)


def _owned_script_ids(db: Session, user: User) -> List[int]:
    return [s.id for s in db.query(Script.id).filter(Script.owner_id == user.id).all()]


def _owned_dashboard_ids(db: Session, user: User) -> List[int]:
    return [d.id for d in db.query(Dashboard.id).filter(Dashboard.owner_id == user.id).all()]


@router.get("/", response_model=List[ScheduleOut])
def list_schedules(
    schedule_type: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import func
    from services.scheduler import get_next_run_utc

    from sqlalchemy import or_
    q = db.query(Schedule)
    if not is_admin(current_user):
        shared_ids = list(sharing.shared_with_me(db, current_user).keys())
        q = q.filter(or_(Schedule.owner_id == current_user.id, Schedule.id.in_(shared_ids or [-1])))
    if schedule_type and schedule_type != "all":
        q = q.filter(Schedule.schedule_type == schedule_type)
    all_schedules = q.order_by(Schedule.id.desc()).all()
    filtered = [s for s in all_schedules if not (s.name or "").startswith("[Ad-hoc]")]
    if not filtered:
        return []

    # Bulk lookups
    script_ids    = {s.script_id    for s in filtered if s.script_id}
    dashboard_ids = {s.dashboard_id for s in filtered if s.dashboard_id}

    scripts_map    = {s.id: s for s in db.query(Script).filter(Script.id.in_(script_ids)).all()}    if script_ids    else {}
    from models import SharepointSite
    site_ids = {s.sharepoint_site_id for s in filtered if s.sharepoint_site_id}
    site_names = dict(db.query(SharepointSite.id, SharepointSite.name).filter(SharepointSite.id.in_(site_ids)).all()) if site_ids else {}
    shares = sharing.share_info(db, current_user, filtered)
    dashboards_map = {d.id: d for d in db.query(Dashboard).filter(Dashboard.id.in_(dashboard_ids)).all()} if dashboard_ids else {}

    # Bulk last run logs for script schedules
    sched_script_ids = [s.script_id for s in filtered if s.schedule_type == "script" and s.script_id]
    sched_tableau_ids = [s.id for s in filtered if s.schedule_type == "tableau"]
    last_log_by_script: Dict[int, RunLog] = {}
    last_log_by_schedule: Dict[int, RunLog] = {}

    if sched_script_ids:
        subq = (db.query(RunLog.script_id, func.max(RunLog.started_at).label("mx"))
                .filter(RunLog.script_id.in_(sched_script_ids))
                .group_by(RunLog.script_id).subquery())
        for l in db.query(RunLog).join(subq, (RunLog.script_id == subq.c.script_id) & (RunLog.started_at == subq.c.mx)).all():
            last_log_by_script[l.script_id] = l

    if sched_tableau_ids:
        subq2 = (db.query(RunLog.schedule_id, func.max(RunLog.started_at).label("mx"))
                 .filter(RunLog.schedule_id.in_(sched_tableau_ids))
                 .group_by(RunLog.schedule_id).subquery())
        for l in db.query(RunLog).join(subq2, (RunLog.schedule_id == subq2.c.schedule_id) & (RunLog.started_at == subq2.c.mx)).all():
            last_log_by_schedule[l.schedule_id] = l

    results = []
    for s in filtered:
        sc = scripts_map.get(s.script_id)
        db_ = dashboards_map.get(s.dashboard_id)
        if s.schedule_type == "script":
            name = sc.name if sc else (s.name or f"Script #{s.script_id}")
        elif s.schedule_type == "tableau":
            name = s.name or (db_.name if db_ else f"Tableau #{s.id}")
        elif s.schedule_type == "sharepoint":
            name = s.name or f"SharePoint #{s.id}"
        else:
            name = s.name or f"Schedule #{s.id}"

        try:    view_urls = json.loads(s.view_urls_json or "[]")
        except: view_urls = []

        # APScheduler lookup — fast, in-memory, no DB call
        next_run_utc = None
        try:
            if s.is_active:
                next_run_utc = get_next_run_utc(s.id, s.schedule_type or "script")
        except Exception:
            pass

        last_log = last_log_by_script.get(s.script_id) if s.schedule_type == "script" and s.script_id else \
                   last_log_by_schedule.get(s.id)

        results.append({
            "id":               s.id,
            "schedule_type":    s.schedule_type,
            "name":             name,
            "script_id":        s.script_id,
            "script_name":      sc.name if sc else None,
            "frequency":        s.frequency,
            "run_time":         s.run_time,
            "days_of_week":     s.days_of_week or [],
            "week_of_month":    s.week_of_month,
            "start_date":       s.start_date,
            "dashboard_id":     s.dashboard_id,
            "dashboard_name":   db_.name if db_ else None,
            "email_to":         s.email_to,
            "cc_to":            s.cc_to,
            "fmt":              s.fmt,
            "view_urls":        view_urls,
            "filters":          json.loads(s.filters_json or "{}"),
            "recurrence":       s.recurrence,
            "run_at_utc":       s.run_at_utc,
            "timezone":         s.timezone,
            "interval_hours":   s.interval_hours,
            "hourly_end_time":  s.hourly_end_time,
            "is_active":        s.is_active,
            "email_on_success": s.email_on_success,
            "email_on_failure": s.email_on_failure,
            "recipients":       s.recipients or [],
            "owner":            s.owner,
            "status":           s.status,
            "last_run_utc":     last_log.started_at if last_log else s.last_run_utc,
            "last_run_status":  last_log.status     if last_log else s.last_run_status,
            "last_error":       getattr(s, "last_error", None),
            "next_run_utc":     next_run_utc,
            "created_at":       s.created_at,
            "owner_name":       s.owner.name  if s.owner else None,
            "owner_email":      s.owner.email if s.owner else None,
            "sharepoint_site_id": s.sharepoint_site_id,
            "sharepoint_folder":  s.sharepoint_folder,
            "output_file_path":   getattr(s, "output_file_path", None),
            "append_timestamp_to_filename": bool(getattr(s, "append_timestamp_to_filename", False)),
            "source_folder":        getattr(s, "source_folder", None),
            "filename_pattern":     getattr(s, "filename_pattern", None),
            "date_format":          getattr(s, "date_format", None),
            "target_period":        getattr(s, "target_period", "current"),
            "destination_filename": getattr(s, "destination_filename", None),
            "upload_mode":          getattr(s, "upload_mode", "replace") or "replace",
            "target_sheet":         getattr(s, "target_sheet", None),
            "target_table":         getattr(s, "target_table", None),
            "notify_email_to":      getattr(s, "notify_email_to", None),
            "notify_cc_to":         getattr(s, "notify_cc_to", None),
            "sharepoint_site_name": site_names.get(s.sharepoint_site_id),
            **shares.get(s.id, {}),
        })
    return results


# ── Script schedule CRUD ──────────────────────────────────────────────────────

@router.post("/script", response_model=ScheduleOut)
def create_script_schedule(
    body: ScriptScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sc = db.query(Script).filter(Script.id == body.script_id).first()
    if not sc:
        raise HTTPException(400, "Script not found")
    if not is_admin(current_user) and sc.owner_id != current_user.id:
        raise HTTPException(403, "Cannot schedule a script you don't own")
    s = Schedule(
        schedule_type    = "script",
        name             = sc.name,   # snapshot script name into schedule row
        script_id        = body.script_id,
        frequency        = body.frequency,
        recurrence       = body.frequency if body.frequency in ("once", "hourly") else "once",
        run_time         = body.run_time,
        days_of_week     = body.days_of_week,
        week_of_month    = body.week_of_month,
        start_date       = _parse_start_date(body.start_date),
        run_at_utc       = _parse_run_at_local(body.run_at_local, body.timezone),
        timezone         = body.timezone,
        interval_hours   = body.interval_hours,
        hourly_end_time  = body.hourly_end_time,
        is_active        = body.is_active,
        email_on_success = body.email_on_success,
        email_on_failure = body.email_on_failure,
        recipients       = body.recipients,
        owner_id         = current_user.id,
        sharepoint_site_id = body.sharepoint_site_id,
        sharepoint_folder  = body.sharepoint_folder,
        output_file_path   = body.output_file_path,
        append_timestamp_to_filename = body.append_timestamp_to_filename,
        upload_mode        = (body.upload_mode or "replace"),
        target_sheet       = body.target_sheet,
        target_table       = body.target_table,
    )
    db.add(s); db.commit(); db.refresh(s)
    from services.scheduler import add_or_update_schedule
    add_or_update_schedule(s)
    return _out(s, db, current_user)


@router.put("/script/{schedule_id}", response_model=ScheduleOut)
def update_script_schedule(
    schedule_id: int,
    body: ScriptScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = db.query(Schedule).filter(Schedule.id == schedule_id,
                                  Schedule.schedule_type == "script").first()
    if not s:
        raise HTTPException(404, "Script schedule not found")
    role = sharing.require(db, current_user, s, "edit")
    keep_site = s.sharepoint_site_id
    # Keep name in sync with script name
    if s.script_id:
        sc2 = db.query(Script).filter(Script.id == s.script_id).first()
        if sc2:
            s.name = sc2.name
    s.frequency        = body.frequency
    s.recurrence       = body.frequency if body.frequency in ("once", "hourly") else s.recurrence or "once"
    s.run_time         = body.run_time
    s.days_of_week     = body.days_of_week
    s.week_of_month    = body.week_of_month
    s.start_date       = _parse_start_date(body.start_date)
    s.timezone         = body.timezone
    s.interval_hours   = body.interval_hours
    s.hourly_end_time  = body.hourly_end_time
    if body.run_at_local:
        run_at_utc = _parse_run_at_local(body.run_at_local, body.timezone)
        if run_at_utc:
            s.run_at_utc = run_at_utc
    s.is_active        = body.is_active
    s.email_on_success = body.email_on_success
    s.email_on_failure = body.email_on_failure
    s.recipients       = body.recipients
    s.sharepoint_site_id = body.sharepoint_site_id
    s.sharepoint_folder  = body.sharepoint_folder
    s.output_file_path   = body.output_file_path
    s.append_timestamp_to_filename = body.append_timestamp_to_filename
    s.upload_mode        = (body.upload_mode or "replace")
    s.target_sheet       = body.target_sheet
    s.target_table       = body.target_table
    if role == "edit":
        # People it's shared with can't swap the owner's SharePoint site.
        s.sharepoint_site_id = keep_site
    _mark_edited(s, current_user)
    db.commit(); db.refresh(s)
    from services.scheduler import add_or_update_schedule
    add_or_update_schedule(s)
    return _out(s, db, current_user)


@router.patch("/{schedule_id}/toggle", response_model=ScheduleOut)
def toggle_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not s:
        raise HTTPException(404, "Schedule not found")
    sharing.require(db, current_user, s, "edit")
    s.is_active = not s.is_active
    _mark_edited(s, current_user)
    db.commit(); db.refresh(s)
    from services.scheduler import add_or_update_schedule, remove_schedule
    if s.is_active:
        add_or_update_schedule(s)
    else:
        remove_schedule(s.id, s.schedule_type)
    return _out(s, db, current_user)


@router.delete("/{schedule_id}")
def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not s:
        raise HTTPException(404, "Schedule not found")
    sharing.require(db, current_user, s, "owner")
    from services.scheduler import remove_schedule
    remove_schedule(s.id, s.schedule_type)
    from models import ScheduleShare
    db.query(ScheduleShare).filter(ScheduleShare.schedule_id == schedule_id).delete(synchronize_session=False)
    # Null out run log references BEFORE deleting so SQLite ID reuse
    # can't cause orphaned logs to leak into a future schedule's history.
    from models import RunLog
    db.query(RunLog).filter(RunLog.schedule_id == schedule_id).update(
        {"schedule_id": None}, synchronize_session=False
    )
    db.delete(s); db.commit()
    return {"ok": True}


# ── Tableau schedule CRUD ─────────────────────────────────────────────────────

@router.post("/tableau", response_model=ScheduleOut)
def create_tableau_schedule(
    body: TableauScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.dashboard_id:
        d = db.query(Dashboard).filter(Dashboard.id == body.dashboard_id).first()
        if not d:
            raise HTTPException(400, "Dashboard not found")
        if not is_admin(current_user) and d.owner_id != current_user.id:
            raise HTTPException(403, "Cannot schedule a dashboard you don't own")

    run_at_utc = _parse_run_at_local(body.run_at_local, body.timezone)
    s = Schedule(
        schedule_type  = "tableau",
        name           = body.name,
        dashboard_id   = body.dashboard_id,
        email_to       = body.email_to,
        cc_to          = body.cc_to,
        fmt            = body.fmt,
        view_urls_json = json.dumps(body.view_urls or []),
        filters_json   = json.dumps(body.filters or {}),
        recurrence     = body.recurrence,
        interval_hours = body.interval_hours,
        hourly_end_time = body.hourly_end_time,
        run_at_utc     = run_at_utc,
        timezone       = body.timezone,
        is_active      = body.is_active,
        days_of_week   = body.days_of_week or [],
        week_of_month  = body.week_of_month or "start",
        status         = "scheduled",
        owner_id       = current_user.id,
        sharepoint_site_id = body.sharepoint_site_id,
        sharepoint_folder  = body.sharepoint_folder,
    )
    db.add(s); db.commit(); db.refresh(s)
    from services.scheduler import add_or_update_schedule
    add_or_update_schedule(s)
    return _out(s, db, current_user)


@router.put("/tableau/{schedule_id}", response_model=ScheduleOut)
def update_tableau_schedule(
    schedule_id: int,
    body: TableauScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = db.query(Schedule).filter(Schedule.id == schedule_id,
                                  Schedule.schedule_type == "tableau").first()
    if not s:
        raise HTTPException(404, "Tableau schedule not found")
    role = sharing.require(db, current_user, s, "edit")
    keep_site = s.sharepoint_site_id

    s.name           = body.name
    s.email_to       = body.email_to
    s.cc_to          = body.cc_to
    s.fmt            = body.fmt
    s.view_urls_json = json.dumps(body.view_urls or [])
    s.filters_json   = json.dumps(body.filters or {})
    s.recurrence     = body.recurrence
    s.interval_hours = body.interval_hours
    s.hourly_end_time = body.hourly_end_time
    s.timezone       = body.timezone
    s.is_active      = body.is_active
    s.days_of_week   = body.days_of_week or []
    s.week_of_month  = body.week_of_month or "start"
    s.sharepoint_site_id = body.sharepoint_site_id
    s.sharepoint_folder  = body.sharepoint_folder
    if body.run_at_local:
        run_at_utc = _parse_run_at_local(body.run_at_local, body.timezone)
        if run_at_utc:
            s.run_at_utc = run_at_utc
    if body.dashboard_id and role != "edit":
        # People it's shared with can't swap the owner's dashboard or site.
        s.dashboard_id = body.dashboard_id
    if role == "edit":
        s.sharepoint_site_id = keep_site
    _mark_edited(s, current_user)
    s.status = "scheduled"
    db.commit(); db.refresh(s)
    from services.scheduler import add_or_update_schedule
    add_or_update_schedule(s)
    return _out(s, db, current_user)


@router.post("/{schedule_id}/run_now")
def run_now(
    schedule_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not s:
        raise HTTPException(404, "Schedule not found")
    sharing.require(db, current_user, s, "edit")

    if s.schedule_type == "tableau":
        from services.tableau_runner import run_tableau_schedule
        background_tasks.add_task(run_tableau_schedule, s.id, current_user.email)
    elif s.schedule_type == "sharepoint":
        from services.sharepoint_runner import run_sharepoint_schedule
        background_tasks.add_task(run_sharepoint_schedule, s.id, current_user.email)
    else:
        if not s.script_id:
            raise HTTPException(400, "No script linked to this schedule")
        from services.runner import run_script
        background_tasks.add_task(run_script, s.script_id, "manual", current_user.email, s.id)

    return {"ok": True, "message": f"Schedule '{s.name or s.id}' queued for immediate run"}


# ── SharePoint schedule CRUD ──────────────────────────────────────────────────

@router.post("/sharepoint", response_model=ScheduleOut)
def create_sharepoint_schedule(
    body: SharepointScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run_at_utc = _parse_run_at_local(body.run_at_local, body.timezone)
    s = Schedule(
        schedule_type        = "sharepoint",
        name                 = body.name,
        sharepoint_site_id   = body.sharepoint_site_id,
        sharepoint_folder    = body.sharepoint_folder,
        recurrence           = body.recurrence,
        run_at_utc           = run_at_utc,
        timezone             = body.timezone,
        days_of_week         = [d.strip() for d in (body.days_of_week or "").split(",") if d.strip()],
        week_of_month        = body.week_of_month or "start",
        is_active            = body.is_active,
        owner_id             = current_user.id,
        created_by           = current_user.sam_account_name or current_user.email,
        created_by_name      = current_user.name,
        status               = "scheduled",
    )
    # SP file fields
    for col in ("source_path","source_folder","filename_pattern","date_format","target_period",
                "destination_filename","output_file_path","append_timestamp_to_filename",
                "notify_email_to","notify_cc_to","email_on_success","email_on_failure",
                "interval_hours","hourly_end_time"):
        try: setattr(s, col, getattr(body, col, None))
        except Exception: pass
    for col in ("upload_mode","target_sheet","target_table"):
        try: setattr(s, col, getattr(body, col, None))
        except Exception: pass
    db.add(s); db.commit(); db.refresh(s)
    from services.scheduler import add_or_update_schedule
    if s.is_active:
        add_or_update_schedule(s)
    log.info(f"[schedules] Created sharepoint schedule id={s.id} by {current_user.email}")
    return _out(s, db, current_user)


@router.put("/sharepoint/{schedule_id}", response_model=ScheduleOut)
def update_sharepoint_schedule(
    schedule_id: int,
    body: SharepointScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = db.query(Schedule).filter(
        Schedule.id == schedule_id,
        Schedule.schedule_type == "sharepoint"
    ).first()
    if not s:
        raise HTTPException(404, "SharePoint schedule not found")
    role = sharing.require(db, current_user, s, "edit")

    s.name               = body.name
    if role != "edit":
        # People it's shared with can't swap the owner's SharePoint site.
        s.sharepoint_site_id = body.sharepoint_site_id
    s.sharepoint_folder  = body.sharepoint_folder
    s.recurrence         = body.recurrence
    s.timezone           = body.timezone
    s.days_of_week       = [d.strip() for d in (body.days_of_week or "").split(",") if d.strip()]
    s.week_of_month      = body.week_of_month or "start"
    s.is_active          = body.is_active
    if body.run_at_local:
        s.run_at_utc = _parse_run_at_local(body.run_at_local, body.timezone)
    for col in ("source_path","source_folder","filename_pattern","date_format","target_period",
                "destination_filename","output_file_path","append_timestamp_to_filename",
                "notify_email_to","notify_cc_to","email_on_success","email_on_failure",
                "interval_hours","hourly_end_time",
                "upload_mode","target_sheet","target_table"):
        try: setattr(s, col, getattr(body, col, None))
        except Exception: pass
    s.status = "scheduled"
    _mark_edited(s, current_user)
    db.commit(); db.refresh(s)
    from services.scheduler import add_or_update_schedule, remove_schedule
    if s.is_active:
        add_or_update_schedule(s)
    else:
        remove_schedule(s.id, "sharepoint")
    return _out(s, db, current_user)


# ── Sharing ───────────────────────────────────────────────────────────────────
# Only the owner (or an admin) can see and change who a schedule is shared with.

def _share_rows(db: Session, schedule_id: int) -> list:
    from models import ScheduleShare
    rows = db.query(ScheduleShare).filter(ScheduleShare.schedule_id == schedule_id).order_by(ScheduleShare.created_at).all()
    ids = {r.user_id for r in rows} | {r.shared_by_id for r in rows}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}
    out = []
    for r in rows:
        u = users.get(r.user_id)
        if not u:
            continue
        by = users.get(r.shared_by_id)
        out.append({"user_id": u.id, "name": u.name, "email": u.email, "access": r.access,
                    "created_at": r.created_at, "shared_by_name": by.name if by else None})
    return out


def _check_access_value(access: str) -> str:
    a = (access or "").lower()
    if a not in ("edit", "view"):
        raise HTTPException(400, "Access must be 'edit' or 'view'")
    return a


@router.get("/{schedule_id}/shares", response_model=List[ShareOut])
def list_shares(schedule_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    sharing.require(db, current_user, s, "owner")
    return _share_rows(db, schedule_id)


def _notify_share(bg: BackgroundTasks, db: Session, request: Request, kind: str, s: Schedule, target: User, actor: User, access: str = "", old_access: str = ""):
    """Email the person about their access, after the response is sent (a mail problem never blocks sharing)."""
    if not target or not target.email:
        return
    from services.email_service import send_share_notification
    nxt = None
    if s.is_active:
        try:
            from services.scheduler import get_next_run_utc
            nxt = get_next_run_utc(s.id, s.schedule_type or "script")
        except Exception:
            nxt = None
    bg.add_task(send_share_notification, kind=kind, to_email=target.email, actor_name=actor.name or actor.email,
                schedule_id=s.id, schedule_name=_sched_display_name(s, db), schedule_type=s.schedule_type or "script",
                access=access, old_access=old_access, next_run_utc=nxt, app_url=_app_url(request))


# Conductor's public address, used for the "Open in Conductor" button in sharing emails.
# CONDUCTOR_URL in .env overrides it (e.g. on a test PC).
DEFAULT_APP_URL = "https://conductor.medpointmanagement.com"


def _app_url(request: Request) -> str:
    env = (os.getenv("CONDUCTOR_URL") or "").strip()
    return (env or DEFAULT_APP_URL).rstrip("/")


def _sched_display_name(s: Schedule, db: Session) -> str:
    """Same name the Schedules page shows (script schedules go by their script's name)."""
    if (s.schedule_type or "script") == "script" and s.script_id:
        sc = db.query(Script).filter(Script.id == s.script_id).first()
        if sc and sc.name:
            return sc.name
    return s.name or f"Schedule #{s.id}"


@router.post("/{schedule_id}/shares", response_model=List[ShareOut])
def add_share(schedule_id: int, body: ShareIn, bg: BackgroundTasks, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from models import ScheduleShare
    s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    sharing.require(db, current_user, s, "owner")
    access = _check_access_value(body.access)
    target = db.query(User).filter(User.id == body.user_id, User.is_active == True).first()
    if not target:
        raise HTTPException(404, "User not found")
    if target.id == s.owner_id:
        raise HTTPException(400, "That person already owns this schedule")
    row = db.query(ScheduleShare).filter(ScheduleShare.schedule_id == s.id, ScheduleShare.user_id == target.id).first()
    old = row.access if row else None
    if row:
        row.access = access
    else:
        db.add(ScheduleShare(schedule_id=s.id, user_id=target.id, access=access, shared_by_id=current_user.id))
    db.commit()
    log.info(f"[schedules] Shared schedule id={s.id} with {target.email} ({access}) by {current_user.email}")
    if old is None:
        _notify_share(bg, db, request, "shared", s, target, current_user, access)
    elif old != access:
        _notify_share(bg, db, request, "changed", s, target, current_user, access, old)
    return _share_rows(db, s.id)


@router.patch("/{schedule_id}/shares/{user_id}", response_model=List[ShareOut])
def change_share(schedule_id: int, user_id: int, body: ShareAccessIn, bg: BackgroundTasks, request: Request, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    from models import ScheduleShare
    s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    sharing.require(db, current_user, s, "owner")
    row = db.query(ScheduleShare).filter(ScheduleShare.schedule_id == s.id, ScheduleShare.user_id == user_id).first()
    if not row:
        raise HTTPException(404, "Not shared with this person")
    old, new = row.access, _check_access_value(body.access)
    row.access = new
    db.commit()
    if old != new:
        _notify_share(bg, db, request, "changed", s, db.query(User).filter(User.id == user_id).first(), current_user, new, old)
    return _share_rows(db, s.id)


@router.delete("/{schedule_id}/shares/{user_id}", response_model=List[ShareOut])
def remove_share(schedule_id: int, user_id: int, bg: BackgroundTasks, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from models import ScheduleShare
    s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    sharing.require(db, current_user, s, "owner")
    had = db.query(ScheduleShare).filter(ScheduleShare.schedule_id == s.id, ScheduleShare.user_id == user_id).first() is not None
    db.query(ScheduleShare).filter(ScheduleShare.schedule_id == s.id, ScheduleShare.user_id == user_id).delete(synchronize_session=False)
    db.commit()
    if had:
        _notify_share(bg, db, request, "removed", s, db.query(User).filter(User.id == user_id).first(), current_user)
    log.info(f"[schedules] Removed share schedule id={s.id} user_id={user_id} by {current_user.email}")
    return _share_rows(db, s.id)


from fastapi import BackgroundTasks  # noqa: F811 — ensure import is present
router.routes