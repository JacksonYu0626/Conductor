from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from database import get_db
from models import RunLog, Script, Schedule, User
from schemas import RunLogOut
from deps import get_current_user, is_admin
from typing import List, Optional, Dict

_SYSTEM_TRIGGERS = {"system", "scheduler", "manual", "", None}

router = APIRouter(prefix="/logs", tags=["logs"])


def _owned_ids(db: Session, user: User, need: str = "view"):
    """
    Script and schedule ids whose runs this user may see: their own, plus
    schedules shared with them (and, for shared script schedules, that
    script's runs). need="edit" leaves out view-only shares.
    """
    from services.sharing import shared_scope
    script_ids   = [s.id for s in db.query(Script.id).filter(Script.owner_id == user.id).all()]
    schedule_ids = [s.id for s in db.query(Schedule.id).filter(Schedule.owner_id == user.id).all()]
    sh_sched, sh_scripts = shared_scope(db, user, need)
    return sorted(set(script_ids) | set(sh_scripts)), sorted(set(schedule_ids) | set(sh_sched))


def _can_see_log(log: RunLog, db: Session, user: User, need: str = "view") -> bool:
    """Admins see every run; everyone else their own runs and runs of schedules shared with them."""
    if is_admin(user):
        return True
    if log.owner_id == user.id:
        return True
    script_ids, schedule_ids = _owned_ids(db, user, need)
    return (log.script_id in script_ids) or (log.schedule_id in schedule_ids)


def _enrich(log: RunLog, db: Session, name_map: Optional[Dict[str, str]] = None) -> dict:
    script_name   = None
    schedule_name = None

    if log.script_id:
        sc = db.query(Script).filter(Script.id == log.script_id).first()
        script_name = sc.name if sc else None

    if log.schedule_name:
        schedule_name = log.schedule_name
    elif log.schedule_id:
        s = db.query(Schedule).filter(Schedule.id == log.schedule_id).first()
        schedule_name = s.name if s else None

    tb = (log.triggered_by or "").strip()
    is_system = tb.lower() in _SYSTEM_TRIGGERS

    # Use snapshotted name first — survives script/schedule/dashboard deletion
    stored_name = getattr(log, "triggered_by_name", "") or ""

    if is_system:
        triggered_by_email = "Scheduler"
        if stored_name:
            triggered_by_name = stored_name
        else:
            # Fallback: resolve from live schedule/script owner (pre-snapshot logs)
            triggered_by_name = ""
            if log.schedule_id:
                s = db.query(Schedule).filter(Schedule.id == log.schedule_id).first()
                if s and s.owner_id:
                    owner = db.query(User).filter(User.id == s.owner_id).first()
                    if owner:
                        triggered_by_name = owner.name
            elif log.script_id:
                sc = db.query(Script).filter(Script.id == log.script_id).first()
                if sc and sc.owner_id:
                    owner = db.query(User).filter(User.id == sc.owner_id).first()
                    if owner:
                        triggered_by_name = owner.name
    else:
        triggered_by_email = "Manual"
        if stored_name:
            triggered_by_name = stored_name
        else:
            # Fallback: resolve from email (pre-snapshot logs)
            if name_map is not None:
                triggered_by_name = name_map.get(tb.lower(), tb)
            else:
                u = db.query(User).filter(User.email == tb).first()
                triggered_by_name = u.name if u else tb

    # Fetch email fields based on log type
    email_to        = ""
    cc_to           = ""
    recipients      = []
    notify_email_to = ""
    notify_cc_to    = ""
    sp_site_name    = ""
    sp_folder       = ""

    if log.schedule_id:
        sched = db.query(Schedule).filter(Schedule.id == log.schedule_id).first()
        if sched:
            if log.log_type == "tableau":
                email_to = sched.email_to or ""
                cc_to    = sched.cc_to    or ""
                # SP info for Tableau → SP schedules
                if sched.sharepoint_site_id:
                    from models import SharepointSite
                    sp_site = db.query(SharepointSite).filter(SharepointSite.id == sched.sharepoint_site_id).first()
                    if sp_site:
                        sp_site_name = sp_site.name
                        folder = sched.sharepoint_folder or "/"
                        sp_folder = sp_site.site_url.rstrip("/") + folder
            elif log.log_type == "script":
                recipients = sched.recipients or []
            elif log.log_type == "sharepoint":
                notify_email_to = getattr(sched, "notify_email_to", None) or ""
                notify_cc_to    = getattr(sched, "notify_cc_to",    None) or ""
                if sched.sharepoint_site_id:
                    from models import SharepointSite
                    sp_site = db.query(SharepointSite).filter(SharepointSite.id == sched.sharepoint_site_id).first()
                    if sp_site:
                        sp_site_name = sp_site.name
                        folder = sched.sharepoint_folder or "/"
                        sp_folder = sp_site.site_url.rstrip("/") + folder

    return {
        "id":                log.id,
        "log_type":          log.log_type or "script",
        "script_id":         log.script_id,
        "script_name":       script_name or "",
        "schedule_id":       log.schedule_id,
        "schedule_name":     schedule_name or "",
        "trigger":           log.trigger,
        "triggered_by":      triggered_by_email,
        "triggered_by_name": triggered_by_name,
        "status":            log.status,
        "output":            log.output or "",
        "error":             log.error or "",
        "duration_ms":       log.duration_ms or 0,
        "started_at":        log.started_at,
        "finished_at":       log.finished_at,
        "email_to":          email_to,
        "cc_to":             cc_to,
        "recipients":        recipients,
        "notify_email_to":   notify_email_to,
        "notify_cc_to":      notify_cc_to,
        "sp_site_name":      sp_site_name,
        "sp_folder":         sp_folder,
    }


def _filtered(db: Session, current_user: User, script_id=None, log_type=None, date_from=None, date_to=None, name=None):
    """Runs this user may see, narrowed by every Run history filter except status."""
    from datetime import datetime, timedelta
    from sqlalchemy import or_

    q = db.query(RunLog)

    if not is_admin(current_user):
        owned_script_ids, owned_schedule_ids = _owned_ids(db, current_user)
        q = q.filter(or_(
            RunLog.script_id.in_(owned_script_ids or [-1]),
            RunLog.schedule_id.in_(owned_schedule_ids or [-1]),
            RunLog.owner_id == current_user.id,
        ))

    if script_id:
        q = q.filter(RunLog.script_id == script_id)
    if name and name.strip():
        # A run's name is its script's name, or the schedule name for Tableau/SharePoint runs
        like = f"%{name.strip()}%"
        sc_ids = [i for (i,) in db.query(Script.id).filter(Script.name.ilike(like)).all()]
        q = q.filter(or_(RunLog.schedule_name.ilike(like), RunLog.script_id.in_(sc_ids or [-1])))
    if log_type and log_type != "all":
        q = q.filter(RunLog.log_type == log_type)
    try:
        # Dates from the UI are Pacific calendar days; logs are stored in UTC.
        # Convert so a day picked here matches the same day on the charts.
        from services.pacific_time import local_day_start_utc
        if date_from:
            q = q.filter(RunLog.started_at >= local_day_start_utc(date_from))
        if date_to:
            next_day = (datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            q = q.filter(RunLog.started_at < local_day_start_utc(next_day))
    except ValueError:
        pass
    return q


def _status_filter(q, status):
    if not status or status == "all":
        return q
    if status == "running":   # "started" is an older name for running
        return q.filter(RunLog.status.in_(["running", "started"]))
    return q.filter(RunLog.status == status)


# ── Weekday × hour (Run history heatmap) ──────────────────────────────────
# Hours are Pacific local time. With no date range the heatmap (and a clicked
# cell) covers the last 4 weeks.
HEAT_DAYS = 28


def _heat_range(q, date_from, date_to):
    from datetime import datetime, timedelta
    if not date_from and not date_to:
        q = q.filter(RunLog.started_at >= datetime.utcnow() - timedelta(days=HEAT_DAYS))
    return q


def _slot(dt):
    """(weekday Mon=0, hour) of a UTC timestamp, in Pacific time."""
    from services.pacific_time import to_local
    loc = to_local(dt)
    return loc.weekday(), loc.hour


def _slot_ids(q, wd: int, hr: int):
    """Ids of runs in q that started on weekday wd at hour hr (Pacific), newest first."""
    rows = q.with_entities(RunLog.id, RunLog.started_at).order_by(desc(RunLog.started_at)).all()
    return [i for i, st in rows if st is not None and _slot(st) == (wd, hr)]


def _valid_slot(wd, hr):
    return wd is not None and hr is not None and 0 <= wd <= 6 and 0 <= hr <= 23


@router.get("/heatmap")
def heatmap(
    log_type:   Optional[str] = None,
    q:          Optional[str] = None,
    status:     Optional[str] = None,
    date_from:  Optional[str] = Query(default=None),
    date_to:    Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Runs per weekday and hour (Pacific) for the Run history filters.
    n = runs counted (all runs, or only the chosen status); failed = failed runs.
    """
    base = _heat_range(_filtered(db, current_user, log_type=log_type, date_from=date_from, date_to=date_to, name=q),
                       date_from, date_to)
    rows = base.with_entities(RunLog.started_at, RunLog.status).all()
    want = None if not status or status == "all" else ({"running", "started"} if status == "running" else {status})
    grid = [[{"n": 0, "failed": 0} for _ in range(24)] for _ in range(7)]
    for st, stt in rows:
        if st is None:
            continue
        wd, hr = _slot(st)
        c = grid[wd][hr]
        if want is None or stt in want:
            c["n"] += 1
        if stt == "failed":
            c["failed"] += 1
    return {"days": None if (date_from or date_to) else HEAT_DAYS, "grid": grid}


@router.get("/counts")
def count_logs(
    log_type:   Optional[str] = None,
    q:          Optional[str] = None,
    date_from:  Optional[str] = Query(default=None),
    date_to:    Optional[str] = Query(default=None),
    wd:         Optional[int] = None,
    hr:         Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """How many runs match the Run history filters, per status (for the status buttons)."""
    from sqlalchemy import func
    base = _filtered(db, current_user, log_type=log_type, date_from=date_from, date_to=date_to, name=q)
    if _valid_slot(wd, hr):
        # A heatmap cell is picked: count in Python (weekday/hour are Pacific time)
        base = _heat_range(base, date_from, date_to)
        by: Dict[str, int] = {}
        for st, stt in base.with_entities(RunLog.started_at, RunLog.status).all():
            if st is not None and _slot(st) == (wd, hr):
                by[stt or ""] = by.get(stt or "", 0) + 1
    else:
        rows = base.with_entities(RunLog.status, func.count(RunLog.id)).group_by(RunLog.status).all()
        by = {(s or ""): int(n) for s, n in rows}
    return {
        "all":     sum(by.values()),
        "success": by.get("success", 0),
        "failed":  by.get("failed", 0),
        "running": by.get("running", 0) + by.get("started", 0),
        "stopped": by.get("stopped", 0),
    }


@router.get("/", response_model=List[RunLogOut])
def list_logs(
    script_id:  Optional[int] = None,
    status:     Optional[str] = None,
    log_type:   Optional[str] = None,
    q:          Optional[str] = None,
    date_from:  Optional[str] = Query(default=None),
    date_to:    Optional[str] = Query(default=None),
    limit:      Optional[int] = Query(default=None, ge=1, le=5000),
    offset:     int = Query(default=0, ge=0),
    wd:         Optional[int] = None,
    hr:         Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from models import SharepointSite
    name = q
    q = _status_filter(_filtered(db, current_user, script_id, log_type, date_from, date_to, name), status)

    if _valid_slot(wd, hr):
        # Only runs from one heatmap cell (weekday + hour, Pacific time)
        ids = _slot_ids(_heat_range(q, date_from, date_to), wd, hr)
        ids = ids[offset:offset + (limit or 200)]
        by_id = {l.id: l for l in db.query(RunLog).filter(RunLog.id.in_(ids or [-1])).all()}
        logs = [by_id[i] for i in ids if i in by_id]
    else:
        q = q.order_by(desc(RunLog.started_at), desc(RunLog.id))
        # Run history asks for one page at a time (limit + offset).
        # Without a limit: latest 200, or everything when a date range is given
        # (older callers rely on that).
        if offset:
            q = q.offset(offset)
        if limit:
            q = q.limit(limit)
        elif not date_from and not date_to:
            q = q.limit(200)
        logs = q.all()
    if not logs:
        return []

    # ── Bulk lookups — ONE query per entity type ───────────────────────────
    script_ids   = {l.script_id   for l in logs if l.script_id}
    schedule_ids = {l.schedule_id for l in logs if l.schedule_id}

    scripts_map   = {s.id: s for s in db.query(Script).filter(Script.id.in_(script_ids)).all()}   if script_ids   else {}
    schedules_map = {s.id: s for s in db.query(Schedule).filter(Schedule.id.in_(schedule_ids)).all()} if schedule_ids else {}

    # SP sites — only for schedules that have sharepoint_site_id
    sp_site_ids = {s.sharepoint_site_id for s in schedules_map.values() if s.sharepoint_site_id}
    sp_sites_map = {s.id: s for s in db.query(SharepointSite).filter(SharepointSite.id.in_(sp_site_ids)).all()} if sp_site_ids else {}

    # User name map for manual triggers
    emails = {(l.triggered_by or "").strip().lower() for l in logs
              if l.triggered_by and (l.triggered_by or "").lower() not in _SYSTEM_TRIGGERS}
    name_map: Dict[str, str] = {}
    if emails:
        users = db.query(User).filter(User.email.in_(list(emails))).all()
        name_map = {u.email.lower(): u.name for u in users if u.email}

    # ── Build results without any per-row DB calls ─────────────────────────
    results = []
    for log in logs:
        sc    = scripts_map.get(log.script_id)
        sched = schedules_map.get(log.schedule_id)

        script_name   = sc.name    if sc    else ""
        schedule_name = log.schedule_name or (sched.name if sched else "")

        tb       = (log.triggered_by or "").strip()
        is_sys   = tb.lower() in _SYSTEM_TRIGGERS
        stored   = getattr(log, "triggered_by_name", "") or ""

        if is_sys:
            triggered_by_email = "Scheduler"
            triggered_by_name  = stored or (sched.owner.name if sched and sched.owner else "")
        else:
            triggered_by_email = "Manual"
            triggered_by_name  = stored or name_map.get(tb.lower(), tb)

        email_to = cc_to = notify_email_to = notify_cc_to = sp_site_name = sp_folder = ""
        recipients = []

        if sched:
            if log.log_type == "tableau":
                email_to = sched.email_to or ""
                cc_to    = sched.cc_to    or ""
                sp_site  = sp_sites_map.get(sched.sharepoint_site_id)
                if sp_site:
                    sp_site_name = sp_site.name
                    sp_folder    = sp_site.site_url.rstrip("/") + (sched.sharepoint_folder or "/")
            elif log.log_type == "script":
                recipients = sched.recipients or []
            elif log.log_type == "sharepoint":
                notify_email_to = getattr(sched, "notify_email_to", None) or ""
                notify_cc_to    = getattr(sched, "notify_cc_to",    None) or ""
                sp_site = sp_sites_map.get(sched.sharepoint_site_id)
                if sp_site:
                    sp_site_name = sp_site.name
                    sp_folder    = sp_site.site_url.rstrip("/") + (sched.sharepoint_folder or "/")

        results.append({
            "id":                log.id,
            "log_type":          log.log_type or "script",
            "script_id":         log.script_id,
            "script_name":       script_name,
            "schedule_id":       log.schedule_id,
            "schedule_name":     schedule_name,
            "trigger":           log.trigger,
            "triggered_by":      triggered_by_email,
            "triggered_by_name": triggered_by_name,
            "status":            log.status,
            "output":            log.output or "",
            "error":             log.error  or "",
            "duration_ms":       log.duration_ms or 0,
            "started_at":        log.started_at,
            "finished_at":       log.finished_at,
            "email_to":          email_to,
            "cc_to":             cc_to,
            "recipients":        recipients,
            "notify_email_to":   notify_email_to,
            "notify_cc_to":      notify_cc_to,
            "sp_site_name":      sp_site_name,
            "sp_folder":         sp_folder,
        })
    return results


@router.get("/running")
def list_running(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Everything running right now, for the header's "running" indicator.
    Lightweight (no output) and never cached, so it can be polled.
    """
    from sqlalchemy import or_
    from services.runner import _resolve_timeout

    q = db.query(RunLog).filter(RunLog.status.in_(["running", "started"])).order_by(RunLog.started_at)
    if not is_admin(current_user):
        script_ids, schedule_ids = _owned_ids(db, current_user)
        q = q.filter(or_(
            RunLog.script_id.in_(script_ids or [-1]),
            RunLog.schedule_id.in_(schedule_ids or [-1]),
            RunLog.owner_id == current_user.id,
        ))
    rows = q.limit(100).all()
    # View-only shares can watch a run but not stop it
    if is_admin(current_user):
        can_stop = lambda r: True
    else:
        e_scripts, e_scheds = _owned_ids(db, current_user, "edit")
        can_stop = lambda r: r.owner_id == current_user.id or r.script_id in e_scripts or r.schedule_id in e_scheds
    script_ids = {r.script_id for r in rows if r.script_id}
    scripts_map = {s.id: s for s in db.query(Script).filter(Script.id.in_(script_ids)).all()} if script_ids else {}

    out = []
    for r in rows:
        sc = scripts_map.get(r.script_id)
        is_app = bool(sc and getattr(sc, "script_type", "script") == "app")
        timeout_sec = None
        if (r.log_type or "script") == "script" and sc and not is_app:
            timeout_sec = _resolve_timeout(getattr(sc, "timeout_sec", None))
        tb = (r.triggered_by or "").strip()
        out.append({
            "id":                r.id,
            "log_type":          r.log_type or "script",
            "script_id":         r.script_id,
            "schedule_id":       r.schedule_id,
            "name":              (sc.name if sc else "") or r.schedule_name or "",
            "schedule_name":     r.schedule_name or "",
            "trigger":           r.trigger,
            "is_manual":         tb.lower() not in _SYSTEM_TRIGGERS,
            "triggered_by_name": r.triggered_by_name or "",
            "started_at":        r.started_at,
            "timeout_sec":       timeout_sec,
            "is_app":            is_app,
            "can_stop":          bool(can_stop(r)),
        })
    return out


@router.get("/{log_id}", response_model=RunLogOut)
def get_log(
    log_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    log = db.query(RunLog).filter(RunLog.id == log_id).first()
    if not log or not _can_see_log(log, db, current_user):
        raise HTTPException(404, "Log not found")
    return _enrich(log, db)


@router.post("/{log_id}/stop")
def stop_log(
    log_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Mark a running log entry as stopped.
    Used for Tableau/SharePoint runs where we cannot kill the background
    thread directly — this just marks the DB record so it no longer
    shows as 'running' in the UI.
    """
    from datetime import datetime, timezone
    run_log = db.query(RunLog).filter(RunLog.id == log_id).first()
    if not run_log or not _can_see_log(run_log, db, current_user):
        raise HTTPException(404, "Log not found")
    if not _can_see_log(run_log, db, current_user, "edit"):
        raise HTTPException(403, "You can view this schedule but not stop it")
    if run_log.status != "running":
        raise HTTPException(400, f"Log is not running (status: {run_log.status})")

    run_log.status      = "stopped"
    run_log.finished_at = datetime.now(timezone.utc)
    run_log.error       = "Manually stopped by user"
    db.commit()
    return {"ok": True, "message": "Run marked as stopped"}