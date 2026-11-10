"""
Conductor — unified data models.
Supports both Script jobs and Tableau Dashboard jobs in a single DB.
"""
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text,
    ForeignKey, JSON, Enum, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base, DB_SCHEMA
import enum


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": DB_SCHEMA} if DB_SCHEMA else {}

    id              = Column(Integer, primary_key=True, index=True)
    name            = Column(String(120), nullable=False)
    email           = Column(String(200), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role            = Column(String(30), default="user")   # admin | user | developer
    department      = Column(String(100), default="")
    title           = Column(String(100), default="")
    is_active        = Column(Boolean, default=True)
    notify_email     = Column(Boolean, default=True)
    sam_account_name = Column(String(100), default="")
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    feedbacks  = relationship("Feedback", back_populates="user")
    dashboards = relationship("Dashboard", back_populates="owner")


class Script(Base):
    __tablename__ = "scripts"
    __table_args__ = (
        Index("ix_scripts_owner_active", "owner_id", "is_active"),
        {"schema": DB_SCHEMA},
    ) if DB_SCHEMA else (
        Index("ix_scripts_owner_active", "owner_id", "is_active"),
    )

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(200), nullable=False)
    description = Column(Text, default="")
    category    = Column(String(100), default="General")
    filename    = Column(String(300), nullable=False, unique=True)  # user_folder/script_folder
    entry_point = Column(String(300), default="main.py")           # file to run inside folder
    script_type = Column(String(20), default="script")              # "script" | "app"
    timeout_sec = Column(Integer, nullable=True)                    # NULL = default (3600); ignored for apps
    owner_id    = Column(Integer, ForeignKey(f"{DB_SCHEMA}.users.id" if DB_SCHEMA else "users.id"), nullable=True)
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())

    owner     = relationship("User")
    schedules = relationship("Schedule", back_populates="script",
                             foreign_keys="Schedule.script_id",
                             cascade="all, delete-orphan")
    run_logs  = relationship("RunLog", back_populates="script",
                             foreign_keys="RunLog.script_id",
                             cascade="save-update, merge")  # no delete — preserve run history


class Dashboard(Base):
    """
    A registered Tableau view (or set of views) that can be run immediately
    or attached to a recurring schedule for automated email delivery.
    """
    __tablename__ = "dashboards"
    __table_args__ = (
        Index("ix_dashboards_owner_active", "owner_id", "is_active"),
        {"schema": DB_SCHEMA},
    ) if DB_SCHEMA else (
        Index("ix_dashboards_owner_active", "owner_id", "is_active"),
    )

    id                  = Column(Integer, primary_key=True, index=True)
    name                = Column(String(200), nullable=False)
    description         = Column(Text, default="")
    category            = Column(String(100), default="General")
    view_url            = Column(String(1000), nullable=False)   # primary Tableau URL
    additional_urls_json= Column(Text, default="[]")             # JSON list of extra view URLs
    filters_json        = Column(Text, default="{}")             # default filters JSON
    fmt                 = Column(String(10), default="pdf")      # pdf | png | csv
    owner_id            = Column(Integer, ForeignKey(f"{DB_SCHEMA}.users.id" if DB_SCHEMA else "users.id"), nullable=True)
    is_active           = Column(Boolean, default=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), onupdate=func.now())

    owner     = relationship("User", back_populates="dashboards")
    schedules = relationship("Schedule", back_populates="dashboard",
                             foreign_keys="Schedule.dashboard_id",
                             cascade="all, delete-orphan")


class SharepointSite(Base):
    """
    A registered SharePoint site.
    site_type = 'internal' → credentials loaded from .env at runtime
    site_type = 'external' → credentials stored per-site in DB
    """
    __tablename__ = "sharepoint_sites"
    __table_args__ = (
        Index("ix_sharepoint_sites_owner_active", "owner_id", "is_active"),
        {"schema": DB_SCHEMA},
    ) if DB_SCHEMA else (
        Index("ix_sharepoint_sites_owner_active", "owner_id", "is_active"),
    )

    id               = Column(Integer, primary_key=True, index=True)
    name             = Column(String(200), nullable=False)
    site_url         = Column(String(500), nullable=False)
    site_type        = Column(String(20),  nullable=False, default="internal")   # 'internal' | 'external'
    tenant_id        = Column(String(200), nullable=True)    # null for internal — loaded from .env
    client_id        = Column(String(200), nullable=True)    # null for internal — loaded from .env
    client_secret    = Column(String(500), nullable=True)    # null for internal — loaded from .env
    drive_id         = Column(String(200), nullable=True)
    is_active        = Column(Boolean, default=True)
    owner_id         = Column(Integer, ForeignKey(f"{DB_SCHEMA}.users.id" if DB_SCHEMA else "users.id"), nullable=True)
    created_by       = Column(String(128), default="")
    created_by_name  = Column(String(255), default="")
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now())

    owner             = relationship("User", foreign_keys=[owner_id])



class Schedule(Base):
    """
    Unified schedule for both Script and Tableau jobs.
    schedule_type = "script"  → script_id is set; uses frequency/run_time/days_of_week
    schedule_type = "tableau" → dashboard_id is set; uses recurrence/run_at_utc/timezone
    """
    __tablename__ = "schedules"
    __table_args__ = (
        Index("ix_schedules_owner_type", "owner_id", "schedule_type"),
        Index("ix_schedules_script_active", "script_id", "is_active"),
        Index("ix_schedules_dashboard_active", "dashboard_id", "is_active"),
        Index("ix_schedules_sp_site_active", "sharepoint_site_id", "is_active"),
        {"schema": DB_SCHEMA},
    ) if DB_SCHEMA else (
        Index("ix_schedules_owner_type", "owner_id", "schedule_type"),
        Index("ix_schedules_script_active", "script_id", "is_active"),
        Index("ix_schedules_dashboard_active", "dashboard_id", "is_active"),
        Index("ix_schedules_sp_site_active", "sharepoint_site_id", "is_active"),
    )

    id            = Column(Integer, primary_key=True, index=True)
    schedule_type = Column(String(20), nullable=False, default="script")  # "script" | "tableau"
    name          = Column(String(200), default="")  # human-readable label

    # ── Ownership ──────────────────────────────────────────────────────────
    owner_id      = Column(Integer, ForeignKey(f"{DB_SCHEMA}.users.id" if DB_SCHEMA else "users.id"), nullable=True)

    # ── Script-schedule fields ─────────────────────────────────────────────
    script_id        = Column(Integer, ForeignKey(f"{DB_SCHEMA}.scripts.id" if DB_SCHEMA else "scripts.id", ondelete="CASCADE"), nullable=True)
    frequency        = Column(String(20))          # daily|weekly|monthly|quarterly
    run_time         = Column(String(5))           # HH:MM
    days_of_week     = Column(JSON, default=list)  # ["Monday","Friday"] for weekly
    week_of_month    = Column(String(10), default="1st")
    start_date       = Column(DateTime, nullable=True)  # don't fire before this date

    # ── Tableau-schedule fields ────────────────────────────────────────────
    dashboard_id     = Column(Integer, ForeignKey(f"{DB_SCHEMA}.dashboards.id" if DB_SCHEMA else "dashboards.id", ondelete="CASCADE"), nullable=True)
    email_to         = Column(Text, default="")    # semicolon-separated recipients
    cc_to            = Column(Text, default="")
    fmt              = Column(String(10), default="pdf")
    view_urls_json   = Column(Text, default="[]")  # overrides dashboard.view_url if set
    filters_json     = Column(Text, default="{}")  # overrides dashboard.filters_json if set
    recurrence       = Column(String(20), default="once")  # once|daily|weekly|monthly|quarterly|hourly
    interval_hours   = Column(Integer, default=1)
    hourly_end_time  = Column(String(5), nullable=True)  # HH:MM — "to" time for hourly recurrence; days_of_week reused for "on these days"
    run_at_utc       = Column(DateTime, nullable=True)
    timezone         = Column(String(64), default="America/Los_Angeles")

    # ── Shared fields ──────────────────────────────────────────────────────
    is_active        = Column(Boolean, default=True)
    email_on_success = Column(Boolean, default=True)
    email_on_failure = Column(Boolean, default=True)
    recipients       = Column(JSON, default=list)  # for script schedules
    apscheduler_id   = Column(String(100), default="")
    status           = Column(String(50), default="scheduled")
    last_run_utc     = Column(DateTime, nullable=True)
    last_run_status  = Column(String(20), nullable=True)
    last_error       = Column(Text, nullable=True)
    created_by       = Column(String(128), default="")
    created_by_name  = Column(String(255), default="")
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now())
    # Who last changed the settings, and when (UTC). updated_at can't be used
    # for this because it also changes on every run.
    last_edited_by_id = Column(Integer, ForeignKey(f"{DB_SCHEMA}.users.id" if DB_SCHEMA else "users.id"), nullable=True)
    last_edited_at    = Column(DateTime, nullable=True)

    # ── SharePoint notification fields (schedule_type = 'sharepoint') ──────────
    # Who to notify on upload success/failure
    notify_email_to  = Column(Text, nullable=True)   # semicolon-separated
    notify_cc_to     = Column(Text, nullable=True)   # semicolon-separated

    # ── SharePoint add-on (Tableau schedules only) ─────────────────────────
    # When set, the Tableau runner also posts the PDF to SharePoint after email.
    # TODO: uncomment after IT runs sharepoint_tables.sql
    sharepoint_site_id = Column(Integer, ForeignKey(f"{DB_SCHEMA}.sharepoint_sites.id" if DB_SCHEMA else "sharepoint_sites.id"), nullable=True) 
    sharepoint_folder  = Column(String(500), nullable=True)              # destination folder; supports tokens

    # ── SharePoint add-on (script schedules) ───────────────────────────────
    # When set, the script runner posts the output file to SharePoint after a successful run.
    output_file_path             = Column(String(2000), nullable=True)  # local path(s) of file(s) produced by the script, one per line; supports tokens
    append_timestamp_to_filename = Column(Boolean, default=False)      # if true, insert _YYYYMMDD_HHMMSS before the extension

    # ── SharePoint standalone schedule fields (schedule_type = 'sharepoint') ─
    # These are only populated when schedule_type = 'sharepoint'.
    # source_folder + filename_pattern = pattern-match mode
    # source_path = exact path mode
    # TODO: uncomment after IT runs sharepoint_alter.sql
    source_folder        = Column(String(1000), nullable=True)
    filename_pattern     = Column(String(300),  nullable=True)
    date_format          = Column(String(50),   nullable=True)
    target_period        = Column(String(20),   default="current")
    destination_filename = Column(String(300),  nullable=True)

    # ── Upload mode (replace whole file vs. update a tab in an existing .xlsx) ─
    # "replace"     → upload bytes, overwrite the whole destination file (default; current behavior)
    # "update_tab"  → write data into a named Excel Table inside an existing .xlsx (preserves pivots)
    # TODO: uncomment after IT runs sharepoint_upload_mode_alter.sql
    upload_mode          = Column(String(20),   default="replace")
    target_sheet         = Column(String(200),  nullable=True)   # worksheet/tab name (informational/validation)
    target_table         = Column(String(200),  nullable=True)   # named Excel Table to write into (update_tab mode)

    owner           = relationship("User", foreign_keys=[owner_id])
    script          = relationship("Script", back_populates="schedules", foreign_keys=[script_id])
    dashboard       = relationship("Dashboard", back_populates="schedules", foreign_keys=[dashboard_id])
    sharepoint_site = relationship("SharepointSite", foreign_keys=[sharepoint_site_id])  # TODO: uncomment after IT runs sharepoint_tables.sql


class RunLog(Base):
    """
    Unified execution log for both Script runs and Tableau delivery runs.
    """
    __tablename__ = "run_logs"
    __table_args__ = (
        Index("ix_run_logs_started_at", "started_at"),
        Index("ix_run_logs_status_started", "status", "started_at"),
        Index("ix_run_logs_type_started", "log_type", "started_at"),
        Index("ix_run_logs_script_started", "script_id", "started_at"),
        Index("ix_run_logs_schedule_started", "schedule_id", "started_at"),
        Index("ix_run_logs_owner_started", "owner_id", "started_at"),
        {"schema": DB_SCHEMA},
    ) if DB_SCHEMA else (
        Index("ix_run_logs_started_at", "started_at"),
        Index("ix_run_logs_status_started", "status", "started_at"),
        Index("ix_run_logs_type_started", "log_type", "started_at"),
        Index("ix_run_logs_script_started", "script_id", "started_at"),
        Index("ix_run_logs_schedule_started", "schedule_id", "started_at"),
        Index("ix_run_logs_owner_started", "owner_id", "started_at"),
    )

    id           = Column(Integer, primary_key=True, index=True)
    log_type     = Column(String(20), default="script")   # "script" | "tableau"

    script_id    = Column(Integer, ForeignKey(f"{DB_SCHEMA}.scripts.id" if DB_SCHEMA else "scripts.id", ondelete="CASCADE"), nullable=True)
    schedule_id  = Column(Integer, ForeignKey(f"{DB_SCHEMA}.schedules.id" if DB_SCHEMA else "schedules.id", ondelete="SET NULL"), nullable=True)
    schedule_name = Column(String(255), default="")

    trigger           = Column("trigger_type", String(20), default="manual")
    triggered_by      = Column(String(200), default="system")
    triggered_by_name = Column(String(255), default="")   # snapshotted at run time
    owner_id          = Column(Integer, nullable=True)    # snapshotted at run time
    status            = Column(String(20), default="running")
    output       = Column(Text, default="")
    error        = Column(Text, default="")
    duration_ms  = Column(Integer, default=0)
    pid          = Column(Integer, nullable=True)
    started_at   = Column(DateTime(timezone=True), server_default=func.now())
    finished_at  = Column(DateTime(timezone=True), nullable=True)

    script = relationship("Script", back_populates="run_logs", foreign_keys=[script_id])


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = {"schema": DB_SCHEMA} if DB_SCHEMA else {}

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey(f"{DB_SCHEMA}.users.id" if DB_SCHEMA else "users.id"), nullable=True)
    type       = Column(String(50), default="Bug")
    message    = Column(Text, nullable=False)
    status     = Column(String(30), default="Open")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    edited_at  = Column(DateTime, nullable=True)   # last time the author changed it (UTC)

    user = relationship("User", back_populates="feedbacks")


# ── Public feedback: comments and upvotes ────────────────────────────────────
# Created on prod by sql/add_collaboration.sql. Times are stored in UTC.
def _utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)

_FK = (lambda t: f"{DB_SCHEMA}.{t}" if DB_SCHEMA else t)


class FeedbackComment(Base):
    __tablename__ = "feedback_comments"
    __table_args__ = {"schema": DB_SCHEMA} if DB_SCHEMA else {}

    id          = Column(Integer, primary_key=True, index=True)
    feedback_id = Column(Integer, ForeignKey(_FK("feedback.id"), ondelete="CASCADE"), nullable=False, index=True)
    user_id     = Column(Integer, ForeignKey(_FK("users.id")), nullable=False)
    message     = Column(Text, nullable=False)
    created_at  = Column(DateTime, default=_utcnow, nullable=False)
    edited_at   = Column(DateTime, nullable=True)   # last time the author changed it (UTC)

    user = relationship("User")


class FeedbackVote(Base):
    __tablename__ = "feedback_votes"
    __table_args__ = {"schema": DB_SCHEMA} if DB_SCHEMA else {}

    feedback_id = Column(Integer, ForeignKey(_FK("feedback.id"), ondelete="CASCADE"), primary_key=True)
    user_id     = Column(Integer, ForeignKey(_FK("users.id")), primary_key=True)
    created_at  = Column(DateTime, default=_utcnow, nullable=False)


class FeedbackCommentVote(Base):
    __tablename__ = "feedback_comment_votes"
    __table_args__ = {"schema": DB_SCHEMA} if DB_SCHEMA else {}

    comment_id  = Column(Integer, ForeignKey(_FK("feedback_comments.id"), ondelete="CASCADE"), primary_key=True)
    user_id     = Column(Integer, ForeignKey(_FK("users.id")), primary_key=True)
    created_at  = Column(DateTime, default=_utcnow, nullable=False)


# ── Schedule sharing ─────────────────────────────────────────────────────────
# A schedule's owner can share it with other people: access "edit" (change
# settings, run, pause, stop, test-run its script) or "view" (see it and its
# run history). No end date — a row stays until the owner removes it.
# Created on prod by sql/add_collaboration.sql.
class ScheduleShare(Base):
    __tablename__ = "schedule_shares"
    __table_args__ = {"schema": DB_SCHEMA} if DB_SCHEMA else {}

    id           = Column(Integer, primary_key=True, index=True)
    schedule_id  = Column(Integer, ForeignKey(_FK("schedules.id"), ondelete="CASCADE"), nullable=False, index=True)
    user_id      = Column(Integer, ForeignKey(_FK("users.id")), nullable=False, index=True)
    access       = Column(String(10), nullable=False, default="edit")
    shared_by_id = Column(Integer, ForeignKey(_FK("users.id")), nullable=False)
    created_at   = Column(DateTime, default=_utcnow, nullable=False)

    user = relationship("User", foreign_keys=[user_id])