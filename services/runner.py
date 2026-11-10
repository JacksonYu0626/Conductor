"""
Runs a Python script in a subprocess, captures stdout/stderr,
writes a RunLog row, and sends email notifications.

Uses Popen (not subprocess.run) so:
  - Long-running / non-stop scripts are supported
  - The process PID is stored in RunLog so it can be killed via the stop endpoint
  - On portal startup/shutdown, all stale 'running' logs are cleaned up
"""
import subprocess, sys, time, os, signal, threading
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from database import SessionLocal
from models import RunLog, Script, Schedule, User

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")

# In-memory map of { run_log_id: Popen } so stop_script() can find the process
_active_procs: dict[int, subprocess.Popen] = {}

# Per-script timeout limits (seconds). routers/scripts.py validates against these too.
DEFAULT_TIMEOUT_SEC = 3600        # 1 hour — used when a script has no timeout_sec
MIN_TIMEOUT_SEC     = 300         # 5 minutes
MAX_TIMEOUT_SEC     = 12 * 3600   # 12 hours


def _resolve_timeout(timeout_sec) -> int:
    """Return the effective timeout for a script, clamped to the allowed range."""
    if not timeout_sec:
        return DEFAULT_TIMEOUT_SEC
    return max(MIN_TIMEOUT_SEC, min(int(timeout_sec), MAX_TIMEOUT_SEC))


def _fmt_duration(seconds: int) -> str:
    """3600 -> '1 hour', 28800 -> '8 hours', 5400 -> '1h 30m'."""
    h, m = divmod(int(seconds) // 60, 60)
    if h == 0 and m == 0:
        return f"{int(seconds)} seconds"
    if m == 0:
        return f"{h} hour" + ("" if h == 1 else "s")
    return f"{h}h {m}m" if h else f"{m} minutes"


PROGRESS_FLUSH_SECONDS = 2  # how often partial output is saved while a script runs


# ── Explaining a failed exit ─────────────────────────────────────────────────
# A script that ends with a non-zero exit code but prints no error (for example
# Python crashing inside Excel/COM, or the script calling sys.exit(1)) used to
# leave the error column blank. These turn the exit code into a readable reason.
_WINDOWS_CRASH_CODES = {
    0xC0000005: "Python crashed (access violation). This is often caused by Excel/COM automation "
                "(win32com, xlwings) or a database/ODBC driver, typically while closing or saving.",
    0xC00000FD: "Python crashed (stack overflow), e.g. very deep recursion.",
    0xC0000409: "Python was stopped by a fatal error in a native library (fast-fail / stack buffer overrun).",
    0xC0000374: "Python crashed (heap corruption) inside a native library.",
    0xC0000017: "Python ran out of memory.",
    0xC000013A: "The script was interrupted (Ctrl+C / console closed).",
    0xE06D7363: "A C++ library used by the script threw an unhandled exception.",
}


def _exit_reason(code) -> str:
    """One readable line for a non-zero exit code."""
    if code is None:
        return "The script ended without an exit code."
    u = code & 0xFFFFFFFF
    if u in _WINDOWS_CRASH_CODES:
        return f"{_WINDOWS_CRASH_CODES[u]} (exit code {code} / 0x{u:08X})"
    if code == 1:
        return ("The script stopped itself with exit code 1 (for example sys.exit(1) or exit(\"...\")) "
                "without printing an error.")
    if code == 3:
        return "The script was aborted (exit code 3)."
    if u >= 0xC0000000:
        return f"Python crashed with Windows error 0x{u:08X} (exit code {code}) without printing an error."
    return f"The script ended with exit code {code} without printing an error."


def _failure_error(code, stderr: str) -> str:
    """
    Error text for a failed run. A normal Python error already has a traceback,
    so that's kept as is. Otherwise the exit code is explained, followed by any
    crash details Python's fault handler printed (which line it was on).
    """
    err = (stderr or "").strip()
    if "Traceback (most recent call last)" in err:
        return stderr
    reason = _exit_reason(code)
    if not err:
        if code is not None and (code & 0xFFFFFFFF) >= 0xC0000000:
            reason += ("\nIf the script's output file looks complete, the work likely finished and "
                       "the crash happened at the end (for example while closing Excel).")
        return reason
    # It did print something (e.g. crash details from the fault handler): show it under the reason
    return reason.replace(" without printing an error", "") + "\n\n" + stderr


def _combine_output(out: str, err: str) -> str:
    """stdout, plus stderr as a '--- log ---' section (same layout as finished runs)."""
    out = out or ""
    if err:
        out = out + ("\n\n--- log ---\n" if out else "") + err
    return out


def _communicate_streaming(proc: subprocess.Popen, timeout, on_progress=None):
    """
    Like proc.communicate(timeout=...), but reads stdout/stderr as they arrive
    so the partial output can be saved while the script is still running
    (used by the live "Test run" console in the UI).

    Returns (stdout, stderr, timed_out). On timeout the process is killed and
    whatever it printed so far is returned.
    """
    out_parts, err_parts = [], []

    def _reader(stream, sink):
        try:
            for line in iter(stream.readline, ""):
                sink.append(line)
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    threads = [
        threading.Thread(target=_reader, args=(proc.stdout, out_parts), daemon=True),
        threading.Thread(target=_reader, args=(proc.stderr, err_parts), daemon=True),
    ]
    for t in threads:
        t.start()

    started = time.time()
    deadline = (started + timeout) if timeout else None
    last_flushed = (0, 0)
    last_flush_at = 0.0
    timed_out = False

    def _flush_interval() -> float:
        # Save often at the start (when someone is usually watching a test
        # run), then less often so long or chatty jobs don't hammer the DB.
        running_for = time.time() - started
        if running_for < 120:
            return PROGRESS_FLUSH_SECONDS
        if running_for < 1800:
            return 10
        return 30

    while True:
        try:
            proc.wait(timeout=PROGRESS_FLUSH_SECONDS)
            break
        except subprocess.TimeoutExpired:
            pass
        if deadline is not None and time.time() >= deadline:
            timed_out = True
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=10)
            except Exception:
                pass
            break
        if on_progress is not None and time.time() - last_flush_at >= _flush_interval():
            sizes = (len(out_parts), len(err_parts))
            if sizes != last_flushed:
                last_flushed = sizes
                last_flush_at = time.time()
                try:
                    on_progress("".join(out_parts), "".join(err_parts))
                except Exception:
                    pass  # progress is best-effort; never break the run

    # Give the readers a moment to drain anything left in the pipes. A child
    # process that keeps the pipe open must not hang the runner forever.
    for t in threads:
        t.join(timeout=5)
    return "".join(out_parts), "".join(err_parts), timed_out


def run_script(script_id: int, trigger: str = "manual", triggered_by: str = "system",
               schedule_id: int = None):
    db: Session = SessionLocal()
    log_id = None
    try:
        script = db.query(Script).filter(Script.id == script_id).first()
        if not script:
            return

        script_dir   = os.path.join(SCRIPTS_DIR, *script.filename.split("/"))
        entry_point  = getattr(script, "entry_point", None) or "main.py"
        script_path  = os.path.join(script_dir, entry_point)
        os.makedirs(script_dir, exist_ok=True) 
        if not os.path.exists(script_path):
            _finish_log(db, script_id, trigger, triggered_by, "failed",
                        "", f"Entry point '{entry_point}' not found in folder: {script.filename}/", 0, schedule_id)
            return

        # Resolve and snapshot owner name so it survives script/schedule deletion
        triggered_by_name = ""
        owner_id_snap     = None
        if triggered_by and "@" in triggered_by:
            u = db.query(User).filter(User.email == triggered_by).first()
            triggered_by_name = u.name if u else triggered_by
            owner_id_snap     = u.id   if u else None
        elif triggered_by in ("scheduler", "system"):
            if schedule_id:
                sched = db.query(Schedule).filter(Schedule.id == schedule_id).first()
                if sched and sched.owner_id:
                    owner = db.query(User).filter(User.id == sched.owner_id).first()
                    triggered_by_name = owner.name if owner else ""
                    owner_id_snap     = sched.owner_id
            if not triggered_by_name and script.owner_id:
                owner = db.query(User).filter(User.id == script.owner_id).first()
                triggered_by_name = owner.name if owner else ""
                owner_id_snap     = script.owner_id

        # Resolve schedule name for the log
        _sched_name = ""
        if schedule_id:
            _sched = db.query(Schedule).filter(Schedule.id == schedule_id).first()
            _sched_name = _sched.name if _sched else ""
        if not _sched_name and script:
            _sched_name = script.name or ""

        log = RunLog(
            script_id=script_id,
            schedule_id=schedule_id,
            schedule_name=_sched_name,
            trigger=trigger,
            triggered_by=triggered_by,
            triggered_by_name=triggered_by_name,
            owner_id=owner_id_snap,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        log_id = log.id

        # Apps (long-running) have no timeout; scripts use their own
        # timeout_sec, falling back to 1 hour when it isn't set.
        is_app = getattr(script, "script_type", "script") == "app"
        timeout = None if is_app else _resolve_timeout(getattr(script, "timeout_sec", None))

        start = time.time()
        proc  = None
        try:
            proc = subprocess.Popen(
                # -X faulthandler: if Python itself crashes (e.g. inside Excel/COM),
                # it prints which line it was on to stderr instead of dying silently.
                [sys.executable, "-X", "faulthandler", script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=script_dir,
                # Unbuffered so print() output reaches the live console right
                # away instead of only when the script finishes.
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )

            # Store PID so the stop endpoint can terminate this process
            log.pid = proc.pid
            db.commit()

            _active_procs[log_id] = proc

            def _save_progress(out_so_far: str, err_so_far: str):
                # Only the output column is updated, so a concurrent manual
                # stop (which sets status) is never overwritten here.
                log.output = _combine_output(out_so_far, err_so_far)[:100000]
                db.commit()

            # Block until the process ends (or is killed via stop_script),
            # saving partial output every few seconds for the live console.
            stdout, stderr, timed_out = _communicate_streaming(proc, timeout, _save_progress)

            elapsed_ms = int((time.time() - start) * 1000)

            if timed_out:
                # Keep whatever the script printed before it was killed so the
                # log shows how far it got.
                status = "failed"
                output = _combine_output(stdout, stderr)
                error  = f"Script timed out after {_fmt_duration(timeout)}"
            # Negative returncode means the process was killed by a signal (our stop)
            elif proc.returncode is not None and proc.returncode < 0:
                status = "stopped"
                output = stdout or ""
                error  = "Process was manually stopped."
            else:
                status = "success" if proc.returncode == 0 else "failed"
                output = stdout or ""
                if status == "success":
                    # Many scripts use the `logging` module, which writes to stderr
                    # by default even for normal info/progress messages. On a
                    # successful run, treat stderr as supplementary output (a
                    # "log" section) rather than an error, so it doesn't show
                    # up in red "ERROR" boxes / trigger failure notifications.
                    if stderr:
                        output = (output + ("\n\n--- log ---\n" if output else "") + stderr)
                    error = ""
                else:
                    error  = _failure_error(proc.returncode, stderr)

        except Exception as e:
            elapsed_ms = int((time.time() - start) * 1000)
            status, output, error = "failed", "", str(e)

        finally:
            _active_procs.pop(log_id, None)

        # Re-fetch log in case it was updated externally (e.g. stop_script)
        db.refresh(log)
        if log.status != "stopped":  # don't overwrite a manual stop status
            log.status      = status
            log.output      = (output or "")[:100000]
            log.error       = (error or "")[:50000]
            log.duration_ms = elapsed_ms
            log.finished_at = datetime.now(timezone.utc)
            db.commit()

        # Update schedule last_run fields so the UI shows correct last run time
        if schedule_id:
            sched = db.query(Schedule).filter(Schedule.id == schedule_id).first()
            if sched:
                sched.last_run_utc    = log.started_at  # use start time, not finish time
                sched.last_run_status = log.status
                db.commit()

        # Post output file to SharePoint (script schedules only, on success)
        sp_status = ""
        sp_path   = ""
        sp_error  = ""
        sp_mode   = "replace"
        sp_site   = ""
        if schedule_id and log.status == "success":
            sched_for_sp = db.query(Schedule).filter(Schedule.id == schedule_id).first()
            if sched_for_sp and sched_for_sp.sharepoint_site_id and sched_for_sp.output_file_path:
                sp_mode = (getattr(sched_for_sp, "upload_mode", None) or "replace").lower()
                # Resolve the destination site display name so the email can show where files landed
                try:
                    from models import SharepointSite
                    _site = db.query(SharepointSite).filter(
                        SharepointSite.id == sched_for_sp.sharepoint_site_id
                    ).first()
                    sp_site = (_site.name or "") if _site else ""
                except Exception:
                    sp_site = ""
                if sp_mode == "update_tab":
                    sp_status, sp_path, sp_error = _update_tab_for_script(sched_for_sp)
                else:
                    sp_status, sp_path, sp_error = _post_output_to_sharepoint(sched_for_sp)

        # Email notification
        if schedule_id:
            _send_notifications(db, script, log, schedule_id, sp_status, sp_path, sp_error, sp_mode, sp_site)

    finally:
        db.close()


def _update_tab_for_script(sched: "Schedule"):
    """
    update_tab mode for a SCRIPT schedule: instead of replacing the whole file,
    write the script's output data into a named Excel Table inside an existing
    .xlsx on SharePoint, in place (preserves pivots, other sheets, formatting).

    Reuses the exact logic already used by SharePoint schedules
    (services.sharepoint_runner._update_tab), so the two code paths stay aligned.

    Requires on the schedule:
      - output_file_path: a line of the form  "<local source> -> <dest .xlsx path>"
      - target_table:     the named Excel Table (ListObject) to write into
      - sharepoint_site_id: the destination site

    Returns (status, path/summary, error) — same shape as _post_output_to_sharepoint.
    """
    from services.sharepoint_runner import _update_tab
    from models import SharepointSite

    db = SessionLocal()
    try:
        site = (
            db.query(SharepointSite)
            .filter(SharepointSite.id == sched.sharepoint_site_id)
            .first()
        )
        if not site:
            return "failed", "", f"SharePoint site {sched.sharepoint_site_id} not found"
        # _update_tab returns (status, summary, error)
        return _update_tab(sched, site)
    except Exception as e:
        return "failed", "", f"Tab update failed: {e}"
    finally:
        db.close()


def _post_output_to_sharepoint(sched: "Schedule"):
    """
    Upload the script's output file(s) to SharePoint.
    `output_file_path` may contain multiple lines, one per file:
        <local path>[ -> <destination folder>]
    If a line omits "-> folder", the schedule-level `sharepoint_folder` is used.
    Returns (status, path, error):
      - status: "success" (all uploaded), "partial" (some uploaded, some failed),
                or "failed" (none uploaded)
      - path: newline-separated list of successfully-posted SharePoint paths
      - error: newline-separated list of "<source path>: <error>" for failures
    """
    from services.sharepoint_runner import post_file_to_sharepoint, append_timestamp
    from services.sharepoint_service import resolve_tokens

    raw_lines = [l.strip() for l in (sched.output_file_path or "").splitlines() if l.strip()]
    if not raw_lines:
        return "failed", "", "No output file path configured"

    default_folder = resolve_tokens(sched.sharepoint_folder or "/")
    succeeded, failed = [], []

    for line in raw_lines:
        raw_path = line
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
            if sched.append_timestamp_to_filename:
                filename = append_timestamp(filename)

            with open(src_path, "rb") as f:
                file_bytes = f.read()

            post_file_to_sharepoint(sched.sharepoint_site_id, folder, filename, file_bytes)
            succeeded.append(f"{folder.rstrip('/')}/{filename}")
        except Exception as e:
            failed.append(f"{raw_path}: {e}")

    sp_path  = "\n".join(succeeded)
    sp_error = "\n".join(failed)

    if failed and succeeded:
        return "partial", sp_path, sp_error
    elif failed:
        return "failed", sp_path, sp_error
    else:
        return "success", sp_path, sp_error


def stop_script(log_id: int) -> bool:
    """
    Terminate the subprocess associated with run_log `log_id`.
    Returns True if a process was found and signalled, False otherwise.
    """
    proc = _active_procs.get(log_id)
    if proc is None:
        return False

    try:
        if sys.platform == "win32":
            proc.terminate()
        else:
            os.kill(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # already exited naturally

    # Mark the log stopped immediately so the UI reflects it
    db: Session = SessionLocal()
    try:
        log = db.query(RunLog).filter(RunLog.id == log_id).first()
        if log and log.status == "running":
            log.status      = "stopped"
            log.error       = "Process was manually stopped."
            log.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()

    return True


def cleanup_stale_runs():
    """
    Mark any RunLog rows stuck in 'running' or 'started' as 'failed'.
    'started' is the status written by older versions of runner.py before
    the process had a chance to update it — treat it the same as 'running'.
    Call this on portal startup AND shutdown to handle crash/kill scenarios.
    """
    db: Session = SessionLocal()
    try:
        stale = db.query(RunLog).filter(RunLog.status.in_(["running", "started"])).all()
        for log in stale:
            log.status      = "failed"
            log.error       = "Portal was shut down while this script was running."
            log.finished_at = log.finished_at or datetime.now(timezone.utc)
        if stale:
            db.commit()
            print(f"[Runner] Cleaned up {len(stale)} stale log(s) from previous session.")
    finally:
        db.close()


def _send_notifications(db: Session, script, log: RunLog, schedule_id: int,
                         sp_status: str = "", sp_path: str = "", sp_error: str = "",
                         sp_mode: str = "replace", sp_site: str = ""):
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        return
    send = (log.status == "success" and schedule.email_on_success) or \
           (log.status == "failed"  and schedule.email_on_failure)

    from services.email_service import send_run_notification

    if send and schedule.recipients:
        send_run_notification(
            recipients=schedule.recipients,
            script_name=script.name,
            status=log.status,
            duration_ms=log.duration_ms,
            output=log.output,
            error=log.error,
            started_at=log.started_at,
            sp_status=sp_status,
            sp_path=sp_path,
            sp_error=sp_error,
            sp_mode=sp_mode,
            sp_site=sp_site,
        )
        return

    # If no run notification would otherwise be sent, but SharePoint posting
    # failed, make sure the schedule owner still finds out.
    if sp_status in ("failed", "partial"):
        owner_email = ""
        if schedule.owner_id:
            owner = db.query(User).filter(User.id == schedule.owner_id).first()
            owner_email = (owner.email or "") if owner else ""
        if owner_email and owner_email not in (schedule.recipients or []):
            send_run_notification(
                recipients=[owner_email],
                script_name=script.name,
                status=log.status,
                duration_ms=log.duration_ms,
                output=log.output,
                error=log.error,
                started_at=log.started_at,
                sp_status=sp_status,
                sp_path=sp_path,
                sp_error=sp_error,
                sp_mode=sp_mode,
                sp_site=sp_site,
            )


def _finish_log(db, script_id, trigger, triggered_by, status, output, error, duration_ms, schedule_id):
    triggered_by_name = ""
    owner_id_snap     = None
    if triggered_by and "@" in triggered_by:
        u = db.query(User).filter(User.email == triggered_by).first()
        triggered_by_name = u.name if u else triggered_by
        owner_id_snap     = u.id   if u else None
    _sched_name2 = ""
    if schedule_id:
        _sched2 = db.query(Schedule).filter(Schedule.id == schedule_id).first()
        _sched_name2 = _sched2.name if _sched2 else ""
    if not _sched_name2:
        _sc2 = db.query(Script).filter(Script.id == script_id).first()
        _sched_name2 = _sc2.name if _sc2 else ""

    log = RunLog(
        script_id=script_id, schedule_id=schedule_id, schedule_name=_sched_name2,
        trigger=trigger, triggered_by=triggered_by,
        triggered_by_name=triggered_by_name, owner_id=owner_id_snap,
        status=status, output=output, error=error, duration_ms=duration_ms,
        started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
    )
    db.add(log); db.commit()