from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from models import User, Schedule
from schemas import UserCreate, UserUpdate, UserOut, UserListOut
from deps import get_current_user, is_admin
from passlib.context import CryptContext
from typing import List, Optional
import os

router = APIRouter(prefix="/users", tags=["users"])
pwd_ctx = CryptContext(schemes=["bcrypt"])


@router.get("/", response_model=List[UserListOut])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Every active user, with how many scripts, dashboards, SharePoint sites and
    schedules each one owns. Everyone can see this list (names and counts only);
    the items themselves stay private — the other routers still only return a
    user's own items unless they are an admin.
    """
    from sqlalchemy import func
    from models import Script, Dashboard, SharepointSite

    users = db.query(User).filter(User.is_active == True).order_by(User.name.asc()).all()

    def _counts(model, *filters):
        q = db.query(model.owner_id, func.count(model.id)).filter(model.owner_id.isnot(None))
        for f in filters:
            q = q.filter(f)
        return {owner_id: int(cnt) for owner_id, cnt in q.group_by(model.owner_id).all()}

    scripts    = _counts(Script, Script.is_active == True)
    dashboards = _counts(Dashboard, Dashboard.is_active == True)
    sites      = _counts(SharepointSite, SharepointSite.is_active == True)
    from models import Feedback
    feedback = {uid: int(cnt) for uid, cnt in db.query(Feedback.user_id, func.count(Feedback.id))
                .filter(Feedback.user_id.isnot(None)).group_by(Feedback.user_id).all()}
    # Ad-hoc schedules (created by "Send now") are hidden from the Schedules page too
    schedules: dict = {}
    for owner_id, name in db.query(Schedule.owner_id, Schedule.name).filter(Schedule.owner_id.isnot(None)).all():
        if not (name or "").startswith("[Ad-hoc]"):
            schedules[owner_id] = schedules.get(owner_id, 0) + 1

    out = []
    for u in users:
        item = UserListOut.model_validate(u).model_dump()
        item.update(
            script_count=scripts.get(u.id, 0),
            dashboard_count=dashboards.get(u.id, 0),
            sharepoint_site_count=sites.get(u.id, 0),
            schedule_count=schedules.get(u.id, 0),
            feedback_count=feedback.get(u.id, 0),
        )
        out.append(item)
    return out


@router.get("/search", response_model=List[dict])
def search_users(
    q: str = Query(..., min_length=2),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search users for recipient pickers — available to all authenticated users."""
    local = db.query(User).filter(
        (User.name.ilike(f"%{q}%")) |
        (User.email.ilike(f"%{q}%")) |
        (User.department.ilike(f"%{q}%"))
    ).all()

    results = [
        {"fullname": u.name, "email": u.email, "title": u.title,
         "department": u.department, "source": "local"}
        for u in local
    ]

    mssql_results = _try_mssql_search(q)
    existing_emails = {r["email"].lower() for r in results}
    for r in mssql_results:
        if r["email"].lower() not in existing_emails:
            results.append(r)

    return results


def _try_mssql_search(query: str) -> list:
    try:
        import pyodbc
    except ImportError:
        return []

    SERVER   = os.getenv("MSSQL_SERVER", "MPMEDW1")
    DATABASE = os.getenv("MSSQL_DATABASE", "mpm_edw")
    DRIVER   = os.getenv("MSSQL_DRIVER", "{ODBC Driver 17 for SQL Server}")
    CONN_STR = (
        f"DRIVER={DRIVER};SERVER={SERVER};DATABASE={DATABASE};"
        f"Trusted_Connection=Yes;Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=5;"
    )
    try:
        sql = """
            SELECT *
            FROM (
                SELECT 
                    [GivenName],
                    [Surname],
                    [DisplayName] AS FULLNAME,
                    LTRIM(RTRIM([Title])) AS TITLE,
                    LTRIM(RTRIM([Department])) AS DEPARTMENT,
                    LOWER(LTRIM(RTRIM([Email]))) AS EMAIL_L,
                    [Disabled] AS DISABLED_DTM
                    --ROW_NUMBER() OVER (
                    --    PARTITION BY 
                    --        LOWER(LTRIM(RTRIM([GivenName]))),
                    --        LOWER(LTRIM(RTRIM([Surname])))
                    --    ORDER BY 
                    --        CASE WHEN [Disabled] IS NULL THEN 0 ELSE 1 END,
                    --        [Disabled] DESC
                    --) AS RN
                FROM [mpm_edw].[LAND].[USERS_SECURITY_TBL]
                WHERE [Title] IS NOT NULL 
                AND ([Title] <> '' OR [Title] IS NOT NULL)
                AND [GivenName] IS NOT NULL
                AND [Email] IS NOT NULL
                --AND DEPARTMENT NOT LIKE '%NO LONGER%'
                --AND SERVERID = '1'
            ) X
            WHERE 1 = 1
                --AND X.RN = 1
                AND (
                LOWER(LTRIM(RTRIM([GivenName]))) LIKE ?
                OR LOWER(LTRIM(RTRIM([Surname]))) LIKE ?
                OR LOWER(LTRIM(RTRIM(EMAIL_l))) LIKE ?
                OR LOWER(LTRIM(RTRIM(DEPARTMENT))) LIKE ?
                )
        """
        like = f"%{query.lower()}%"
        results = []
        with pyodbc.connect(CONN_STR) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, [like, like, like, like])
                for row in cur.fetchall():
                    results.append({
                        "fullname": row.FULLNAME or "",
                        "email": row.EMAIL_L or "",
                        "title": row.TITLE or "",
                        "department": row.DEPARTMENT or "",
                        "source": "mssql",
                    })
        return results
    except Exception as e:
        print(f"[MSSQL search] FAILED: {type(e).__name__}: {e}")
        return []


@router.post("/", response_model=UserOut)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admin only."""
    if not is_admin(current_user):
        raise HTTPException(403, "Admin access required to create users")
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(400, "Email already registered")
    u = User(
        name=body.name, email=body.email,
        hashed_password=pwd_ctx.hash(body.password),
        role=body.role, department=body.department, title=body.title,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admin only."""
    if not is_admin(current_user):
        raise HTTPException(403, "Admin access required to edit users")
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "User not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(u, k, v)

    # If deactivating: pause all their active schedules
    if body.is_active is False:
        from services.scheduler import remove_schedule
        schedules = db.query(Schedule).filter(
            Schedule.owner_id == user_id,
            Schedule.is_active == True
        ).all()
        for s in schedules:
            s.is_active = False
            remove_schedule(s.id, s.schedule_type)

    db.commit(); db.refresh(u)
    return u


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admin only. Deactivates user and pauses their schedules."""
    if not is_admin(current_user):
        raise HTTPException(403, "Admin access required to deactivate users")
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404)
    u.is_active = False

    # Pause all their active schedules
    from services.scheduler import remove_schedule
    schedules = db.query(Schedule).filter(
        Schedule.owner_id == user_id,
        Schedule.is_active == True
    ).all()
    for s in schedules:
        s.is_active = False
        remove_schedule(s.id, s.schedule_type)

    db.commit()
    return {"ok": True}