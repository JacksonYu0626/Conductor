"""
deps.py — shared FastAPI dependencies for Conductor.

Defines get_current_user so every router can import it without
circular imports through main.py. SECRET is read lazily so
load_dotenv() in main.py always runs first.
"""
import os
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database import get_db
from models import User
from jose import jwt

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    secret = os.getenv("APP_SECRET_KEY", "dev-secret")   # lazy read — after load_dotenv()
    if not creds:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, secret, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(401, "Invalid or expired token")
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(401, "User not found or inactive")
    # The token must belong to this exact person. Older tokens (no email) and
    # tokens issued against a different database are rejected → sign in again.
    token_email = (payload.get("email") or "").lower()
    if not token_email or token_email != (user.email or "").lower():
        raise HTTPException(401, "Session no longer valid, please sign in again")
    return user


def is_admin(user: User) -> bool:
    return (user.role or "").lower() == "admin"


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not is_admin(user):
        raise HTTPException(403, "Admin access required")
    return user