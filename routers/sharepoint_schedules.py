"""
routers/sharepoint_schedules.py — CRUD for standalone SharePoint upload schedules.
"""
import logging
from datetime import datetime, timezone

import pytz
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from database import get_db
from models import SharepointSchedule, SharepointSite, User
from schemas import SharepointScheduleCreate, SharepointScheduleUpdate, SharepointScheduleOut
from deps import get_current_user, is_admin
from typing import List

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/sharepoint/schedules", tags=["sharepoint"])


def _parse_run_at_utc(run_at_local: str, tz_name: str) -> datetime:
    """Convert YYYY-MM-DDTHH:MM (local) → naive UTC datetime for storage."""
    tz      = pytz.timezone(tz_name or "America/Los_Angeles")
    local_dt = datetime.fromisoformat(run_at_local)
    aware    = tz.localize(local_dt)
    return aware.astimezone(pytz.UTC).replace(tzinfo=None)


def _enrich(s: SharepointSchedule, db: Session) -> dict:
    from services.scheduler import get_next_run_utc
    return {
        "id":                   s.id,
        "name":                 s.name,
        "site_id":              s.site_id,
        "site_name":            s.site.name if s.site else None,
        "source_path":          s.source_path,
        "staged_file_path":     s.staged_file_path,
        "destination_folder":   s.destination_folder,
        "destination_filename": s.destination_filename,
        "recurrence":           s.recurrence,
        "run_at_utc":           s.run_at_utc,
        "timezone":             s.timezone,
        "days_of_week":         s.days_of_week,
        "day_of_month":         s.day_of_month,
        "is_active":            s.is_active,
        "status":               s.status,
        "last_run_utc":         s.last_run_utc,
        "last_run_status":      s.last_run_status,
        "next_run_utc":         get_next_run_utc(s.id, "sharepoint"),
        "owner":                s.owner,
        "created_by_name":      s.created_by_name,
        "created_at":           s.created_at,
    }


@router.get("/", response_model=List[SharepointScheduleOut])
def list_schedules(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    q = db.query(SharepointSchedule)
    if not is_admin(current_user):
        q = q.filter(SharepointSchedule.owner_id == current_user.id)
    return [_enrich(s, db) for s in q.all()]


@router.get("/{schedule_id}", response_model=SharepointScheduleOut)
def get_schedule(
    schedule_id:  int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    s = db.query(SharepointSchedule).filter(SharepointSchedule.id == schedule_id).first()
    if not s:
        raise HTTPException(404, "Schedule not found")
    if not is_admin(current_user) and s.owner_id != current_user.id:
        raise HTTPException(403, "Not authorized")
    return _enrich(s, db)


@router.post("/", response_model=SharepointScheduleOut)
def create_schedule(
    body:         SharepointScheduleCreate,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    # Validate site exists and user has access
    site = db.query(SharepointSite).filter(SharepointSite.id == body.site_id).first()
    if not site:
        raise HTTPException(404, "SharePoint site not found")
    if not is_admin(current_user) and site.owner_id != current_user.id:
        raise HTTPException(403, "Not authorized to use this SharePoint site")

    run_at_utc = None
    if body.run_at_local:
        run_at_utc = _parse_run_at_utc(body.run_at_local, body.timezone)

    s = SharepointSchedule(
        name                 = body.name,
        site_id              = body.site_id,
        source_path          = body.source_path or None,
        destination_folder   = body.destination_folder or "/",
        destination_filename = body.destination_filename,
        recurrence           = body.recurrence,
        run_at_utc           = run_at_utc,
        timezone             = body.timezone,
        days_of_week         = body.days_of_week or None,
        day_of_month         = body.day_of_month or None,
        is_active            = body.is_active,
        owner_id             = current_user.id,
        created_by           = current_user.sam_account_name or current_user.email,
        created_by_name      = current_user.name,
    )
    db.add(s); db.commit(); db.refresh(s)

    if s.is_active:
        from services.scheduler import add_or_update_sp_schedule
        add_or_update_sp_schedule(s)

    log.info(f"[sharepoint_schedules] Created schedule id={s.id} by {current_user.email}")
    return _enrich(s, db)


@router.put("/{schedule_id}", response_model=SharepointScheduleOut)
def update_schedule(
    schedule_id:  int,
    body:         SharepointScheduleUpdate,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    s = db.query(SharepointSchedule).filter(SharepointSchedule.id == schedule_id).first()
    if not s:
        raise HTTPException(404, "Schedule not found")
    if not is_admin(current_user) and s.owner_id != current_user.id:
        raise HTTPException(403, "Not authorized to edit this schedule")

    if body.run_at_local:
        s.run_at_utc = _parse_run_at_utc(body.run_at_local, body.timezone)

    data = body.model_dump(exclude_unset=True)
    data.pop("run_at_local", None)
    for k, v in data.items():
        setattr(s, k, v)
    db.commit(); db.refresh(s)

    from services.scheduler import add_or_update_sp_schedule, remove_sp_schedule
    if s.is_active:
        add_or_update_sp_schedule(s)
    else:
        remove_sp_schedule(s.id)

    log.info(f"[sharepoint_schedules] Updated schedule id={s.id} by {current_user.email}")
    return _enrich(s, db)


@router.delete("/{schedule_id}")
def delete_schedule(
    schedule_id:  int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    s = db.query(SharepointSchedule).filter(SharepointSchedule.id == schedule_id).first()
    if not s:
        raise HTTPException(404, "Schedule not found")
    if not is_admin(current_user) and s.owner_id != current_user.id:
        raise HTTPException(403, "Not authorized to delete this schedule")

    from services.scheduler import remove_sp_schedule
    remove_sp_schedule(s.id)
    db.delete(s); db.commit()
    log.info(f"[sharepoint_schedules] Deleted schedule id={schedule_id} by {current_user.email}")
    return {"ok": True}


@router.post("/{schedule_id}/run")
def run_now(
    schedule_id:      int,
    background_tasks: BackgroundTasks,
    db:               Session = Depends(get_db),
    current_user:     User    = Depends(get_current_user),
):
    """Trigger an immediate upload run for this schedule."""
    s = db.query(SharepointSchedule).filter(SharepointSchedule.id == schedule_id).first()
    if not s:
        raise HTTPException(404, "Schedule not found")
    if not is_admin(current_user) and s.owner_id != current_user.id:
        raise HTTPException(403, "Not authorized to run this schedule")

    from services.sharepoint_runner import run_sharepoint_schedule
    background_tasks.add_task(run_sharepoint_schedule, s.id, current_user.email)
    return {"ok": True, "message": f"Schedule '{s.name}' queued for upload"}
