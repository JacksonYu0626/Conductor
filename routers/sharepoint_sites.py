"""
routers/sharepoint_sites.py — CRUD for registered SharePoint sites.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import SharepointSite, Schedule, User
from schemas import SharepointSiteCreate, SharepointSiteUpdate, SharepointSiteOut
from deps import get_current_user, is_admin
from typing import List

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/sharepoint/sites", tags=["sharepoint"])


def _enrich(s: SharepointSite, db: Session) -> dict:
    schedule_count = db.query(Schedule).filter(
        Schedule.sharepoint_site_id == s.id,
        Schedule.is_active == True,
    ).count()
    is_internal = (s.site_type or "internal") == "internal"
    return {
        "id":              s.id,
        "name":            s.name,
        "site_url":        s.site_url,
        "site_type":       s.site_type or "internal",
        "tenant_id":       None if is_internal else s.tenant_id,
        "client_id":       None if is_internal else s.client_id,
        # client_secret intentionally excluded
        "drive_id":        s.drive_id,
        "is_active":       s.is_active,
        "owner":           s.owner,
        "created_by_name": s.created_by_name,
        "created_at":      s.created_at,
        "schedule_count":  schedule_count,
    }


@router.get("/", response_model=List[SharepointSiteOut])
def list_sites(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    q = db.query(SharepointSite).filter(SharepointSite.is_active == True)
    if not is_admin(current_user):
        q = q.filter(SharepointSite.owner_id == current_user.id)
    sites = q.order_by(SharepointSite.name.asc()).all()
    if not sites:
        return []

    site_ids = [s.id for s in sites]
    count_rows = (
        db.query(Schedule.sharepoint_site_id, func.count(Schedule.id).label("cnt"))
        .filter(Schedule.sharepoint_site_id.in_(site_ids), Schedule.is_active == True)
        .group_by(Schedule.sharepoint_site_id)
        .all()
    )
    count_map = {r.sharepoint_site_id: r.cnt for r in count_rows}

    results = []
    for s in sites:
        is_internal = (s.site_type or "internal") == "internal"
        results.append({
            "id":              s.id,
            "name":            s.name,
            "site_url":        s.site_url,
            "site_type":       s.site_type or "internal",
            "tenant_id":       None if is_internal else s.tenant_id,
            "client_id":       None if is_internal else s.client_id,
            "drive_id":        s.drive_id,
            "is_active":       s.is_active,
            "owner":           s.owner,
            "created_by_name": s.created_by_name,
            "created_at":      s.created_at,
            "schedule_count":  count_map.get(s.id, 0),
        })
    return results


@router.get("/{site_id}", response_model=SharepointSiteOut)
def get_site(
    site_id:      int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    s = db.query(SharepointSite).filter(SharepointSite.id == site_id).first()
    if not s:
        raise HTTPException(404, "SharePoint site not found")
    if not is_admin(current_user) and s.owner_id != current_user.id:
        raise HTTPException(403, "Not authorized")
    return _enrich(s, db)


@router.post("/", response_model=SharepointSiteOut)
def create_site(
    body:         SharepointSiteCreate,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    import os
    site_type = (body.site_type or "internal").lower()

    if site_type == "internal":
        # Pull credentials from .env — never stored per-site
        tenant_id     = os.getenv("SHAREPOINT_TENANT_ID", "")
        client_id     = os.getenv("SHAREPOINT_CLIENT_ID", "")
        client_secret = os.getenv("SHAREPOINT_CLIENT_SECRET", "")
        if not all([tenant_id, client_id, client_secret]):
            raise HTTPException(400, "Internal SharePoint credentials not configured. "
                                     "Add SHAREPOINT_TENANT_ID, SHAREPOINT_CLIENT_ID, "
                                     "and SHAREPOINT_CLIENT_SECRET to .env")
    else:
        # External — credentials provided by user
        if not all([body.tenant_id, body.client_id, body.client_secret]):
            raise HTTPException(400, "Tenant ID, Client ID and Client Secret are required for external sites.")
        tenant_id     = body.tenant_id
        client_id     = body.client_id
        client_secret = body.client_secret

    s = SharepointSite(
        name            = body.name,
        site_url        = body.site_url.rstrip("/"),
        site_type       = site_type,
        tenant_id       = tenant_id,
        client_id       = client_id,
        client_secret   = client_secret,
        drive_id        = body.drive_id or None,
        owner_id        = current_user.id,
        created_by      = current_user.sam_account_name or current_user.email,
        created_by_name = current_user.name,
    )
    db.add(s); db.commit(); db.refresh(s)
    log.info(f"[sharepoint_sites] Created {site_type} site id={s.id} name={s.name} by {current_user.email}")
    return _enrich(s, db)


@router.put("/{site_id}", response_model=SharepointSiteOut)
def update_site(
    site_id:      int,
    body:         SharepointSiteUpdate,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    s = db.query(SharepointSite).filter(SharepointSite.id == site_id).first()
    if not s:
        raise HTTPException(404, "SharePoint site not found")
    if not is_admin(current_user) and s.owner_id != current_user.id:
        raise HTTPException(403, "Not authorized to edit this site")

    data = body.model_dump(exclude_unset=True)
    # Only update client_secret if a new value was explicitly provided
    if "client_secret" in data and not data["client_secret"]:
        data.pop("client_secret")
    if "site_url" in data and data["site_url"]:
        data["site_url"] = data["site_url"].rstrip("/")
    for k, v in data.items():
        setattr(s, k, v)
    db.commit(); db.refresh(s)
    log.info(f"[sharepoint_sites] Updated site id={s.id} by {current_user.email}")
    return _enrich(s, db)


@router.delete("/{site_id}")
def delete_site(
    site_id:      int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    s = db.query(SharepointSite).filter(SharepointSite.id == site_id).first()
    if not s:
        raise HTTPException(404, "SharePoint site not found")
    if not is_admin(current_user) and s.owner_id != current_user.id:
        raise HTTPException(403, "Not authorized to delete this site")

    # Check for active schedules referencing this site
    active = db.query(Schedule).filter(
        Schedule.sharepoint_site_id == site_id,
        Schedule.is_active == True,
    ).count()
    if active:
        raise HTTPException(400, f"Cannot delete: {active} active schedule(s) still reference this site")

    db.delete(s); db.commit()
    log.info(f"[sharepoint_sites] Deleted site id={site_id} by {current_user.email}")
    return {"ok": True}


@router.post("/{site_id}/test")
def test_site_connection(
    site_id:      int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """Verify credentials by acquiring a Graph API token and resolving the site."""
    s = db.query(SharepointSite).filter(SharepointSite.id == site_id).first()
    if not s:
        raise HTTPException(404, "SharePoint site not found")
    if not is_admin(current_user) and s.owner_id != current_user.id:
        raise HTTPException(403, "Not authorized")

    try:
        from services.sharepoint_service import get_access_token, resolve_site_and_drive
        token          = get_access_token(s)
        site_gid, drv  = resolve_site_and_drive(token, s.site_url)
        return {"ok": True, "graph_site_id": site_gid, "drive_id": drv}
    except Exception as e:
        raise HTTPException(400, f"Connection test failed: {e}")


@router.get("/{site_id}/activity")
def site_activity(
    site_id:      int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """
    Recent uploads and folders used for one site — shown when a row is
    expanded on the SharePoint Sites page. Covers every schedule that posts
    to this site (SharePoint uploads, and Script/Tableau schedules with the
    "Also post to SharePoint" option).
    """
    from datetime import datetime, timezone
    from sqlalchemy import desc
    from models import RunLog

    s = db.query(SharepointSite).filter(SharepointSite.id == site_id).first()
    if not s:
        raise HTTPException(404, "SharePoint site not found")
    if not is_admin(current_user) and s.owner_id != current_user.id:
        raise HTTPException(403, "Not authorized")

    schedules = db.query(Schedule).filter(Schedule.sharepoint_site_id == site_id).all()
    schedule_ids = [x.id for x in schedules]

    folders: List[str] = []
    for sch in schedules:
        dests = []
        for line in (getattr(sch, "output_file_path", None) or "").splitlines():
            line = line.strip()
            if "->" in line:
                dests.append(line.split("->", 1)[1].strip())
        if not dests and sch.sharepoint_folder:
            dests.append(sch.sharepoint_folder.strip())
        for d in dests:
            if d and d not in folders:
                folders.append(d)

    recent = []
    month_uploads = 0
    if schedule_ids:
        rows = (
            db.query(RunLog)
            .filter(RunLog.schedule_id.in_(schedule_ids))
            .order_by(desc(RunLog.started_at))
            .limit(8)
            .all()
        )
        recent = [{
            "id":         r.id,
            "name":       r.schedule_name or "",
            "log_type":   r.log_type or "script",
            "status":     r.status,
            "started_at": r.started_at,
        } for r in rows]
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        month_uploads = (
            db.query(func.count(RunLog.id))
            .filter(RunLog.schedule_id.in_(schedule_ids),
                    RunLog.status == "success",
                    RunLog.started_at >= month_start)
            .scalar() or 0
        )

    return {
        "site_id":         site_id,
        "schedule_count":  len(schedule_ids),
        "uploads_this_month": int(month_uploads),
        "folders":         folders[:10],
        "recent":          recent,
    }
