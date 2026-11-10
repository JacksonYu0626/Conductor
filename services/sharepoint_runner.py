"""
services/sharepoint_runner.py — SharePoint upload execution.

run_sharepoint_schedule()       — called by APScheduler and run-now API
                                   reads from MPMC.schedules (schedule_type='sharepoint')
post_tableau_pdf_to_sharepoint() — called by tableau_runner after email delivery
"""
import logging
import os
import fnmatch
from datetime import datetime, timezone, date
from pathlib import Path

from database import SessionLocal
from models import Schedule, SharepointSite, RunLog, User

log = logging.getLogger(__name__)

DATE_FORMAT_MAP = {
    "YYYYMMDD":   "%Y%m%d",
    "MMDDYYYY":   "%m%d%Y",
    "YYYY-MM-DD": "%Y-%m-%d",
    "MM-DD-YYYY": "%m-%d-%Y",
    "YYYYMM":     "%Y%m",
    "MMYYYY":     "%m%Y",
    "MMM YYYY":   "%b %Y",
    "MMMM YYYY":  "%B %Y",
    "MON YYYY":   "%b %Y",
}


def run_sharepoint_schedule(schedule_id: int, triggered_by: str = "scheduler") -> None:
    db = SessionLocal()
    run_log = None
    try:
        s = db.query(Schedule).filter(
            Schedule.id == schedule_id,
            Schedule.schedule_type == "sharepoint"
        ).first()
        if not s:
            log.error(f"[sp_runner] SharePoint schedule {schedule_id} not found")
            return

        # Create a run_logs row so SharePoint runs appear in Run History
        run_log = _start_log(db, s, triggered_by)

        site = db.query(SharepointSite).filter(SharepointSite.id == s.sharepoint_site_id).first()
        if not site:
            _fail(db, s, "SharePoint site not found or deleted", run_log)
            return

        log.info(f"[sp_runner] Starting schedule id={schedule_id} '{s.name}' triggered_by={triggered_by}")

        from services.sharepoint_service import get_access_token, resolve_site_and_drive, resolve_drive_for_folder, resolve_tokens, upload_bytes

        upload_mode = (getattr(s, "upload_mode", None) or "replace").lower()

        # ── update_tab mode (#4): write data into a named Excel Table in place ───
        # Writes the source data into an existing .xlsx's named Table via the Graph
        # workbook API, preserving the rest of the workbook (pivot tables, etc.).
        if upload_mode == "update_tab":
            status, summary, err = _update_tab(s, site)
            if status == "failed":
                _fail(db, s, err or "Tab update failed", run_log); return
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            s.last_run_utc    = now
            s.last_run_status = "success"
            s.last_error      = None
            s.status          = "completed" if s.recurrence == "once" else "scheduled"
            if s.recurrence == "once":
                s.is_active = False
            db.commit()
            _finish_log(db, run_log, "success", output=summary)
            log.info(f"[sp_runner] Schedule {schedule_id} tab-update finished: {summary}")
            _send_notification(s, "success", web_url=summary, mode="update_tab")
            return

        # ── output_file_path mode (aligned with script schedules) ───────────────
        # `output_file_path` holds one "<local path>[ -> <dest folder>]" per line.
        if (s.output_file_path or "").strip():
            status, sp_paths, sp_errors = _post_output_files(s)
            if status == "failed":
                _fail(db, s, sp_errors or "All uploads failed", run_log); return

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            s.last_run_utc    = now
            s.last_run_status = status  # "success" or "partial"
            s.last_error      = sp_errors or None
            s.status          = "completed" if s.recurrence == "once" else "scheduled"
            if s.recurrence == "once":
                s.is_active = False
            db.commit()
            _finish_log(db, run_log, status, output=sp_paths, error=sp_errors)
            log.info(f"[sp_runner] Schedule {schedule_id} finished with status={status}")

            _send_notification(s, "success" if status == "success" else "partial",
                               web_url=sp_paths, error=sp_errors)
            return

        # ── Legacy single-file mode (source_path / source_folder+pattern) ───────
        # Auth
        try:
            token = get_access_token(site)
        except Exception as e:
            _fail(db, s, f"Token acquisition failed: {e}", run_log); return

        # Resolve site ID then drive based on folder path
        # (drive_id is NOT cached on site — it depends on the folder's library prefix)
        try:
            graph_site_id, _ = resolve_site_and_drive(token, site.site_url)
            dest_folder_raw   = resolve_tokens(s.sharepoint_folder or "/")
            drive_id, dest_folder = resolve_drive_for_folder(token, graph_site_id, dest_folder_raw)
        except Exception as e:
            _fail(db, s, f"Site/drive resolution failed: {e}", run_log); return

        dest_filename = resolve_tokens(getattr(s, "destination_filename", None) or s.name or "upload")

        # Fetch file
        try:
            file_bytes = _get_file_bytes(s)
        except Exception as e:
            _fail(db, s, f"File fetch failed: {e}", run_log); return

        # Upload
        try:
            result  = upload_bytes(token, drive_id, dest_folder, dest_filename, file_bytes)
            web_url = result.get("webUrl", "")
            log.info(f"[sp_runner] Upload complete → {web_url}")
        except Exception as e:
            _fail(db, s, f"Upload failed: {e}", run_log); return

        # Mark success
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        s.last_run_utc    = now
        s.last_run_status = "success"
        s.last_error      = None
        s.status          = "completed" if s.recurrence == "once" else "scheduled"
        if s.recurrence == "once":
            s.is_active = False
        db.commit()
        _finish_log(db, run_log, "success", output=web_url)
        log.info(f"[sp_runner] Schedule {schedule_id} completed successfully")

        # Send success notification
        _send_notification(s, "success", web_url=web_url)

    except Exception as e:
        log.exception(f"[sp_runner] Unexpected error for schedule {schedule_id}: {e}")
        try:
            s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
            if s: _fail(db, s, f"Unexpected error: {e}", run_log)
        except Exception:
            pass
    finally:
        db.close()


def _update_tab(s: Schedule, site):
    """
    update_tab mode (#4): read the source file's data rows and write them into a
    named Excel Table inside an existing .xlsx in SharePoint, in place.

    Interpretation of output_file_path (single logical row expected):
        <local source path>  ->  <destination workbook path incl. .xlsx>
    e.g.  M:\\data\\metadata.csv  ->  /Shared Documents/Reports/Summary.xlsx

    target_table identifies the Table (ListObject) to write into.
    Source data is read as rows; the header row is used to validate against the
    Table's headers (to protect the pivot's field names) and is NOT written as data.

    Returns (status, summary, error).
    """
    from services.sharepoint_service import (
        get_access_token, resolve_site_and_drive, resolve_drive_for_folder,
        resolve_tokens, resolve_item_id, update_table_in_workbook,
    )

    table_name = (getattr(s, "target_table", None) or "").strip()
    if not table_name:
        return "failed", "", "No target Table name configured for update-tab mode."
    target_sheet = (getattr(s, "target_sheet", None) or "").strip()

    raw_lines = [l.strip() for l in (s.output_file_path or "").splitlines() if l.strip()]
    if not raw_lines:
        return "failed", "", "No source/destination configured."
    line = raw_lines[0]
    if "->" not in line:
        return "failed", "", ("Update-tab mode needs '<local source> -> <destination .xlsx path>'. "
                              f"Got: {line}")
    src_raw, _, dest_raw = line.partition("->")
    src_path  = resolve_tokens(src_raw.strip())
    dest_path = resolve_tokens(dest_raw.strip())

    if not os.path.exists(src_path):
        return "failed", "", f"Source file not found: {src_path}"
    if not dest_path.lower().endswith((".xlsx", ".xlsm")):
        return "failed", "", f"Destination must be an .xlsx workbook. Got: {dest_path}"

    # Read the source into header + rows
    try:
        headers, rows = _read_source_rows(src_path)
    except Exception as e:
        return "failed", "", f"Could not read source file: {e}"
    if not headers:
        return "failed", "", "Source file has no header row."
    log.info(f"[sp_runner] Source read: {len(rows)} data rows, {len(headers)} columns from {os.path.basename(src_path)}")

    # Split dest_path into folder + filename, resolve drive + item
    try:
        token = get_access_token(site)
        graph_site_id, _ = resolve_site_and_drive(token, site.site_url)
        dest_folder = "/".join(dest_path.strip("/").split("/")[:-1])
        dest_file   = dest_path.strip("/").split("/")[-1]
        drive_id, folder_in_drive = resolve_drive_for_folder(token, graph_site_id, "/" + dest_folder)
        item_id = resolve_item_id(token, drive_id, folder_in_drive, dest_file)
    except Exception as e:
        return "failed", "", f"Could not resolve destination workbook: {e}"

    # Write into the Table (replace all data rows), validating headers
    try:
        result = update_table_in_workbook(
            token, drive_id, item_id, table_name, rows,
            replace=True, expected_headers=headers,
        )
    except Exception as e:
        return "failed", "", f"Workbook update failed: {e}"

    summary = (
        f"Updated table '{table_name}' ({result.get('rows_added', 0)} rows written) "
        f"in workbook '{dest_file}'.\n"
        f"  • Site: {site.name} ({site.site_url})\n"
        f"  • Folder: /{dest_folder}\n"
        f"  • Workbook: /{dest_path.strip('/')}\n"
        f"  • Table: {table_name}"
        + (f"\n  • Sheet/tab: {target_sheet}" if target_sheet else "")
        + "\nPivot tables refresh when the workbook is opened "
        f"(ensure 'Refresh data when opening the file' is enabled on the pivot)."
    )
    return "success", summary, ""


def _read_source_rows(path: str):
    """
    Read a CSV or XLSX source into (headers, rows).
    Detect by extension. Returns headers as a list of strings and rows as a
    list of lists. The header row is the first row; remaining rows are data.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        import csv
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = list(csv.reader(f))
        if not reader:
            return [], []
        headers = reader[0]
        # Coerce numeric-looking strings to numbers so Excel/pivots aggregate them.
        def _coerce(v):
            if v is None or v == "":
                return ""
            s = v.strip()
            try:
                if s.lstrip("-").isdigit():
                    return int(s)
                f = float(s)
                return f
            except ValueError:
                return v
        rows = [[_coerce(c) for c in row] for row in reader[1:]]
        return headers, rows
    elif ext in (".xlsx", ".xlsm"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as e:
            err = str(e).lower()
            if "zip" in err or "not a zip" in err:
                raise ValueError(
                    f"Could not open '{os.path.basename(path)}' as an Excel workbook. "
                    "The file may be a CSV saved with a .xlsx extension, an old .xls format, "
                    "or corrupted. Fix: open in Excel → File → Save As → Excel Workbook (.xlsx), "
                    "then use that saved copy. Alternatively, use a .csv extension if the source is plain text."
                )
            raise ValueError(f"Could not open Excel file: {e}")
        ws = wb.active  # first sheet
        all_rows = [[("" if c is None else c) for c in row]
                    for row in ws.iter_rows(values_only=True)]
        wb.close()
        if not all_rows:
            return [], []
        return all_rows[0], all_rows[1:]
    else:
        raise ValueError(f"Unsupported source type '{ext}' (use .csv or .xlsx)")


def _post_output_files(s: Schedule):
    """
    Upload the schedule's output file(s) to SharePoint.
    `output_file_path` may contain multiple lines, one per file:
        <local path>[ -> <destination folder>]
    If a line omits "-> folder", the schedule-level `sharepoint_folder` is used.
    Mirrors services/runner._post_output_to_sharepoint so script and SharePoint
    schedules behave identically.
    Returns (status, paths, errors):
      - status: "success" (all uploaded), "partial" (some failed), or "failed" (none)
      - paths:  newline-separated list of successfully-posted SharePoint paths
      - errors: newline-separated list of "<source path>: <error>" for failures
    """
    from services.sharepoint_service import resolve_tokens

    raw_lines = [l.strip() for l in (s.output_file_path or "").splitlines() if l.strip()]
    if not raw_lines:
        return "failed", "", "No output file path configured"

    default_folder = resolve_tokens(s.sharepoint_folder or "/")
    succeeded, failed = [], []

    for line in raw_lines:
        raw_path    = line
        line_folder = None
        if "->" in line:
            raw_path, _, folder_part = line.partition("->")
            raw_path    = raw_path.strip()
            line_folder = folder_part.strip()

        folder = resolve_tokens(line_folder) if line_folder else default_folder

        try:
            src_path = resolve_tokens(raw_path)
            if not os.path.exists(src_path):
                raise FileNotFoundError(f"Output file not found: {src_path}")

            filename = os.path.basename(src_path)
            if getattr(s, "append_timestamp_to_filename", False):
                filename = append_timestamp(filename)

            with open(src_path, "rb") as f:
                file_bytes = f.read()

            post_file_to_sharepoint(s.sharepoint_site_id, folder, filename, file_bytes)
            succeeded.append(f"{folder.rstrip('/')}/{filename}")
        except Exception as e:
            log.error(f"[sp_runner] Upload failed for '{raw_path}': {e}")
            failed.append(f"{raw_path}: {e}")

    sp_paths  = "\n".join(succeeded)
    sp_errors = "\n".join(failed)

    if failed and succeeded:
        return "partial", sp_paths, sp_errors
    elif failed:
        return "failed", sp_paths, sp_errors
    else:
        return "success", sp_paths, sp_errors


def _get_file_bytes(s: Schedule) -> bytes:
    filename_pattern = getattr(s, "filename_pattern", None)
    source_folder    = getattr(s, "source_folder", None)
    source_path      = getattr(s, "source_path", None)

    # Pattern-match mode
    if filename_pattern and source_folder:
        return _find_file_by_date(s)

    # Exact path mode
    if not source_path:
        raise ValueError("No source configured — set source_folder + filename_pattern or source_path.")

    if source_path.startswith("sftp://"):
        from services.sharepoint_service import fetch_from_sftp
        return fetch_from_sftp(source_path)

    p = Path(source_path)
    if not p.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")
    return p.read_bytes()


def _find_file_by_date(s: Schedule) -> bytes:
    from services.sharepoint_service import resolve_tokens
    source_folder    = getattr(s, "source_folder", "")
    filename_pattern = getattr(s, "filename_pattern", "*")
    date_fmt_key     = getattr(s, "date_format", "YYYYMMDD") or "YYYYMMDD"
    target_period    = getattr(s, "target_period", "current") or "current"

    target_dt    = _resolve_target_date(s.recurrence, target_period)
    date_strings = _build_date_strings(target_dt, date_fmt_key)
    folder       = source_folder.rstrip("/\\")

    log.info(f"[sp_runner] Pattern scan: folder={folder} pattern={filename_pattern} dates={date_strings}")

    if folder.startswith("sftp://"):
        return _find_file_sftp(folder, filename_pattern, date_strings)

    folder_path = Path(folder)
    if not folder_path.exists():
        raise FileNotFoundError(f"Source folder not found: {folder}")

    candidates = [
        f for f in folder_path.iterdir()
        if f.is_file()
        and fnmatch.fnmatch(f.name, filename_pattern)
        and any(ds in f.name for ds in date_strings)
    ]
    if not candidates:
        raise FileNotFoundError(f"No file matching '{filename_pattern}' with date {date_strings[0]} in {folder}")
    if len(candidates) > 1:
        raise ValueError(f"Multiple files matched: {', '.join(f.name for f in candidates)}")

    log.info(f"[sp_runner] Matched: {candidates[0].name}")
    return candidates[0].read_bytes()


def _resolve_target_date(recurrence: str, target_period: str) -> date:
    from dateutil.relativedelta import relativedelta
    today = date.today()
    if target_period == "current":
        return today
    rec = (recurrence or "once").lower()
    if rec in ("once", "daily"):   return today - relativedelta(days=1)
    if rec == "weekly":            return today - relativedelta(weeks=1)
    if rec == "monthly":           return today.replace(day=1) - relativedelta(months=1)
    if rec == "quarterly":
        qs = today.month - ((today.month-1) % 3)
        return today.replace(month=qs, day=1) - relativedelta(months=3)
    return today


def _build_date_strings(target_dt: date, fmt_key: str) -> list:
    strfmt = DATE_FORMAT_MAP.get(fmt_key, fmt_key)
    base   = datetime(target_dt.year, target_dt.month, target_dt.day).strftime(strfmt)
    return list({base, base.upper(), base.lower(), base.title()})


def _find_file_sftp(sftp_folder: str, pattern: str, date_strings: list) -> bytes:
    try:
        import paramiko
    except ImportError:
        raise RuntimeError("paramiko required: pip install paramiko")
    no_proto = sftp_folder.replace("sftp://", "", 1)
    host, _, remote_folder = no_proto.partition("/")
    remote_folder = "/" + remote_folder
    transport = paramiko.Transport((host, 22))
    try:
        transport.connect()
        sftp    = paramiko.SFTPClient.from_transport(transport)
        matches = [f for f in sftp.listdir(remote_folder)
                   if fnmatch.fnmatch(f, pattern) and any(ds in f for ds in date_strings)]
        if not matches:
            raise FileNotFoundError(f"No SFTP file matching '{pattern}' with date {date_strings[0]}")
        if len(matches) > 1:
            raise ValueError(f"Multiple SFTP files matched: {', '.join(matches)}")
        with sftp.open(f"{remote_folder}/{matches[0]}", "rb") as f:
            return f.read()
    finally:
        transport.close()


def _start_log(db, s: Schedule, triggered_by: str) -> RunLog:
    """Create a run_logs row for a SharePoint run so it appears in Run History."""
    trigger = "schedule" if triggered_by in ("scheduler", "system") else "manual"
    triggered_by_name = ""
    try:
        if triggered_by and "@" in triggered_by:
            u = db.query(User).filter(User.email == triggered_by).first()
            triggered_by_name = u.name if u else triggered_by
        elif s.owner_id:
            owner = db.query(User).filter(User.id == s.owner_id).first()
            triggered_by_name = owner.name if owner else ""
    except Exception:
        pass
    log_row = RunLog(
        log_type="sharepoint",
        schedule_id=s.id,
        schedule_name=s.name or "",
        trigger=trigger,
        triggered_by=triggered_by,
        triggered_by_name=triggered_by_name,
        owner_id=s.owner_id,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    try:
        db.add(log_row); db.commit(); db.refresh(log_row)
    except Exception as e:
        log.error(f"[sp_runner] Could not create run log: {e}")
        db.rollback()
    return log_row


def _finish_log(db, run_log, status: str, output: str = "", error: str = "") -> None:
    """Finalize a run_logs row. Safe no-op if run_log is None."""
    if run_log is None:
        return
    try:
        finished = datetime.now(timezone.utc)
        elapsed  = 0
        try:
            if run_log.started_at:
                started = run_log.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                elapsed = int((finished - started).total_seconds() * 1000)
        except Exception:
            pass
        run_log.status      = status
        run_log.output      = (output or "")[:100000]
        run_log.error       = (error or "")[:50000]
        run_log.duration_ms = elapsed
        run_log.finished_at = finished
        db.commit()
    except Exception as e:
        log.error(f"[sp_runner] Could not finalize run log: {e}")
        db.rollback()


def _fail(db, s: Schedule, error: str, run_log=None) -> None:
    log.error(f"[sp_runner] Schedule {s.id} failed: {error}")
    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        s.last_run_utc = now; s.last_run_status = "failed"
        s.last_error   = error; s.status = "failed"
        db.commit()
    except Exception as e:
        log.error(f"[sp_runner] Could not persist failure: {e}")
    _finish_log(db, run_log, "failed", error=error)
    _send_notification(s, "failed", error=error)


def _send_notification(s: Schedule, status: str, web_url: str = "", error: str = "", mode: str = "replace") -> None:
    """Send upload success/failure notification email if notify_email_to is set."""
    notify_to = getattr(s, "notify_email_to", None) or ""
    if not notify_to:
        return
    try:
        from services.email_service import _send
        import html as _html
        notify_cc = getattr(s, "notify_cc_to", None) or ""
        to_list   = [e.strip() for e in notify_to.replace(";", ",").split(",") if e.strip()]
        cc_list   = [e.strip() for e in notify_cc.replace(";", ",").split(",") if e.strip()]

        icon  = "✅" if status == "success" else ("⚠️" if status == "partial" else "❌")
        label = "Success" if status == "success" else ("Partial" if status == "partial" else "Failed")
        color = "#059669" if status == "success" else ("#d97706" if status == "partial" else "#dc2626")

        safe_name = _html.escape(s.name or "")

        from services.email_service import build_sharepoint_block
        detail_block = ""
        if status == "success":
            if mode == "update_tab":
                detail_block = build_sharepoint_block(
                    sp_status="success", sp_mode="update_tab", sp_detail=str(web_url),
                )
            else:
                detail_block = build_sharepoint_block(
                    sp_status="success", sp_mode="replace", web_urls=str(web_url),
                )
        elif status == "partial":
            detail_block = build_sharepoint_block(
                sp_status="partial", sp_detail=str(web_url), sp_error=str(error),
            )
        elif status == "failed":
            detail_block = build_sharepoint_block(
                sp_status="failed", sp_error=str(error),
            )

        html = f"""
        <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:600px;margin:0 auto;">
          <div style="background:{color};padding:20px 24px;border-radius:10px 10px 0 0;">
            <h2 style="margin:0;color:#fff;font-size:17px;">{icon} SharePoint Upload {label}: {safe_name}</h2>
          </div>
          <div style="padding:20px 24px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 10px 10px;">
            <p style="margin:0 0 12px;font-size:14px;color:#374151;">
              The SharePoint upload schedule <b>{safe_name}</b> completed with status: <b style="color:{color};">{label}</b>.
            </p>
            {detail_block}
            <p style="margin:20px 0 0;font-size:12px;color:#9ca3af;border-top:1px solid #f3f4f6;padding-top:12px;">
              Sent automatically by MPM Conductor.
            </p>
          </div>
        </div>"""

        _send(
            to        = to_list,
            subject   = f"[MPM Conductor] {icon} SharePoint Upload {label} — {s.name}",
            html_body = html,
            cc        = cc_list,
        )
        log.info(f"[sp_runner] Notification sent to {to_list}")
    except Exception as e:
        log.error(f"[sp_runner] Failed to send notification email: {e}")


# ── Generic file → SharePoint post-delivery upload ────────────────────────────

def post_file_to_sharepoint(site_id: int, folder: str, filename: str, file_bytes: bytes) -> str:
    """
    Upload arbitrary bytes to a SharePoint site/folder.
    Returns the resulting webUrl. Raises on failure (caller decides how to
    handle/report — this function does NOT swallow exceptions).
    """
    db = SessionLocal()
    try:
        site = db.query(SharepointSite).filter(SharepointSite.id == site_id).first()
        if not site:
            raise RuntimeError(f"SharePoint site id={site_id} not found")

        from services.sharepoint_service import get_access_token, resolve_site_and_drive, resolve_drive_for_folder, resolve_tokens, upload_bytes
        token = get_access_token(site)
        graph_site_id, _ = resolve_site_and_drive(token, site.site_url)
        resolved_folder   = resolve_tokens(folder or "/")
        drive_id, upload_folder = resolve_drive_for_folder(token, graph_site_id, resolved_folder)

        result  = upload_bytes(token, drive_id, upload_folder, resolve_tokens(filename), file_bytes)
        web_url = result.get("webUrl", "")
        log.info(f"[sp_runner] Upload complete → {web_url}")
        return web_url
    finally:
        db.close()


# Backward-compat alias (old name, used by tableau_runner historically)
def post_tableau_pdf_to_sharepoint(site_id: int, folder: str, filename: str, pdf_bytes: bytes) -> str:
    return post_file_to_sharepoint(site_id, folder, filename, pdf_bytes)


# ── Filename helper ────────────────────────────────────────────────────────────

def append_timestamp(filename: str) -> str:
    """Insert _YYYYMMDD_HHMMSS before the file extension."""
    p = Path(filename)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if p.suffix:
        return f"{p.stem}_{ts}{p.suffix}"
    return f"{filename}_{ts}"
