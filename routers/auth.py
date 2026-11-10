"""
routers/auth.py — Global Security integration.

Login flow:
  1. Frontend calls GS /security/token with credentials:"include"
     → browser's Windows session proves user identity
     → JWT payload contains userAuth (name, samAccountName, etc.)
  2. Frontend auto-fills username (read-only), user clicks Sign In
  3. Frontend sends samAccountName to POST /auth/login
  4. Backend calls GS /auth/sam (service account) to fetch roles
  5. Checks AppAccess securable → 403 if missing
  6. Creates/updates local User record, issues Conductor JWT
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import User
from schemas import TokenResponse, UserOut
from pydantic import BaseModel
from jose import jwt
from datetime import datetime, timedelta, timezone
import os

from services.global_security import (
    get_user_by_sam,
    logout_user,
    has_app_access,
    extract_role,
)

router = APIRouter(prefix="/auth", tags=["auth"])

SECRET    = os.getenv("APP_SECRET_KEY", "dev-secret")
ALGO      = "HS256"
EXP_HOURS = 72


# ── Request schema ─────────────────────────────────────────────────────────────

class GsLoginRequest(BaseModel):
    sam_account_name: str   # Windows username e.g. "jyu" — identity verified client-side


# ── Helpers ────────────────────────────────────────────────────────────────────

def _create_token(user_id: int, email: str = "") -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=EXP_HOURS)
    # "email" ties the token to the person, not just a row number, so a token
    # can never resolve to someone else (e.g. after switching databases).
    return jwt.encode({"sub": str(user_id), "email": (email or "").lower(), "exp": exp}, SECRET, algorithm=ALGO)


def _sync_user_from_gs(db: Session, gs_data: dict) -> User:
    """Create or update the local User record with fresh GS/AD data."""
    email = (gs_data.get("email") or "").lower().strip()
    name  = gs_data.get("name") or gs_data.get("displayName") or email
    dept  = gs_data.get("department") or ""
    title = gs_data.get("title") or ""
    role  = extract_role(gs_data)
    sam   = gs_data.get("samAccountName") or ""

    user = db.query(User).filter(User.email == email).first()
    if user:
        user.name             = name
        user.department       = dept
        user.title            = title
        user.role             = role
        user.sam_account_name = sam
        user.is_active        = True
    else:
        user = User(
            name             = name,
            email            = email,
            hashed_password  = "",
            role             = role,
            department       = dept,
            title            = title,
            sam_account_name = sam,
            is_active        = True,
        )
        db.add(user)

    db.commit()
    db.refresh(user)
    return user


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/gs_config")
def gs_config():
    """
    Return GS connection settings so the frontend can call GS directly
    without hardcoding URLs. Called on the login page before sign-in.
    """
    return {
        "gs_base_url": os.getenv("GS_BASE_URL", "https://gsmodule.medpointmanagement.com"),
        "gs_app_id":   int(os.getenv("GS_APP_ID", "1045")),
    }


@router.post("/login", response_model=TokenResponse)
def login(body: GsLoginRequest, db: Session = Depends(get_db)):
    """
    Issue a Conductor session JWT after GS identity check.
    The user's Windows identity was already verified client-side;
    this call fetches their roles using the server service account.
    """
    try:
        gs_data = get_user_by_sam(body.sam_account_name)
    except Exception as e:
        raise HTTPException(502, f"Global Security API unavailable: {e}")

    if gs_data is None:
        raise HTTPException(401, "User not found in Global Security")

    if not gs_data.get("enabled", True):
        raise HTTPException(403, "Your AD account is disabled")

    # Uncomment once Ryan sets up the real Conductor app ID in GS:
    if not has_app_access(gs_data):
        raise HTTPException(403, "You do not have access to Conductor. Contact your administrator.")

    user  = _sync_user_from_gs(db, gs_data)
    token = _create_token(user.id, user.email)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/logout")
def logout(sam_account_name: str):
    """Record logout in GS (best-effort) — frontend clears JWT regardless."""
    logout_user(sam_account_name)
    return {"ok": True}


@router.get("/dev_mode")
def dev_mode_status():
    base = os.getenv("GS_BASE_URL", "")
    return {"dev_mode": "test" in base}

# @router.get("/dev_mode")
# def dev_mode_status():
#     dev_mode = os.getenv("DEV_MODE", "false").lower() == "true"
#     return {"dev_mode": dev_mode}