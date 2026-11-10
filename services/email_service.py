"""
services/email_service.py
Sends emails via Microsoft Graph API using a service account shared mailbox.

Required .env variables:
    EMAIL_TENANT_ID      — Azure AD tenant ID
    EMAIL_CLIENT_ID      — App registration client ID
    EMAIL_CLIENT_SECRET  — App registration client secret (Secret Value)
    EMAIL_SENDER         — Service account email address (shared mailbox)

Install: pip install requests  (already in requirements.txt)
"""
import os
import base64
import traceback
import logging
from datetime import datetime
from typing import List, Optional

import pytz
import requests
from dotenv import load_dotenv
load_dotenv()  # ensure .env is loaded even when called from background threads

log = logging.getLogger(__name__)

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"

def _build_signature() -> str:
    sender = os.getenv("EMAIL_SENDER", "").strip() or "svc_mpmconductor@medpointmanagement.com"
    return f"""
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="direction:ltr; width:100%; box-sizing:border-box; border-collapse:collapse; border-spacing:0px; margin-top:24px;">
      <tbody>
        <tr>
          <td align="left" style="direction:ltr; vertical-align:top;">
            <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="direction:ltr; box-sizing:border-box; border-collapse:collapse; border-spacing:0px;">
              <tbody>
                <tr>
                  <td align="left" style="direction:ltr; padding-top:13px; padding-bottom:13px; vertical-align:top;">
                    <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="direction:ltr; white-space:nowrap; color:rgb(0,0,1); box-sizing:border-box; border-collapse:collapse; border-spacing:0px;">
                      <tbody>
                        <tr>
                          <td align="left" style="direction:ltr; white-space:nowrap; vertical-align:top;">
                            <div style="direction:ltr; white-space:nowrap; font-family:Verdana; font-size:13.33px; color:rgb(0,0,1);">
                              <span style="font-weight:700;">MPM Conductor</span>
                            </div>
                          </td>
                          <td align="left" style="direction:ltr; white-space:nowrap; vertical-align:top;">
                            <div style="direction:ltr; white-space:nowrap; font-family:Verdana; font-size:13.33px; color:rgb(0,0,1);">
                              <span style="font-weight:700;">&nbsp;|&nbsp;</span>
                            </div>
                          </td>
                          <td align="left" style="direction:ltr; white-space:nowrap; vertical-align:top;">
                            <div style="direction:ltr; white-space:nowrap; font-family:Verdana; font-size:13.33px; color:rgb(0,0,1);">
                              <span style="font-weight:700;">Automation & Reporting Platform, HIT Operations</span>
                            </div>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                    <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="direction:ltr; white-space:nowrap; color:rgb(58,86,126); box-sizing:border-box; border-collapse:collapse; border-spacing:0px; margin-top:2px;">
                      <tbody>
                        <tr>
                          <td align="left" style="direction:ltr; white-space:nowrap; vertical-align:top;">
                            <div style="direction:ltr; white-space:nowrap; font-family:Verdana; font-size:13.33px; color:rgb(58,86,126);">
                              <span style="font-weight:700;">MedPOINT&nbsp;-&nbsp;Pointing&nbsp;Healthcare&nbsp;in&nbsp;the&nbsp;Right&nbsp;Direction</span>
                            </div>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td align="left" style="direction:ltr; padding-top:13px; vertical-align:top;">
                    <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="direction:ltr; white-space:nowrap; color:rgb(134,154,182); box-sizing:border-box; border-collapse:collapse; border-spacing:0px;">
                      <tbody>
                        <tr>
                          <td align="left" style="direction:ltr; white-space:nowrap; vertical-align:top;">
                            <div style="direction:ltr; white-space:nowrap; font-family:Verdana; font-size:10.67px; color:rgb(134,154,182);">
                              <span style="font-weight:700;">Tel: <a href="tel:818.702.0100" style="color:rgb(134,154,182); text-decoration:none;">818.702.0100&nbsp;</a></span>
                            </div>
                          </td>
                        </tr>
                        <tr>
                          <td align="left" style="direction:ltr; white-space:nowrap; vertical-align:top;">
                            <div style="direction:ltr; white-space:nowrap; font-family:Verdana; font-size:10.67px; color:rgb(134,154,182);">
                              <span style="font-weight:700;">Email: <a href="mailto:{sender}" style="color:rgb(134,154,182); text-decoration:none;">{sender}</a></span>
                            </div>
                          </td>
                        </tr>
                        <tr>
                          <td align="left" style="direction:ltr; white-space:nowrap; vertical-align:top;">
                            <div style="direction:ltr; white-space:nowrap; font-family:Verdana; font-size:10.67px; color:rgb(134,154,182);">
                              <span style="font-weight:700;">VISIT&nbsp;OUR&nbsp;WEBSITE&nbsp;AT: <a href="http://www.medpointmanagement.com/" style="color:rgb(134,154,182); text-decoration:none;">http://www.medpointmanagement.com&nbsp;</a></span>
                            </div>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td align="left" style="direction:ltr; padding-top:13px; vertical-align:top;">
                    <div style="direction:ltr; font-family:Verdana; font-size:10px; color:rgb(134,154,182);">
                      CONFIDENTIAL &amp; PRIVILEGED: The information contained in this communication is confidential, is intended only for the use of the recipient named above, and may be legally privileged. If the reader of this message is not the intended recipient, you are hereby notified that any review, use, dissemination, distribution or copying of this communication is strictly prohibited and maybe unlawful. If you have received this communication in error, please contact the sender by reply e-mail and delete the original message, any attachments, or any copy of it from your computer system. Additionally, this e-mail and/or its attachments may contain Protected Health Information (PHI), as defined by applicable law. Generally, PHI is health care information by which a patient can be identified. If PHI is present, it is being provided with appropriate patient authorization or under circumstances that do not require patient authorization. You, being the recipient of PHI, are obligated to maintain PHI in a safe, secure and confidential manner and to use PHI only for the limited purposes for which it was disclosed. Re-disclosure of PHI without additional patient consent or as permitted by law is prohibited. Unauthorized re-disclosure or failure to maintain confidentiality could subject you to penalties described in federal and state laws.
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </td>
        </tr>
      </tbody>
    </table>
    """


# ── Token ─────────────────────────────────────────────────────────────────────

def _get_token() -> str:
    """Acquire a Graph API access token using client credentials flow."""
    tenant_id     = os.getenv("EMAIL_TENANT_ID", "").strip()
    client_id     = os.getenv("EMAIL_CLIENT_ID", "").strip()
    client_secret = os.getenv("EMAIL_CLIENT_SECRET", "").strip()

    if not all([tenant_id, client_id, client_secret]):
        raise RuntimeError(
            "EMAIL_TENANT_ID, EMAIL_CLIENT_ID and EMAIL_CLIENT_SECRET "
            "must be set in .env to send emails via Graph API."
        )

    url  = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type":    "client_credentials",
        "client_id":     client_id,
        "client_secret": client_secret,
        "scope":         "https://graph.microsoft.com/.default",
    }
    r = requests.post(url, data=data, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Token request failed ({r.status_code}): {r.text}")
    return r.json()["access_token"]


# ── Core send ─────────────────────────────────────────────────────────────────

def _send(
    to:          List[str],
    subject:     str,
    html_body:   str,
    cc:          Optional[List[str]] = None,
    attachments: Optional[List[str]] = None,   # list of file paths
) -> None:
    """
    Send an email via Microsoft Graph API from the shared mailbox.
    Raises on failure so callers can handle/log the error.
    """
    if not to:
        return

    sender = os.getenv("EMAIL_SENDER", "").strip()
    if not sender:
        raise RuntimeError("EMAIL_SENDER must be set in .env")

    token = _get_token()

    # Append the standard Conductor signature to every outgoing email
    html_body = f"{html_body}{_build_signature()}"

    # Build recipient lists
    def _addr(email: str) -> dict:
        return {"emailAddress": {"address": email.strip()}}

    # Build attachment list (base64-encoded)
    graph_attachments = []
    for path in (attachments or []):
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                content_b64 = base64.b64encode(f.read()).decode("utf-8")
            graph_attachments.append({
                "@odata.type":  "#microsoft.graph.fileAttachment",
                "name":         os.path.basename(path),
                "contentBytes": content_b64,
            })

    payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content":     html_body,
            },
            "toRecipients":  [_addr(e) for e in to],
            "ccRecipients":  [_addr(e) for e in (cc or [])],
            "attachments":   graph_attachments,
            "from": {
                "emailAddress": {"address": sender}
            },
        },
        "saveToSentItems": True,
    }

    url = f"{GRAPH_ROOT}/users/{sender}/sendMail"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }
    r = requests.post(url, json=payload, headers=headers, timeout=60)

    if r.status_code == 202:
        log.info(f"[email_service] Sent '{subject}' → {to}")
        print(f"[EMAIL] Sent '{subject}' → {to}")
    else:
        raise RuntimeError(f"Graph API sendMail failed ({r.status_code}): {r.text}")


# ── Shared SharePoint result block ────────────────────────────────────────────

def build_sharepoint_block(
    sp_status: str,
    sp_mode:   str = "replace",   # "replace" | "update_tab"
    sp_detail: str = "",          # newline-separated file paths, OR multi-line update_tab summary
    sp_error:  str = "",          # newline-separated error lines
    web_urls:  str = "",          # newline-separated clickable URLs (SharePoint schedules only)
    site_name: str = "",          # SharePoint site display name (shown as a header when provided)
) -> str:
    """
    Render the standardized SharePoint result block embedded in run notification
    emails (script, Tableau, and SharePoint schedules all use this).

    Returns an HTML string, or "" when sp_status is empty / not configured.

    Notes on inputs (kept consistent with existing behavior — no new escaping):
      - sp_detail is treated as pre-formatted content. In "update_tab" mode it is
        a multi-line summary (site / folder / workbook / table); otherwise it is
        a newline-separated list of posted file paths.
      - web_urls, when provided, renders a list of links and is used in place of a
        plain path list (SharePoint-schedule emails).
      - site_name, when provided, is shown as a "Site: <name>" header above the
        file list so the reader can see where files landed regardless of which
        schedule type (script / Tableau / SharePoint) triggered the upload.
    """
    site_hdr = (
        f"<div style='margin:2px 0 6px;'>Site: <b>{site_name}</b></div>"
        if site_name else ""
    )
    if sp_status == "success":
        if sp_mode == "update_tab":
            detail = sp_detail.replace("\n", "<br>").replace("  • ", "&nbsp;&nbsp;• ")
            inner = (
                f"📁 SharePoint workbook updated in place:"
                f"<div style='margin-top:6px;line-height:1.7;'>{detail}</div>"
            )
        elif web_urls.strip():
            links = "".join(
                f"<div style='margin:2px 0;'><a href='{u}'>{u}</a></div>"
                for u in web_urls.split("\n") if u.strip()
            )
            inner = f"📁 Output file(s) have also been posted to SharePoint:{site_hdr}<div style='margin-top:6px;'>{links}</div>"
        else:
            items = "".join(f"<li>{p}</li>" for p in sp_detail.split("\n") if p)
            inner = f"📁 Output file(s) have also been posted to SharePoint:{site_hdr}<ul style='margin:4px 0 0 18px;'>{items}</ul>"
        return (
            f"<div style='margin-top:12px;padding:10px 14px;background:#f0fdf4;"
            f"border-left:3px solid #16a34a;border-radius:4px;font-size:13px;color:#15803d;'>{inner}</div>"
        )

    if sp_status == "failed":
        err_items = "".join(f"<li>{e}</li>" for e in sp_error.split("\n") if e)
        return (
            f"<div style='margin-top:12px;padding:10px 14px;background:#fef2f2;"
            f"border-left:3px solid #dc2626;border-radius:4px;font-size:13px;color:#991b1b;'>"
            f"⚠️ Posting the output file(s) to SharePoint <b>failed</b>:{site_hdr}<ul style='margin:4px 0 0 18px;'>{err_items}</ul></div>"
        )

    if sp_status == "partial":
        ok_items  = "".join(f"<li>{p}</li>" for p in sp_detail.split("\n") if p)
        err_items = "".join(f"<li>{e}</li>" for e in sp_error.split("\n") if e)
        return (
            f"<div style='margin-top:12px;padding:10px 14px;background:#fffbeb;"
            f"border-left:3px solid #d97706;border-radius:4px;font-size:13px;color:#92400e;'>"
            f"⚠️ Some output files <b>failed</b> to post to SharePoint.{site_hdr}<br>"
            f"<b>Posted:</b><ul style='margin:4px 0 0 18px;'>{ok_items}</ul>"
            f"<b>Failed:</b><ul style='margin:4px 0 0 18px;'>{err_items}</ul></div>"
        )

    return ""


# ── Script run notification ───────────────────────────────────────────────────

def send_run_notification(
    recipients:  List[str],
    script_name: str,
    status:      str,
    duration_ms: int,
    output:      str,
    error:       str,
    started_at:  datetime,
    sp_status:   str = "",   # "" | "success" | "failed"
    sp_path:     str = "",
    sp_error:    str = "",
    sp_mode:     str = "replace",  # "replace" | "update_tab"
    sp_site:     str = "",   # SharePoint site display name
) -> None:
    minutes, seconds = divmod(duration_ms // 1000, 60)
    duration_str = f"{minutes}m {seconds}s"
    icon  = "✅" if status == "success" else "❌"
    color = "#059669" if status == "success" else "#dc2626"
    label = "Success" if status == "success" else "Failed"

    output_block = ""
    if output:
        trimmed = output[-3000:] if len(output) > 3000 else output
        output_block = f"""
        <div style="margin-top:16px;">
          <p style="margin:0 0 6px;font-size:12px;color:#6b7280;font-weight:600;text-transform:uppercase;">Output</p>
          <pre style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:12px;
                      font-size:12px;overflow:auto;white-space:pre-wrap;">{trimmed}</pre>
        </div>"""

    error_block = ""
    if error:
        error_block = f"""
        <div style="margin-top:16px;">
          <p style="margin:0 0 6px;font-size:12px;color:#6b7280;font-weight:600;text-transform:uppercase;">Error</p>
          <pre style="background:#fef2f2;border:1px solid #fecaca;border-radius:6px;padding:12px;
                      font-size:12px;overflow:auto;white-space:pre-wrap;color:#991b1b;">{error}</pre>
        </div>"""

    sp_block = build_sharepoint_block(
        sp_status=sp_status,
        sp_mode=sp_mode,
        sp_detail=sp_path,
        sp_error=sp_error,
        site_name=sp_site,
    )

    pacific_time = started_at.replace(tzinfo=pytz.utc).astimezone(
        pytz.timezone("America/Los_Angeles")
    ).strftime("%Y-%m-%d %I:%M:%S %p %Z")

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                max-width:600px;margin:0 auto;background:#fff;">
      <div style="background:{color};padding:24px 28px;border-radius:10px 10px 0 0;">
        <h2 style="margin:0;color:#fff;font-size:18px;">{icon} Script {label}: {script_name}</h2>
      </div>
      <div style="padding:24px 28px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 10px 10px;">
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
          <tr><td style="padding:8px 0;color:#6b7280;width:140px;">Script</td>
              <td style="padding:8px 0;font-weight:600;color:#111827;">{script_name}</td></tr>
          <tr><td style="padding:8px 0;color:#6b7280;">Status</td>
              <td style="padding:8px 0;font-weight:600;color:{color};">{label}</td></tr>
          <tr><td style="padding:8px 0;color:#6b7280;">Started</td>
              <td style="padding:8px 0;color:#374151;">{pacific_time}</td></tr>
          <tr><td style="padding:8px 0;color:#6b7280;">Duration</td>
              <td style="padding:8px 0;color:#374151;">{duration_str}</td></tr>
        </table>
        {output_block}
        {error_block}
        {sp_block}
        <p style="margin:24px 0 0;font-size:12px;color:#9ca3af;
                  border-top:1px solid #f3f4f6;padding-top:16px;">
          Sent automatically by MPM Conductor.
        </p>
      </div>
    </div>"""

    subject = f"[MPM Conductor] {icon} {script_name} — {label}"
    if sp_status in ("failed", "partial"):
        subject += " (⚠️ SharePoint posting issue)"
    try:
        _send(recipients, subject, html)
    except Exception:
        log.error(f"[email_service] Failed to send run notification:\n{traceback.format_exc()}")
        print(f"[EMAIL] Failed to send notification:\n{traceback.format_exc()}")


# ── Schedule sharing ──────────────────────────────────────────────────────────
# Emails the person a schedule was shared with when access is given, changed or
# removed. "Open in Conductor" links to the address the person sharing is using
# (CONDUCTOR_URL in .env overrides it, if ever needed).
_ACCESS_LABEL = {"edit": "Can edit", "view": "Can view"}
_ACCESS_TEXT = {
    "edit": "you can change its settings, run it now, pause it and see its run history",
    "view": "you can see the schedule, its run history and logs",
}
_TYPE_LABEL = {"script": "Script", "tableau": "Tableau", "sharepoint": "SharePoint"}


def _esc(v) -> str:
    import html as _h
    return _h.escape(str(v or ""), quote=True)


def send_share_notification(
    kind:          str,            # "shared" | "changed" | "removed"
    to_email:      str,
    actor_name:    str,
    schedule_id:   int,
    schedule_name: str,
    schedule_type: str = "script",
    access:        str = "",       # new access ("edit" | "view")
    old_access:    str = "",       # previous access, for "changed"
    next_run_utc:  Optional[datetime] = None,
    app_url:       str = "",       # Conductor's address for the button (from the sharing request)
) -> None:
    if not to_email:
        return
    name = _esc(schedule_name)
    actor = _esc(actor_name)
    rows = [("Schedule", name), ("Type", _TYPE_LABEL.get(schedule_type or "script", "Script"))]
    if kind == "shared":
        color, head = "#2563eb", f"🔗 Shared with you: {name}"
        subject = f"[MPM Conductor] {actor_name} shared “{schedule_name}” with you"
        intro = (f"{actor} gave you access to a schedule in Conductor. With <b>{_ACCESS_LABEL.get(access, access)}</b>, "
                 f"{_ACCESS_TEXT.get(access, '')}.")
        if next_run_utc:
            nxt = next_run_utc.replace(tzinfo=pytz.utc).astimezone(pytz.timezone("America/Los_Angeles"))
            rows.append(("Next run", nxt.strftime("%b %d, %I:%M %p %Z").replace(" 0", " ")))
        rows += [("Your access", _ACCESS_LABEL.get(access, access)), ("Shared by", actor)]
    elif kind == "changed":
        color, head = "#7c3aed", f"✏️ Access changed: {name}"
        subject = f"[MPM Conductor] Your access to “{schedule_name}” changed"
        intro = f"{actor} changed your access. Now {_ACCESS_TEXT.get(access, '')}."
        if access == "view":
            intro += " You can no longer change or run it."
        rows += [("Your access", f"{_ACCESS_LABEL.get(access, access)} "
                                 f"<span style=\"color:#9ca3af;font-weight:400;\">(was {_ACCESS_LABEL.get(old_access, old_access)})</span>"),
                 ("Changed by", actor)]
    else:
        color, head = "#6b7280", f"Access removed: {name}"
        subject = f"[MPM Conductor] You no longer have access to “{schedule_name}”"
        intro = (f"{actor} removed your access. The schedule won't show on your Schedules page anymore. "
                 f"Ask them if you still need it.")
        rows += [("Removed by", actor)]

    base = (app_url or os.getenv("CONDUCTOR_URL") or "").rstrip("/")
    # Every email ends the same way: details, then the button, then the footer.
    # "Removed" links to Conductor itself (the schedule is no longer theirs to open).
    button = ""
    if base:
        href, label = ((f"{base}/", "Open Conductor") if kind == "removed"
                       else (f"{base}/?schedule={int(schedule_id)}", "Open in Conductor"))
        button = (f'<a href="{_esc(href)}" style="display:inline-block;margin-top:18px;'
                  f'background:#2563eb;color:#fff;text-decoration:none;font-weight:600;font-size:14px;'
                  f'padding:10px 18px;border-radius:8px;">{label}</a>')
    table = "".join(f'<tr><td style="padding:8px 0;color:#6b7280;width:130px;">{a}</td>'
                    f'<td style="padding:8px 0;font-weight:600;color:#111827;">{b}</td></tr>' for a, b in rows)
    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:600px;margin:0 auto;background:#fff;">
      <div style="background:{color};padding:22px 28px;border-radius:10px 10px 0 0;">
        <h2 style="margin:0;color:#fff;font-size:18px;">{head}</h2>
      </div>
      <div style="padding:22px 28px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 10px 10px;font-size:14px;color:#374151;">
        <p style="margin:0 0 12px;line-height:1.55;">{intro}</p>
        <table style="width:100%;border-collapse:collapse;font-size:14px;">{table}</table>
        {button}
        <p style="margin:24px 0 0;font-size:12px;color:#9ca3af;border-top:1px solid #f3f4f6;padding-top:16px;">
          Sent automatically by MPM Conductor.
        </p>
      </div>
    </div>"""
    try:
        _send([to_email], subject, html)
        log.info(f"[email_service] Share email ({kind}) sent to {to_email} for schedule id={schedule_id}")
    except Exception:
        log.error(f"[email_service] Failed to send share email ({kind}) to {to_email}:\n{traceback.format_exc()}")