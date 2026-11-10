"""
services/global_security.py
Thin wrapper around the Global Security API.

Base URLs (set GS_BASE_URL in .env):
  Production: https://gsmodule.medpointmanagement.com
  Test:       https://gsmodule-test.medpointmanagement.com

Identity verification happens on the FRONTEND via the browser's Windows
credentials (credentials: "include" on GS /security/token).
The backend uses the server service account (HttpNegotiateAuth) only to
fetch the user's roles/securables after identity is confirmed.
"""
import os
from typing import Optional
import requests
from requests_negotiate_sspi import HttpNegotiateAuth

GS_BASE_URL = os.getenv("GS_BASE_URL", "https://gsmodule.medpointmanagement.com")
GS_APP_ID   = int(os.getenv("GS_APP_ID", "1045"))

# Securable names — must match exactly what Ryan configured in Global Security
SECURABLE_APP_ACCESS      = "AppAccess"
SECURABLE_USER_MANAGEMENT = "UserManagement"
SECURABLE_VIEW_ALL_DATA   = "ViewAllData"

def get_user_by_sam(sam_account_name: str) -> Optional[dict]:
    """
    Call GET /auth/sam using the server service account (SSPI/Negotiate).
    Used after the frontend has already verified the user's identity via
    the browser's own Windows credentials.
    Returns the full UserAuth dict, or None if not found.
    """
    url    = f"{GS_BASE_URL}/auth/sam"
    params = {"appID": GS_APP_ID, "samAccountName": sam_account_name}
    auth   = HttpNegotiateAuth()

    resp = requests.get(url, params=params, auth=auth, timeout=10)

    if resp.status_code in (401, 404):
        return None
    resp.raise_for_status()
    return resp.json()


def logout_user(sam_account_name: str) -> None:
    """
    Call POST /security/logout to record the user exiting the app.
    Silently ignores failures — best-effort only.
    """
    url    = f"{GS_BASE_URL}/security/logout"
    params = {"appID": GS_APP_ID}
    try:
        requests.post(url, params=params, auth=HttpNegotiateAuth(), timeout=5)
    except Exception as e:
        print(f"[GS] logout call failed (non-critical): {e}")


# ── Helpers to read securables from a UserAuth dict ───────────────────────────

def _get_securable_level(user_auth: dict, securable_name: str) -> Optional[str]:
    for role in user_auth.get("roles", []):
        securables = role.get("securables", {})
        if securable_name in securables:
            return securables[securable_name]
    return None


def has_app_access(user_auth: dict) -> bool:
    level = _get_securable_level(user_auth, SECURABLE_APP_ACCESS)
    return (level or "").lower() == "true"


def is_admin_in_gs(user_auth: dict) -> bool:
    um  = (_get_securable_level(user_auth, SECURABLE_USER_MANAGEMENT) or "").lower()
    vad = (_get_securable_level(user_auth, SECURABLE_VIEW_ALL_DATA)   or "").lower()
    return um == "true" and vad == "true"


def extract_role(user_auth: dict) -> str:
    return "admin" if is_admin_in_gs(user_auth) else "user"
