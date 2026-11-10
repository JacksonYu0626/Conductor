# services/tableau_runner.py
"""
Executes a Tableau snapshot schedule:
  1. Renders all view URLs via TableauClient
  2. Sends email with attachments via Microsoft Graph API
  3. Writes a RunLog entry (log_type="tableau")
  4. Updates schedule.last_run_status / last_run_utc
"""
from __future__ import annotations
import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def run_tableau_schedule(schedule_id: int, triggered_by: str = "scheduler") -> None:
    """
    Main entrypoint — called by APScheduler or the run_now API endpoint.
    All DB work is done inside this function with its own session.
    """
    from database import SessionLocal
    from models import Schedule, RunLog

    db = SessionLocal()
    try:
        s: Optional[Schedule] = db.query(Schedule).filter(Schedule.id == schedule_id).first()
        if not s:
            log.warning(f"[tableau_runner] Schedule {schedule_id} not found")
            return

        started_at = _utcnow()
        tmp_files: List[str] = []

        # Resolve and snapshot owner name so it survives schedule/dashboard deletion
        from models import User as _User
        triggered_by_name = ""
        owner_id_snap     = None
        if triggered_by and "@" in triggered_by:
            u = db.query(_User).filter(_User.email == triggered_by).first()
            triggered_by_name = u.name if u else triggered_by
            owner_id_snap     = u.id   if u else None
        elif triggered_by in ("scheduler", "system"):
            if s.owner_id:
                owner = db.query(_User).filter(_User.id == s.owner_id).first()
                triggered_by_name = owner.name if owner else ""
                owner_id_snap     = s.owner_id

        # Create RunLog entry
        run_log = RunLog(
            log_type          = "tableau",
            schedule_id       = schedule_id,
            schedule_name     = s.name,
            trigger           = "schedule" if triggered_by == "scheduler" else "manual",
            triggered_by      = triggered_by,
            triggered_by_name = triggered_by_name,
            owner_id          = owner_id_snap,
            status            = "running",
            started_at        = started_at,
        )
        db.add(run_log)
        db.commit()
        db.refresh(run_log)
        log.info(f"[tableau_runner] Start schedule_id={schedule_id} name={s.name!r}")

        try:
            # Resolve view URLs (schedule overrides dashboard, else use dashboard URL)
            view_urls = _resolve_view_urls(s)
            if not view_urls:
                raise ValueError("No view URLs configured for this schedule")

            filters = json.loads(s.filters_json or "{}")
            fmt     = (s.fmt or "pdf").lower()
            out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tmp")
            os.makedirs(out_dir, exist_ok=True)

            # Render views — with one retry on PAT token invalidation
            from services.tableau_client import TableauClient, get_pat_lock

            attachments: List[str] = []
            pdf_paths:   List[str] = []

            def _render_all(view_urls, fmt, out_dir, filters):
                """Render all views and return (pdf_paths, attachments)."""
                _pdf, _att = [], []
                client = TableauClient()
                try:
                    for url in view_urls:
                        fp = client.render_view(url, fmt=fmt, out_dir=out_dir,
                                                extra_filters=filters or None)
                        tmp_files.append(fp)
                        if fmt == "pdf":
                            _pdf.append(fp)
                        else:
                            _att.append(fp)
                finally:
                    client._close_conn()
                return _pdf, _att

            PAT_ERROR_MARKERS = [
                "did not return paginated results",
                "valid auth token",
                "401",
                "invalid token",
                "not authenticated",
            ]

            with get_pat_lock():
                try:
                    pdf_paths, attachments = _render_all(view_urls, fmt, out_dir, filters)
                except Exception as render_err:
                    err_lower = str(render_err).lower()
                    is_auth_err = any(m.lower() in err_lower for m in PAT_ERROR_MARKERS)
                    if is_auth_err:
                        log.warning(f"[tableau_runner] Auth error — retrying with fresh token: {render_err}")
                        # Force re-authentication on retry
                        try:
                            from services.tableau_client import TableauClient as _TC
                            _TC._reset_auth()  # clears cached token if method exists
                        except Exception:
                            pass
                        pdf_paths, attachments = _render_all(view_urls, fmt, out_dir, filters)
                    else:
                        raise

            # Merge PDFs if multiple
            if fmt == "pdf":
                if len(pdf_paths) > 1:
                    try:
                        from PyPDF2 import PdfMerger
                        merged = os.path.join(out_dir, f"tableau_merged_{schedule_id}.pdf")
                        merger = PdfMerger()
                        for p in pdf_paths:
                            merger.append(p)
                        merger.write(merged)
                        merger.close()
                        tmp_files.append(merged)
                        attachments = [merged]
                    except ImportError:
                        attachments = pdf_paths
                else:
                    attachments = pdf_paths

            # ── SharePoint upload (do this BEFORE email so the email can reflect the real outcome) ──
            sp_folder   = ""
            sp_filename = ""
            sp_status   = ""   # "" = not configured, "success", "failed"
            sp_error    = ""
            sp_web_url  = ""
            sp_site     = ""
            if s.sharepoint_site_id and attachments:
                import re
                safe_name   = re.sub(r"[^\w\s-]", "", s.name).strip().replace(" ", "_")
                sp_filename = f"{safe_name}_{datetime.now().strftime('%Y%m%d')}.{fmt}"
                sp_folder   = s.sharepoint_folder or "/"
                # Resolve destination site display name for the email
                try:
                    from models import SharepointSite
                    _site = db.query(SharepointSite).filter(
                        SharepointSite.id == s.sharepoint_site_id
                    ).first()
                    sp_site = (_site.name or "") if _site else ""
                except Exception:
                    sp_site = ""
                try:
                    from services.sharepoint_runner import post_file_to_sharepoint
                    sp_web_url = post_file_to_sharepoint(
                        site_id   = s.sharepoint_site_id,
                        folder    = sp_folder,
                        filename  = sp_filename,
                        file_bytes = open(attachments[0], "rb").read(),
                    )
                    sp_status = "success"
                    log.info(f"[tableau_runner] SharePoint upload success: {sp_filename}")
                except Exception as sp_err:
                    sp_status = "failed"
                    sp_error  = str(sp_err)
                    log.error(f"[tableau_runner] SharePoint upload failed (non-fatal): {sp_err}")

            # Send email — subject/body reflect SP outcome too
            subject = f"[MPM Conductor] Tableau Snapshot — {s.name}"
            if sp_status == "failed":
                subject += " (⚠️ SharePoint posting failed)"
            body = _build_email_body(s, view_urls, sp_folder=sp_folder, sp_filename=sp_filename,
                                      sp_status=sp_status, sp_error=sp_error, sp_site=sp_site)
            _send_email(s.email_to, subject, body, attachments, s.cc_to or "")

            # If SP failed, also notify the schedule owner (in case they're not in email_to/cc_to)
            if sp_status == "failed":
                _notify_owner_sp_failure(db, s, sp_folder, sp_filename, sp_error)

            sp_status_str = (
                f" | SharePoint: OK - {sp_filename} -> {sp_folder}" if sp_status == "success" else
                f" | SharePoint: FAILED - {sp_error}" if sp_status == "failed" else ""
            )

            # ── Success ──────────────────────────────────────────────────
            finished_at  = _utcnow()
            duration_ms  = int((finished_at - started_at).total_seconds() * 1000)

            s.last_run_utc    = finished_at
            s.last_run_status = "success"
            s.last_error      = None
            s.status          = "completed" if s.recurrence == "once" else "scheduled"

            run_log.status      = "success"
            run_log.finished_at = finished_at
            run_log.duration_ms = duration_ms
            run_log.output      = (
                f"Sent {len(attachments)} attachment(s) to {s.email_to}"
                + (f" | CC: {s.cc_to}" if s.cc_to else "")
                + sp_status_str
            )
            run_log.error       = ""

            db.commit()
            log.info(f"[tableau_runner] Success schedule_id={schedule_id} duration={duration_ms}ms")

        except Exception as e:
            finished_at = _utcnow()
            duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            err_str     = str(e)

            s.last_run_utc    = finished_at
            s.last_run_status = "failed"
            s.last_error      = err_str
            s.status          = "failed" if s.recurrence == "once" else "scheduled"

            run_log.status      = "failed"
            run_log.finished_at = finished_at
            run_log.duration_ms = duration_ms
            run_log.error       = err_str

            db.commit()
            log.error(f"[tableau_runner] Failed schedule_id={schedule_id} error={err_str}")

        finally:
            for fp in tmp_files:
                try:
                    if fp and os.path.exists(fp):
                        os.remove(fp)
                except Exception as ce:
                    log.warning(f"[tableau_runner] Could not delete tmp file {fp}: {ce}")

    finally:
        db.close()


def _resolve_view_urls(s) -> List[str]:
    """Return the list of view URLs for a schedule, falling back to dashboard."""
    try:
        urls = json.loads(s.view_urls_json or "[]")
        if urls:
            return urls
    except Exception:
        pass
    # Fall back to linked dashboard
    if s.dashboard:
        urls = [s.dashboard.view_url]
        try:
            extra = json.loads(s.dashboard.additional_urls_json or "[]")
            urls += extra
        except Exception:
            pass
        return urls
    return []


def _get_export_lock():
    """DEPRECATED: kept for backward compat. Use tableau_client.get_pat_lock() instead."""
    from services.tableau_client import get_pat_lock
    return get_pat_lock()


def _clean_view_url(url: str) -> str:
    """Remove /sheets/ segment from Tableau view URLs for cleaner display."""
    import re
    return re.sub(r"/sheets/", "/", url)

def _build_email_body(s, view_urls: List[str], sp_folder: str = "", sp_filename: str = "",
                       sp_status: str = "", sp_error: str = "", sp_site: str = "") -> str:
    clean_urls = [_clean_view_url(u) for u in view_urls]
    ul_items = "".join(f"<li>{u}</li>" for u in clean_urls)

    from services.email_service import build_sharepoint_block
    sp_path = f"{sp_folder.rstrip('/')}/{sp_filename}" if sp_filename else sp_folder
    sp_block = build_sharepoint_block(
        sp_status=sp_status,
        sp_mode="replace",
        sp_detail=sp_path,
        sp_error=sp_error,
        site_name=sp_site,
    )

    return (
        "<p>Hello,</p>"
        f"<p>Here is the automated Tableau snapshot for <b>{s.name}</b>.</p>"
        f"<p>Sources:</p><ul>{ul_items}</ul>"
        f"<p>Format: {(s.fmt or 'PDF').upper()}</p>"
        f"{sp_block}"
        "<p style='color:#6b7280;font-size:12px;margin-top:20px;'>"
        "Sent automatically by MPM Conductor.</p>"
    )


def _notify_owner_sp_failure(db, s, sp_folder: str, sp_filename: str, sp_error: str) -> None:
    """Ensure the schedule owner is notified of a SharePoint posting failure,
    even if they're not in email_to/cc_to."""
    try:
        from models import User
        owner_email = ""
        if s.owner_id:
            owner = db.query(User).filter(User.id == s.owner_id).first()
            owner_email = (owner.email or "") if owner else ""
        if not owner_email:
            return

        existing = set()
        for field in (s.email_to or "", s.cc_to or ""):
            existing |= {e.strip().lower() for e in field.replace(";", ",").split(",") if e.strip()}
        if owner_email.strip().lower() in existing:
            return  # owner already received the main email with the failure block

        sp_path = f"{sp_folder.rstrip('/')}/{sp_filename}" if sp_filename else sp_folder
        html = (
            "<p>Hello,</p>"
            f"<p>The Tableau snapshot for <b>{s.name}</b> was sent successfully, "
            f"but posting it to SharePoint <b>failed</b>.</p>"
            f"<p style='padding:10px 14px;background:#fef2f2;border-left:3px solid #dc2626;"
            f"border-radius:4px;font-size:13px;color:#991b1b;'>"
            f"Destination: <b>{sp_path}</b><br>Error: {sp_error}</p>"
            "<p style='color:#6b7280;font-size:12px;margin-top:20px;'>"
            "Sent automatically by MPM Conductor.</p>"
        )
        from services.email_service import _send
        _send(
            to        = [owner_email],
            subject   = f"[MPM Conductor] ⚠️ SharePoint Posting Failed — {s.name}",
            html_body = html,
        )
        log.info(f"[tableau_runner] Owner notified of SharePoint failure: {owner_email}")
    except Exception as e:
        log.error(f"[tableau_runner] Could not notify owner of SP failure: {e}")


def _send_email(to: str, subject: str, html_body: str, attachments: List[str], cc: str = "") -> None:
    """Send via Microsoft Graph API using the shared mailbox service account."""
    try:
        from services.email_service import _send

        to_list = [e.strip() for e in to.replace(";", ",").split(",") if e.strip()]
        cc_list = [e.strip() for e in cc.replace(";", ",").split(",") if e.strip()] if cc else []

        _send(
            to          = to_list,
            subject     = subject,
            html_body   = html_body,
            cc          = cc_list,
            attachments = attachments,
        )
        log.info(f"[tableau_runner] Email sent to {to}")
    except Exception as e:
        log.error(f"[tableau_runner] Email failed: {e}")
        raise
