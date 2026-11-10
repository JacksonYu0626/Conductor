"""
routers/dashboards.py — CRUD for registered Tableau dashboards.
"""
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from database import get_db
from models import Dashboard, Schedule, RunLog, User
from schemas import DashboardCreate, DashboardUpdate, DashboardRunNow, DashboardOut
from deps import get_current_user, is_admin
from typing import List, Optional, Dict

log = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboards", tags=["dashboards"])


def _enrich(d: Dashboard, db: Session) -> dict:
    last_log = (
        db.query(RunLog)
        .filter(
            RunLog.log_type == "tableau",
            RunLog.schedule_id.in_(
                db.query(Schedule.id).filter(Schedule.dashboard_id == d.id)
            )
        )
        .order_by(desc(RunLog.started_at))
        .first()
    )
    schedule_count = db.query(Schedule).filter(
        Schedule.dashboard_id == d.id,
        Schedule.is_active == True
    ).count()

    try:
        additional_urls = json.loads(d.additional_urls_json or "[]")
    except Exception:
        additional_urls = []
    try:
        filters = json.loads(d.filters_json or "{}")
    except Exception:
        filters = {}

    return {
        "id":              d.id,
        "name":            d.name,
        "description":     d.description,
        "category":        d.category,
        "view_url":        d.view_url,
        "additional_urls": additional_urls,
        "filters":         filters,
        "fmt":             d.fmt or "pdf",
        "is_active":       d.is_active,
        "owner":           d.owner,
        "created_at":      d.created_at,
        "last_run":        last_log.started_at if last_log else None,
        "last_status":     last_log.status if last_log else None,
        "schedule_count":  schedule_count,
    }


@router.get("/", response_model=List[DashboardOut])
def list_dashboards(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import func

    q = db.query(Dashboard).filter(Dashboard.is_active == True)
    if not is_admin(current_user):
        q = q.filter(Dashboard.owner_id == current_user.id)
    dashboards = q.all()
    if not dashboards:
        return []

    dashboard_ids = [d.id for d in dashboards]

    # Bulk: all active schedule IDs grouped by dashboard_id
    sched_rows = (
        db.query(Schedule.id, Schedule.dashboard_id)
        .filter(Schedule.dashboard_id.in_(dashboard_ids))
        .all()
    )
    # map dashboard_id → list of schedule_ids
    dash_sched_map: Dict[int, list] = {}
    for sid, did in sched_rows:
        dash_sched_map.setdefault(did, []).append(sid)

    # Active schedule counts
    active_counts = (
        db.query(Schedule.dashboard_id, func.count(Schedule.id).label("cnt"))
        .filter(Schedule.dashboard_id.in_(dashboard_ids), Schedule.is_active == True)
        .group_by(Schedule.dashboard_id)
        .all()
    )
    count_map = {r.dashboard_id: r.cnt for r in active_counts}

    # Bulk: last tableau log per dashboard
    all_sched_ids = [sid for sids in dash_sched_map.values() for sid in sids]
    last_log_map: Dict[int, RunLog] = {}
    if all_sched_ids:
        subq = (
            db.query(RunLog.schedule_id, func.max(RunLog.started_at).label("max_started"))
            .filter(RunLog.log_type == "tableau", RunLog.schedule_id.in_(all_sched_ids))
            .group_by(RunLog.schedule_id)
            .subquery()
        )
        last_logs = (
            db.query(RunLog)
            .join(subq, (RunLog.schedule_id == subq.c.schedule_id) & (RunLog.started_at == subq.c.max_started))
            .all()
        )
        # map schedule_id → log, then map to dashboard_id
        sched_to_log = {l.schedule_id: l for l in last_logs}
        for did, sids in dash_sched_map.items():
            best = None
            for sid in sids:
                l = sched_to_log.get(sid)
                if l and (best is None or l.started_at > best.started_at):
                    best = l
            if best:
                last_log_map[did] = best

    results = []
    for d in dashboards:
        try:    additional_urls = json.loads(d.additional_urls_json or "[]")
        except: additional_urls = []
        try:    filters = json.loads(d.filters_json or "{}")
        except: filters = {}
        last_log = last_log_map.get(d.id)
        results.append({
            "id":              d.id,
            "name":            d.name,
            "description":     d.description,
            "category":        d.category,
            "view_url":        d.view_url,
            "additional_urls": additional_urls,
            "filters":         filters,
            "fmt":             d.fmt or "pdf",
            "is_active":       d.is_active,
            "owner":           d.owner,
            "created_at":      d.created_at,
            "last_run":        last_log.started_at if last_log else None,
            "last_status":     last_log.status     if last_log else None,
            "schedule_count":  count_map.get(d.id, 0),
        })
    return results


@router.get("/search/views")
def search_tableau_views(
    q: str = Query(default=""),
    current_user: User = Depends(get_current_user),
):
    try:
        from services.tableau_client import TableauClient
        client  = TableauClient()
        results = client.search_views(q)
        return {"results": results}
    except Exception as e:
        raise HTTPException(503, f"Tableau search unavailable: {e}")


@router.get("/{dashboard_id}", response_model=DashboardOut)
def get_dashboard(
    dashboard_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    d = db.query(Dashboard).filter(Dashboard.id == dashboard_id).first()
    if not d:
        raise HTTPException(404, "Dashboard not found")
    if not is_admin(current_user) and d.owner_id != current_user.id:
        raise HTTPException(403, "Not authorized")
    return _enrich(d, db)


@router.post("/", response_model=DashboardOut)
def create_dashboard(
    body: DashboardCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    d = Dashboard(
        name                 = body.name,
        description          = body.description,
        category             = body.category,
        view_url             = body.view_url,
        additional_urls_json = json.dumps(body.additional_urls or []),
        filters_json         = json.dumps(body.filters or {}),
        fmt                  = body.fmt,
        owner_id             = current_user.id,
    )
    db.add(d); db.commit(); db.refresh(d)
    return _enrich(d, db)


@router.put("/{dashboard_id}", response_model=DashboardOut)
def update_dashboard(
    dashboard_id: int,
    body: DashboardUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    d = db.query(Dashboard).filter(Dashboard.id == dashboard_id).first()
    if not d:
        raise HTTPException(404, "Dashboard not found")
    if not is_admin(current_user) and d.owner_id != current_user.id:
        raise HTTPException(403, "Not authorized to edit this dashboard")
    data = body.model_dump(exclude_unset=True)
    if "additional_urls" in data:
        d.additional_urls_json = json.dumps(data.pop("additional_urls") or [])
    if "filters" in data:
        d.filters_json = json.dumps(data.pop("filters") or {})
    for k, v in data.items():
        setattr(d, k, v)
    db.commit(); db.refresh(d)
    return _enrich(d, db)


@router.delete("/{dashboard_id}")
def delete_dashboard(
    dashboard_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    d = db.query(Dashboard).filter(Dashboard.id == dashboard_id).first()
    if not d:
        raise HTTPException(404, "Dashboard not found")
    if not is_admin(current_user) and d.owner_id != current_user.id:
        raise HTTPException(403, "Not authorized to delete this dashboard")
    # 1. Remove APScheduler jobs + delete all linked schedules from DB
    from services.scheduler import remove_schedule
    linked_schedules = db.query(Schedule).filter(Schedule.dashboard_id == dashboard_id).all()
    for sched in linked_schedules:
        remove_schedule(sched.id, sched.schedule_type or "tableau")
        db.delete(sched)

    # 2. Null out dashboard_id on RunLogs so history is preserved but won't
    #    accidentally link to a future dashboard that reuses the same DB row.
    #    Commit immediately so the DB-level ondelete="CASCADE" has no RunLogs
    #    left to delete when we remove the dashboard row below.
    db.query(RunLog).filter(
        RunLog.schedule_id.in_(
            db.query(Schedule.id).filter(Schedule.dashboard_id == dashboard_id)
        )
    ).update({"schedule_id": None}, synchronize_session=False)
    db.commit()

    # 3. Delete the dashboard record itself
    db.delete(d)
    db.commit()
    return {"ok": True}


@router.post("/{dashboard_id}/run")
def run_dashboard_now(
    dashboard_id: int,
    body: DashboardRunNow,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    d = db.query(Dashboard).filter(Dashboard.id == dashboard_id).first()
    if not d:
        raise HTTPException(404, "Dashboard not found")
    if not is_admin(current_user) and d.owner_id != current_user.id:
        raise HTTPException(403, "Not authorized to run this dashboard")

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    view_urls = [d.view_url]
    try:
        extra = json.loads(d.additional_urls_json or "[]")
        view_urls += extra
    except Exception:
        pass

    s = Schedule(
        schedule_type  = "tableau",
        name           = f"[Ad-hoc] {d.name}",
        dashboard_id   = dashboard_id,
        email_to       = body.email_to,
        cc_to          = body.cc_to,
        fmt            = body.fmt or d.fmt or "pdf",
        view_urls_json = json.dumps(view_urls),
        filters_json   = json.dumps(body.filters or {}),
        recurrence     = "once",
        run_at_utc     = now,
        status         = "running",
        is_active      = False,
        owner_id       = current_user.id,
    )
    db.add(s); db.commit(); db.refresh(s)

    from services.tableau_runner import run_tableau_schedule
    background_tasks.add_task(run_tableau_schedule, s.id, current_user.email)
    return {"ok": True, "message": f"Dashboard '{d.name}' queued for delivery", "schedule_id": s.id}


@router.post("/{dashboard_id}/pause_schedules")
def pause_all_schedules(
    dashboard_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admin action: pause all active schedules for a dashboard."""
    if not is_admin(current_user):
        raise HTTPException(403, "Admin access required")
    schedules = db.query(Schedule).filter(
        Schedule.dashboard_id == dashboard_id,
        Schedule.is_active == True
    ).all()
    from services.scheduler import remove_schedule
    for s in schedules:
        s.is_active = False
        remove_schedule(s.id, s.schedule_type)
    db.commit()
    return {"ok": True, "paused": len(schedules)}
