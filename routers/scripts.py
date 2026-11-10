import io
import os
import re
import shutil
import zipfile
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from database import get_db
from models import RunLog, Script, User
from schemas import ScriptCreate, ScriptOut, ScriptUpdate
from deps import get_current_user, is_admin

router = APIRouter(prefix="/scripts", tags=["scripts"])

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")


# ── Folder slug helpers ───────────────────────────────────────────────────────

def _user_folder_slug(user: User) -> str:
    """Build a filesystem-safe folder name: FirstName_LastName_emailprefix."""
    email_prefix = user.email.split("@")[0]
    name_slug = re.sub(r"[^\w\s]", "", user.name).strip()
    name_slug = re.sub(r"\s+", "_", name_slug)
    return f"{name_slug}_{email_prefix}"


def _script_folder_slug(script_name: str) -> str:
    """Sanitize a script name into a safe folder name."""
    # Remove characters illegal on Windows/Linux filesystems
    slug = re.sub(r'[<>:"/\\|?*]', "_", script_name).strip().strip(".")
    # Collapse runs of spaces/underscores
    slug = re.sub(r"[\s_]+", "_", slug)
    return slug or "script"


# ── Timeout validation ────────────────────────────────────────────────────────

def _validate_timeout(timeout_sec: Optional[int]) -> Optional[int]:
    """None/0 = use the default. Otherwise must be within MIN..MAX."""
    from services.runner import MIN_TIMEOUT_SEC, MAX_TIMEOUT_SEC
    if not timeout_sec:
        return None
    if timeout_sec < MIN_TIMEOUT_SEC or timeout_sec > MAX_TIMEOUT_SEC:
        raise HTTPException(
            400,
            f"Timeout must be between {MIN_TIMEOUT_SEC // 60} minutes and "
            f"{MAX_TIMEOUT_SEC // 3600} hours.",
        )
    return int(timeout_sec)


# ── Local-path scan (production readiness check) ─────────────────────────────
# The production server has no personal mapped drives (F:, N:, M:, ...), so
# any hard-coded drive-letter path will fail there. This scan doesn't block
# registration — it just returns warnings so the user can fix them.

_DRIVE_PATH_RE = re.compile(
    r"""(?<![A-Za-z0-9])(?:[D-Zd-z]:[\\/]|[Cc]:[\\/]+Users[\\/])"""
)
_SCAN_EXTS      = {".py", ".env", ".ini", ".cfg", ".json", ".yaml", ".yml", ".toml", ".txt"}
_SKIP_DIRS      = {".venv", "venv", "env", "__pycache__", "site-packages", ".git", "__MACOSX"}
_MAX_SCAN_BYTES = 1_000_000
_MAX_WARNINGS   = 25


def _scan_for_local_paths(target_dir: str) -> List[str]:
    warnings: List[str] = []
    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in _SCAN_EXTS and fn.lower() != ".env":
                continue
            full = os.path.join(root, fn)
            try:
                if os.path.getsize(full) > _MAX_SCAN_BYTES:
                    continue
                with open(full, encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except OSError:
                continue
            rel = os.path.relpath(full, target_dir).replace("\\", "/")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue  # skip blank lines and comments
                if _DRIVE_PATH_RE.search(stripped):
                    snippet = stripped if len(stripped) <= 120 else stripped[:117] + "..."
                    warnings.append(f"{rel} line {i}: {snippet}")
                    if len(warnings) >= _MAX_WARNINGS:
                        warnings.append("(more matches not shown)")
                        return warnings
    return warnings


# ── Enrich helper ─────────────────────────────────────────────────────────────

def _enrich(script: Script, db: Session) -> dict:
    last_log = (
        db.query(RunLog)
        .filter(RunLog.script_id == script.id)
        .order_by(desc(RunLog.started_at))
        .first()
    )
    from models import Schedule
    schedule_count = db.query(Schedule).filter(
        Schedule.script_id == script.id,
        Schedule.is_active == True,
    ).count()
    return {
        "id":             script.id,
        "name":           script.name,
        "description":    script.description,
        "category":       script.category,
        "filename":       script.filename,
        "entry_point":    getattr(script, "entry_point", "main.py") or "main.py",
        "is_active":      script.is_active,
        "script_type":    getattr(script, "script_type", "script"),
        "timeout_sec":    getattr(script, "timeout_sec", None),
        "owner":          script.owner,
        "created_at":     script.created_at,
        "last_run":       last_log.started_at if last_log else None,
        "last_status":    last_log.status if last_log else None,
        "schedule_count": schedule_count,
    }


# ── List / get ────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[ScriptOut])
def list_scripts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import func
    from models import Schedule

    q = db.query(Script).filter(Script.is_active == True)
    if not is_admin(current_user):
        q = q.filter(Script.owner_id == current_user.id)
    scripts = q.all()
    if not scripts:
        return []

    script_ids = [s.id for s in scripts]

    # Bulk: last run per script
    from sqlalchemy import desc as _desc
    subq = (
        db.query(RunLog.script_id, func.max(RunLog.started_at).label("max_started"))
        .filter(RunLog.script_id.in_(script_ids))
        .group_by(RunLog.script_id)
        .subquery()
    )
    last_logs = (
        db.query(RunLog)
        .join(subq, (RunLog.script_id == subq.c.script_id) & (RunLog.started_at == subq.c.max_started))
        .all()
    )
    last_log_map = {l.script_id: l for l in last_logs}

    # Bulk: active schedule count per script
    counts = (
        db.query(Schedule.script_id, func.count(Schedule.id).label("cnt"))
        .filter(Schedule.script_id.in_(script_ids), Schedule.is_active == True)
        .group_by(Schedule.script_id)
        .all()
    )
    count_map = {r.script_id: r.cnt for r in counts}

    results = []
    for script in scripts:
        last_log = last_log_map.get(script.id)
        results.append({
            "id":             script.id,
            "name":           script.name,
            "description":    script.description,
            "category":       script.category,
            "filename":       script.filename,
            "entry_point":    getattr(script, "entry_point", "main.py") or "main.py",
            "is_active":      script.is_active,
            "script_type":    getattr(script, "script_type", "script"),
            "timeout_sec":    getattr(script, "timeout_sec", None),
            "owner":          script.owner,
            "created_at":     script.created_at,
            "last_run":       last_log.started_at if last_log else None,
            "last_status":    last_log.status     if last_log else None,
            "schedule_count": count_map.get(script.id, 0),
        })
    return results


@router.get("/{script_id}", response_model=ScriptOut)
def get_script(
    script_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = db.query(Script).filter(Script.id == script_id).first()
    if not s:
        raise HTTPException(404, "Script not found")
    if not is_admin(current_user) and s.owner_id != current_user.id:
        raise HTTPException(403, "Not authorized")
    return _enrich(s, db)


# ── Upload: conflict check ────────────────────────────────────────────────────

@router.get("/upload/check")
def check_upload_conflict(
    script_name: str = Query(...),
    current_user: User = Depends(get_current_user),
):
    """
    Check whether a folder already exists for this user + script name.
    Returns { exists, user_folder, script_folder, path }.
    """
    user_folder   = _user_folder_slug(current_user)
    script_folder = _script_folder_slug(script_name)
    target        = os.path.join(SCRIPTS_DIR, user_folder, script_folder)
    return {
        "exists":        os.path.exists(target) and os.path.isdir(target),
        "user_folder":   user_folder,
        "script_folder": script_folder,
        "path":          f"{user_folder}/{script_folder}",
    }


# ── Upload + register (single multipart call) ─────────────────────────────────

@router.post("/register", response_model=ScriptOut)
async def register_script(
    name:        str  = Form(...),
    description: str  = Form(""),
    category:    str  = Form("General"),
    script_type: str  = Form("script"),
    entry_point: str  = Form("main.py"),
    overwrite:   bool = Form(False),
    timeout_sec: Optional[int] = Form(None),
    file: UploadFile  = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a .py or .zip file and register (or re-register) the script.
    Folder layout: scripts/{user_folder}/{script_folder}/
    """
    timeout_sec   = _validate_timeout(timeout_sec)
    user_folder   = _user_folder_slug(current_user)
    script_folder = _script_folder_slug(name)
    target_dir    = os.path.join(SCRIPTS_DIR, user_folder, script_folder)
    rel_filename  = f"{user_folder}/{script_folder}"

    # Conflict guard
    if os.path.exists(target_dir) and not overwrite:
        raise HTTPException(409, "Folder already exists. Set overwrite=true to replace.")

    # Clean existing folder before deploying new files so stale files don't linger
    if os.path.exists(target_dir) and overwrite:
        shutil.rmtree(target_dir)

    os.makedirs(target_dir, exist_ok=True)

    # Save / extract uploaded file
    content = await file.read()
    fname   = (file.filename or "").lower()

    if fname.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                # Security: strip any absolute or parent-traversal paths
                for member in zf.infolist():
                    member_path = os.path.realpath(os.path.join(target_dir, member.filename))
                    if not member_path.startswith(os.path.realpath(target_dir)):
                        raise HTTPException(400, f"Unsafe path in zip: {member.filename}")
                zf.extractall(target_dir)

            # Auto-flatten: if zip extracted into a single subfolder (common when
            # zipping a folder directly), move contents up one level.
            entries = [e for e in os.listdir(target_dir) if not e.startswith("__MACOSX")]
            if len(entries) == 1:
                sole = os.path.join(target_dir, entries[0])
                if os.path.isdir(sole):
                    for item in os.listdir(sole):
                        shutil.move(os.path.join(sole, item), os.path.join(target_dir, item))
                    shutil.rmtree(sole)

        except zipfile.BadZipFile:
            raise HTTPException(400, "Uploaded file is not a valid zip archive.")
    elif fname.endswith(".py"):
        out_path = os.path.join(target_dir, file.filename)
        with open(out_path, "wb") as f_out:
            f_out.write(content)
    else:
        raise HTTPException(400, "Only .py and .zip files are supported.")

    # Validate entry point exists after extraction
    entry_path = os.path.join(target_dir, entry_point)
    if not os.path.exists(entry_path):
        raise HTTPException(
            400,
            f"Entry point '{entry_point}' not found in the uploaded files. "
            f"Check that the filename matches exactly (case-sensitive)."
        )

    # Look for hard-coded local drive paths that won't exist on the server
    path_warnings = _scan_for_local_paths(target_dir)

    # Upsert DB record
    existing = db.query(Script).filter(Script.filename == rel_filename).first()
    if existing:
        existing.name        = name
        existing.description = description
        existing.category    = category
        existing.script_type = script_type
        existing.entry_point = entry_point
        existing.timeout_sec = timeout_sec
        existing.is_active   = True
        existing.updated_at  = func.now()
        db.commit()
        db.refresh(existing)
        return {**_enrich(existing, db), "path_warnings": path_warnings}

    s = Script(
        name        = name,
        description = description,
        category    = category,
        filename    = rel_filename,
        entry_point = entry_point,
        script_type = script_type,
        timeout_sec = timeout_sec,
        owner_id    = current_user.id,
        is_active   = True,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return {**_enrich(s, db), "path_warnings": path_warnings}


# ── Standard CRUD (metadata only) ─────────────────────────────────────────────

@router.post("/", response_model=ScriptOut)
def create_script(
    body: ScriptCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Legacy / admin endpoint — registers a script by folder path directly."""
    if db.query(Script).filter(Script.filename == body.filename).first():
        raise HTTPException(400, "A script with that filename already exists")
    data = body.model_dump()
    data["timeout_sec"] = _validate_timeout(data.get("timeout_sec"))
    data["owner_id"] = current_user.id
    s = Script(**data)
    db.add(s)
    db.commit()
    db.refresh(s)
    return _enrich(s, db)


@router.put("/{script_id}", response_model=ScriptOut)
def update_script(
    script_id: int,
    body: ScriptUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = db.query(Script).filter(Script.id == script_id).first()
    if not s:
        raise HTTPException(404, "Script not found")
    if not is_admin(current_user) and s.owner_id != current_user.id:
        raise HTTPException(403, "Not authorized to edit this script")
    updates = body.model_dump(exclude_unset=True)
    if "timeout_sec" in updates:
        updates["timeout_sec"] = _validate_timeout(updates["timeout_sec"])
    for k, v in updates.items():
        setattr(s, k, v)
    s.updated_at = func.now()
    db.commit()
    db.refresh(s)
    return _enrich(s, db)


@router.delete("/{script_id}")
def delete_script(
    script_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = db.query(Script).filter(Script.id == script_id).first()
    if not s:
        raise HTTPException(404, "Script not found")
    if not is_admin(current_user) and s.owner_id != current_user.id:
        raise HTTPException(403, "Not authorized to delete this script")

    # 1. Remove APScheduler jobs + delete all linked schedules from DB
    from models import Schedule
    from services.scheduler import remove_schedule
    linked_schedules = db.query(Schedule).filter(Schedule.script_id == script_id).all()
    for sched in linked_schedules:
        remove_schedule(sched.id, sched.schedule_type or "script")
        db.delete(sched)

    # 2. Null out script_id on RunLogs so history is preserved but won't
    #    accidentally link to a future script that reuses the same DB row.
    #    Commit immediately so the DB-level ondelete="CASCADE" has no RunLogs
    #    left to delete when we remove the script row below.
    db.query(RunLog).filter(RunLog.script_id == script_id).update(
        {"script_id": None}, synchronize_session=False
    )
    db.commit()

    # 3. Delete the script folder from disk
    script_dir = os.path.join(SCRIPTS_DIR, *s.filename.split("/"))
    if os.path.exists(script_dir) and os.path.isdir(script_dir):
        shutil.rmtree(script_dir, ignore_errors=True)

    # 4. Delete the script record itself
    db.delete(s)
    db.commit()
    return {"ok": True}


# ── Run / stop / logs ─────────────────────────────────────────────────────────

@router.post("/{script_id}/run")
def run_script(
    script_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    triggered_by: str = "manual",
):
    s = db.query(Script).filter(Script.id == script_id).first()
    if not s:
        raise HTTPException(404, "Script not found")
    # Owner, admin, or someone a schedule of this script is shared with ("Can edit")
    from services.sharing import can_use_script
    if not can_use_script(db, current_user, s, "edit"):
        raise HTTPException(403, "Not authorized to run this script")
    from services.runner import run_script as _run
    background_tasks.add_task(_run, script_id, "manual", current_user.email)
    return {"ok": True, "message": f"Script '{s.name}' started"}


@router.post("/{script_id}/stop")
def stop_script(
    script_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from services.runner import stop_script as _stop
    from services.sharing import can_use_script
    if not can_use_script(db, current_user, db.query(Script).filter(Script.id == script_id).first(), "edit"):
        raise HTTPException(404, "Script not found")
    log = (
        db.query(RunLog)
        .filter(RunLog.script_id == script_id, RunLog.status == "running")
        .order_by(desc(RunLog.started_at))
        .first()
    )
    if not log:
        raise HTTPException(404, "No running instance found for this script")
    killed = _stop(log.id)
    if not killed:
        raise HTTPException(409, "Process not found in memory — it may have already finished")
    return {"ok": True, "message": "Script stop signal sent", "log_id": log.id}


@router.post("/{script_id}/pause_schedules")
def pause_script_schedules(
    script_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admin action: pause every active schedule that runs this script."""
    if not is_admin(current_user):
        raise HTTPException(403, "Admin access required")
    from models import Schedule
    from services.scheduler import remove_schedule
    schedules = db.query(Schedule).filter(
        Schedule.script_id == script_id,
        Schedule.is_active == True,
    ).all()
    for sched in schedules:
        sched.is_active = False
        remove_schedule(sched.id, sched.schedule_type or "script")
    db.commit()
    return {"ok": True, "paused": len(schedules)}


@router.get("/{script_id}/logs/latest")
def get_latest_log(
    script_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = db.query(Script).filter(Script.id == script_id).first()
    from services.sharing import can_use_script
    if not s or not can_use_script(db, current_user, s, "view"):
        raise HTTPException(404, "Script not found")
    log = (
        db.query(RunLog)
        .filter(RunLog.script_id == script_id)
        .order_by(desc(RunLog.started_at))
        .first()
    )
    if not log:
        return None
    return {
        "id": log.id, "status": log.status, "output": log.output,
        "error": log.error, "duration_ms": log.duration_ms,
        "started_at": log.started_at, "finished_at": log.finished_at,
    }