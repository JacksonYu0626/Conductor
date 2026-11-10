"""
services/sharing.py — who may do what with a schedule.

Roles, strongest first:
  owner  — created it. Everything, including delete and sharing.
  admin  — Conductor admin. Same as owner.
  edit   — shared with "Can edit": change settings, run now, pause/resume,
           stop, see run history and logs, test-run the schedule's script.
           Cannot delete, cannot share, cannot swap the owner's script,
           dashboard or SharePoint site.
  view   — shared with "Can view": see the schedule, its run history and logs.
  None   — no access (the API answers 404 so it doesn't reveal the schedule).
"""
from typing import Dict, List, Optional, Set, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import Schedule, ScheduleShare, User
from deps import is_admin

RANK = {None: 0, "view": 1, "edit": 2, "admin": 3, "owner": 3}


def shared_with_me(db: Session, user: User) -> Dict[int, str]:
    """schedule_id → "edit" | "view" for schedules other people shared with this user."""
    rows = db.query(ScheduleShare.schedule_id, ScheduleShare.access).filter(ScheduleShare.user_id == user.id).all()
    return {sid: (acc if acc in ("edit", "view") else "view") for sid, acc in rows}


def role_for(db: Session, user: User, s: Schedule, shared: Optional[Dict[int, str]] = None) -> Optional[str]:
    if s.owner_id == user.id:
        return "owner"
    if is_admin(user):
        return "admin"
    if shared is None:
        row = db.query(ScheduleShare.access).filter(ScheduleShare.schedule_id == s.id,
                                                    ScheduleShare.user_id == user.id).first()
        return (row[0] if row[0] in ("edit", "view") else "view") if row else None
    return shared.get(s.id)


def require(db: Session, user: User, s: Optional[Schedule], need: str = "view") -> str:
    """Raise unless the user has at least `need` ("view" | "edit" | "owner") on the schedule."""
    if not s:
        raise HTTPException(404, "Schedule not found")
    r = role_for(db, user, s)
    if r is None:
        raise HTTPException(404, "Schedule not found")
    if RANK[r] < RANK[need]:
        if need == "owner":
            raise HTTPException(403, "Only the owner or an admin can do this")
        raise HTTPException(403, "You can view this schedule but not change it")
    return r


def shared_scope(db: Session, user: User, need: str = "view") -> Tuple[List[int], List[int]]:
    """
    (schedule_ids, script_ids) the user can reach through sharing at `need` level.
    Script ids come from shared *script* schedules, so people can see that
    script's runs (a script schedule's history is the script's history) and,
    with edit access, test-run it.
    """
    shared = shared_with_me(db, user)
    sids = [sid for sid, acc in shared.items() if RANK[acc] >= RANK[need]]
    if not sids:
        return [], []
    script_ids = [sc for (sc,) in db.query(Schedule.script_id)
                  .filter(Schedule.id.in_(sids), Schedule.schedule_type == "script", Schedule.script_id.isnot(None)).all()]
    return sids, sorted(set(script_ids))


def can_use_script(db: Session, user: User, script, need: str = "edit") -> bool:
    """Owner/admin, or someone with `need` access to a schedule that runs this script."""
    if not script:
        return False
    if is_admin(user) or script.owner_id == user.id:
        return True
    _, script_ids = shared_scope(db, user, need)
    return script.id in script_ids


def share_info(db: Session, user: User, schedules: List[Schedule]) -> Dict[int, dict]:
    """Extra fields for the Schedules page: my_access, share_count, last edited by, shared_at."""
    if not schedules:
        return {}
    ids = [s.id for s in schedules]
    shared = shared_with_me(db, user)
    # Who each schedule is shared with (oldest first), for the "Shared with Priya +2" tag
    people: Dict[int, List[dict]] = {}
    for sid, name, email, acc in (db.query(ScheduleShare.schedule_id, User.name, User.email, ScheduleShare.access)
                                  .join(User, User.id == ScheduleShare.user_id)
                                  .filter(ScheduleShare.schedule_id.in_(ids))
                                  .order_by(ScheduleShare.created_at).all()):
        people.setdefault(sid, []).append({"name": name or email, "access": acc})
    counts = {sid: len(v) for sid, v in people.items()}
    # When each schedule was shared with this user (drives the "New" tag)
    shared_at = {sid: at for sid, at in db.query(ScheduleShare.schedule_id, ScheduleShare.created_at)
                 .filter(ScheduleShare.user_id == user.id, ScheduleShare.schedule_id.in_(ids)).all()}
    editor_ids: Set[int] = {s.last_edited_by_id for s in schedules if getattr(s, "last_edited_by_id", None)}
    names = {u.id: u.name for u in db.query(User).filter(User.id.in_(editor_ids)).all()} if editor_ids else {}
    out = {}
    for s in schedules:
        out[s.id] = {
            "my_access":           role_for(db, user, s, shared) or "view",
            "share_count":         counts.get(s.id, 0),
            "last_edited_by_name": names.get(getattr(s, "last_edited_by_id", None)),
            "last_edited_at":      getattr(s, "last_edited_at", None),
            "shared_at":           shared_at.get(s.id),
            # Names are only for people who can manage sharing (owner / admin)
            "share_people":        people.get(s.id, []) if role_for(db, user, s, shared) in ("owner", "admin") else [],
        }
    return out