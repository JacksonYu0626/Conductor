"""
Conductor — unified automation & reporting orchestration platform.
Run:  python main.py  →  http://localhost:8000
"""
# App version (date-based, like WayPOINT: YYYY.MM.DD, then .2, .3 for later releases that day).
# Keep equal to UI_VERSION in static/app/core.jsx and the ?v= in static/index.html,
# and add the release to CHANGELOG.md.
__version__ = "2026.11.06"

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, Depends, HTTPException
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import Dict, Tuple, Any
from dotenv import load_dotenv
import hashlib, os, time
import uvicorn

load_dotenv()

from database import get_db, init_db
from models import User, Script, Schedule, RunLog, Dashboard, SharepointSite
from schemas import UserOut
from deps import get_current_user, is_admin
from routers import auth, scripts, schedules, logs, users, feedback, analytics, dashboards
from routers import sharepoint_sites
from services.scheduler import start_scheduler, stop_scheduler
from services.runner import cleanup_stale_runs


def _migrate_entry_point_column():
    """Add entry_point column to scripts table if missing (safe ALTER TABLE)."""
    from database import engine
    import sqlalchemy as sa
    with engine.connect() as conn:
        try:
            conn.execute(sa.text("ALTER TABLE scripts ADD COLUMN entry_point VARCHAR(300) DEFAULT 'main.py'"))
            conn.commit()
            print("[Migration] Added entry_point column to scripts.")
        except Exception:
            pass  # Column already exists


def _migrate_scripts_to_user_folders():
    """
    One-time migration: move scripts from root Scripts/ into per-user subfolders.
    Only touches scripts whose filename doesn't already contain a '/'.
    Scripts without an owner are assigned to the admin user.
    """
    import re, shutil
    from database import SessionLocal
    from models import Script, User as UserModel

    db = SessionLocal()
    try:
        unmigrated = db.query(Script).filter(~Script.filename.contains("/")).all()
        if not unmigrated:
            return

        scripts_dir = os.path.join(os.path.dirname(__file__), "scripts")
        admin = db.query(UserModel).filter(UserModel.role == "admin").first()

        moved = 0
        for script in unmigrated:
            owner = None
            if script.owner_id:
                owner = db.query(UserModel).filter(UserModel.id == script.owner_id).first()
            if not owner:
                owner = admin
                if admin:
                    script.owner_id = admin.id

            if not owner:
                continue

            # Build slug: Name_emailprefix
            email_prefix = owner.email.split("@")[0]
            name_slug = re.sub(r"[^\w\s]", "", owner.name).strip()
            name_slug = re.sub(r"\s+", "_", name_slug)
            user_folder = f"{name_slug}_{email_prefix}"

            user_dir = os.path.join(scripts_dir, user_folder)
            os.makedirs(user_dir, exist_ok=True)

            old_path = os.path.join(scripts_dir, script.filename)
            new_path = os.path.join(user_dir, script.filename)

            if os.path.exists(old_path) and not os.path.exists(new_path):
                shutil.move(old_path, new_path)

            script.filename    = f"{user_folder}/{script.filename}"
            script.entry_point = getattr(script, "entry_point", None) or "main.py"
            moved += 1

        if moved:
            db.commit()
            print(f"[Migration] Moved {moved} script(s) into user subfolders.")
    finally:
        db.close()


# Safety switch for local testing. Set SCHEDULER_ENABLED=false in a local .env
# so a test copy never fires schedules or marks production runs as failed,
# even if it is accidentally pointed at the production database.
# Production does not set it, so the default (true) keeps today's behavior.
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").strip().lower() not in ("false", "0", "no", "off")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _migrate_entry_point_column()
    _migrate_scripts_to_user_folders()
    if SCHEDULER_ENABLED:
        cleanup_stale_runs()
        start_scheduler()
    else:
        print("⏸  SCHEDULER_ENABLED=false — schedules will not fire and running jobs are left untouched.")
    os.makedirs(os.path.join(os.path.dirname(__file__), "scripts"), exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), "tmp"), exist_ok=True)
    print("✅ Conductor started → http://localhost:8000")
    print("📖 API docs          → http://localhost:8000/api/docs")
    yield
    if SCHEDULER_ENABLED:
        stop_scheduler()
        cleanup_stale_runs()


app = FastAPI(
    title="Conductor API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── GZip: compress all responses ≥ 1 KB ──────────────────────────────────────
# This alone reduces the 208 KB index.html to ~50 KB in transit.
app.add_middleware(GZipMiddleware, minimum_size=1000)

from starlette.middleware.base import BaseHTTPMiddleware

class NoCacheAPIMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        # /auth/gs_config never changes at runtime — allow browser to cache 10 min
        if request.url.path == "/auth/gs_config":
            response.headers["Cache-Control"] = "public, max-age=600"
            return response
        if request.url.path.startswith((
            "/auth", "/scripts", "/dashboards", "/schedules", "/logs",
            "/users", "/feedback", "/analytics", "/summary", "/api",
            "/sharepoint",
        )):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response

app.add_middleware(NoCacheAPIMiddleware)


@app.get("/auth/me", response_model=UserOut, tags=["auth"])
def me(user: User = Depends(get_current_user)):
    return user


# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(scripts.router)
app.include_router(dashboards.router)
app.include_router(schedules.router)
app.include_router(logs.router)
app.include_router(users.router)
app.include_router(feedback.router)
app.include_router(analytics.router)
app.include_router(sharepoint_sites.router)


# ── Small in-memory caches for dashboard-style endpoints ─────────────────────
# These mimic the practical approach used by large apps: page requests read a
# very fresh cached result instead of recalculating the same DB aggregates on
# every click. TTL is intentionally short so the UI still feels current.
_SUMMARY_CACHE: Dict[Tuple[Any, ...], Tuple[float, dict]] = {}
_SUMMARY_CACHE_TTL_SECONDS = int(os.getenv("CONDUCTOR_SUMMARY_CACHE_SECONDS", "300"))

def _cache_get(cache: dict, key: tuple, ttl_seconds: int):
    item = cache.get(key)
    if not item:
        return None
    ts, value = item
    if time.time() - ts <= ttl_seconds:
        return value
    cache.pop(key, None)
    return None

def _cache_set(cache: dict, key: tuple, value: dict):
    cache[key] = (time.time(), value)
    return value


# Clear the Summary / chart caches whenever a run is created or its status
# changes (started, finished, stopped), so new results show up right away
# instead of after the cache expires. Runs are written in this same process
# (API + scheduler threads), so an in-memory flag is enough.
from sqlalchemy import event as _sa_event, inspect as _sa_inspect

def _clear_run_caches(*_args):
    _SUMMARY_CACHE.clear()
    analytics._ANALYTICS_CACHE.clear()

def _on_runlog_update(_mapper, _conn, target):
    # Partial-output saves only touch "output"; ignore those so a long run
    # doesn't wipe the cache every few seconds.
    if _sa_inspect(target).attrs.status.history.has_changes():
        _clear_run_caches()

_sa_event.listen(RunLog, "after_insert", _clear_run_caches)
_sa_event.listen(RunLog, "after_update", _on_runlog_update)

# ── Summary stats endpoint ─────────────────────────────────────────────────────
@app.get("/summary/stats", tags=["summary"])
def summary_stats(
    job_type: str = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import or_, case, func

    admin = is_admin(current_user)
    normalized_job_type = (job_type or "all").lower()
    cache_key = (
        "summary_stats",
        "admin" if admin else "user",
        current_user.id if not admin else 0,
        normalized_job_type,
    )
    cached = _cache_get(_SUMMARY_CACHE, cache_key, _SUMMARY_CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    # ── Owned IDs for non-admins. Keep this once per cache refresh, not every click. ──
    owned_script_ids = []
    owned_schedule_ids = []
    if not admin:
        owned_script_ids = [
            s.id for s in db.query(Script.id).filter(Script.owner_id == current_user.id).all()
        ]
        owned_schedule_ids = [
            s.id for s in db.query(Schedule.id).filter(Schedule.owner_id == current_user.id).all()
        ]

    # ── Small table counts ───────────────────────────────────────────────────
    q_scripts = db.query(func.count(Script.id)).filter(Script.is_active == True)
    if not admin:
        q_scripts = q_scripts.filter(Script.owner_id == current_user.id)
    total_scripts = int(q_scripts.scalar() or 0)

    q_dash = db.query(func.count(Dashboard.id)).filter(Dashboard.is_active == True)
    if not admin:
        q_dash = q_dash.filter(Dashboard.owner_id == current_user.id)
    total_dashboards = int(q_dash.scalar() or 0)

    q_sched = db.query(func.count(Schedule.id)).filter(Schedule.is_active == True)
    if not admin:
        q_sched = q_sched.filter(Schedule.owner_id == current_user.id)
    if normalized_job_type != "all":
        q_sched = q_sched.filter(Schedule.schedule_type == normalized_job_type)
    active_schedules = int(q_sched.scalar() or 0)

    def _base_log_q():
        q = db.query(RunLog)
        if not admin:
            q = q.filter(
                or_(
                    RunLog.script_id.in_(owned_script_ids or [-1]),
                    RunLog.schedule_id.in_(owned_schedule_ids or [-1]),
                    RunLog.owner_id == current_user.id,
                )
            )
        if normalized_job_type != "all":
            q = q.filter(RunLog.log_type == normalized_job_type)
        return q

    # ── RunLog counts: one aggregate query instead of multiple counts. ───────
    status_counts = _base_log_q().with_entities(
        func.sum(case((RunLog.status == "success", 1), else_=0)).label("success_cnt"),
        func.sum(case((RunLog.status == "failed",  1), else_=0)).label("failed_cnt"),
        func.sum(case((RunLog.status == "running", 1), else_=0)).label("running_cnt"),
    ).one()

    success_runs = int(status_counts.success_cnt or 0)
    failed_runs  = int(status_counts.failed_cnt  or 0)
    running_now  = int(status_counts.running_cnt or 0)

    # ── Recent logs: select only fields needed by Summary. Do NOT load output/error. ──
    recent_rows = (
        _base_log_q()
        .with_entities(
            RunLog.id, RunLog.log_type, RunLog.script_id, RunLog.schedule_id,
            RunLog.schedule_name, RunLog.trigger, RunLog.triggered_by,
            RunLog.triggered_by_name, RunLog.status, RunLog.duration_ms,
            RunLog.started_at, RunLog.finished_at,
        )
        .filter(RunLog.status.in_(["success", "failed", "stopped"]))
        .order_by(RunLog.started_at.desc())
        .limit(10)
        .all()
    )

    script_ids = {r.script_id for r in recent_rows if r.script_id}
    schedule_ids = {r.schedule_id for r in recent_rows if r.schedule_id}
    scripts_map = {s.id: s for s in db.query(Script).filter(Script.id.in_(script_ids)).all()} if script_ids else {}
    schedules_map = {s.id: s for s in db.query(Schedule).filter(Schedule.id.in_(schedule_ids)).all()} if schedule_ids else {}

    emails = {(r.triggered_by or "").strip().lower() for r in recent_rows if r.triggered_by}
    system_triggers = {"system", "scheduler", "manual", "", None}
    emails = {e for e in emails if e not in system_triggers}
    name_map = {}
    if emails:
        users_for_names = db.query(User).filter(User.email.in_(list(emails))).all()
        name_map = {u.email.lower(): u.name for u in users_for_names if u.email}

    recent_logs = []
    for r in recent_rows:
        sc = scripts_map.get(r.script_id)
        sched = schedules_map.get(r.schedule_id)
        tb = (r.triggered_by or "").strip()
        is_system_trigger = tb.lower() in system_triggers
        recent_logs.append({
            "id": r.id,
            "log_type": r.log_type or "script",
            "script_id": r.script_id,
            "script_name": sc.name if sc else "",
            "schedule_id": r.schedule_id,
            "schedule_name": r.schedule_name or (sched.name if sched else ""),
            "trigger": r.trigger,
            "triggered_by": "Scheduler" if is_system_trigger else "Manual",
            "triggered_by_name": (r.triggered_by_name or "") if is_system_trigger else (r.triggered_by_name or name_map.get(tb.lower(), tb)),
            "status": r.status,
            "output": "",
            "error": "",
            "duration_ms": r.duration_ms or 0,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "email_to": "",
            "cc_to": "",
            "recipients": [],
            "notify_email_to": "",
            "notify_cc_to": "",
            "sp_site_name": "",
            "sp_folder": "",
        })

    result = {
        "job_type":         normalized_job_type,
        "cached_for_seconds": _SUMMARY_CACHE_TTL_SECONDS,
        "total_scripts":    total_scripts,
        "total_dashboards": total_dashboards,
        "active_schedules": active_schedules,
        "success_runs":     success_runs,
        "failed_runs":      failed_runs,
        "running_now":      running_now,
        "recent_logs":      recent_logs,
    }
    return _cache_set(_SUMMARY_CACHE, cache_key, result)


# ── Serve frontend ─────────────────────────────────────────────────────────────
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_INDEX_PATH = os.path.join(STATIC_DIR, "index.html")

# Serve frontend assets (JS/CSS/images) directly.
# Without this mount, /static/app.bundle.js is handled by the SPA catch-all
# and returns index.html instead of JavaScript, causing a blank page.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Version + What's new ──────────────────────────────────────────────────────
# No sign-in needed: the page asks every few minutes whether a newer version is
# running, and "What's new" shows CHANGELOG.md.
from datetime import datetime as _dt
_STARTED_AT = _dt.now().strftime("%Y-%m-%dT%H:%M:%S")
_CHANGELOG_PATH = os.path.join(os.path.dirname(__file__), "CHANGELOG.md")


@app.get("/api/version", tags=["app"])
def app_version():
    return {"version": __version__, "started_at": _STARTED_AT}


@app.get("/api/changelog", tags=["app"])
def app_changelog():
    try:
        with open(_CHANGELOG_PATH, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""
    return {"version": __version__, "text": text}

def _etag_for_file(path: str) -> str:
    """Generate a stable ETag from the file's mtime + size (no hashing needed)."""
    stat = os.stat(path)
    return f'"{int(stat.st_mtime)}-{stat.st_size}"'


@app.get("/{full_path:path}", include_in_schema=False)
def serve_ui(full_path: str, request=None):
    API_PREFIXES = ("auth", "scripts", "dashboards", "schedules", "logs",
                    "users", "feedback", "analytics", "summary", "api", "sharepoint")
    if full_path.startswith(API_PREFIXES):
        raise HTTPException(status_code=404, detail="Not found")

    etag = _etag_for_file(_INDEX_PATH)
    # Always re-check index.html with the server (cheap: ETag -> 304 when
    # unchanged) so a new release shows up on the next page load instead of
    # after a 5-minute browser cache. The app files it loads carry ?v=… so
    # they refresh too.
    return FileResponse(
        _INDEX_PATH,
        headers={
            "ETag": etag,
            "Cache-Control": "no-cache",
        },
    )


if __name__ == "__main__":
    import threading
    import time
    import urllib.request
    import webbrowser

    APP_URL = "http://localhost:8000"
    HEALTH_URL = f"{APP_URL}/health"

    def wait_for_server(url, timeout=60):
        start = time.time()
        while time.time() - start < timeout:
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    if response.status < 500:
                        return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def open_browser_when_ready():
        if wait_for_server(HEALTH_URL, timeout=60):
            webbrowser.open(APP_URL)
        else:
            print("⚠️ Server did not become ready within 60 seconds. Please open http://localhost:8000 manually after startup finishes.")

    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)