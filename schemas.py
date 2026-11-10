from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


# ── Auth ──────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


# ── User ──────────────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: str = "user"
    department: str = ""
    title: str = ""

class UserUpdate(BaseModel):
    name: Optional[str] = None
    department: Optional[str] = None
    title: Optional[str] = None
    notify_email: Optional[bool] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None

class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    department: str
    title: str
    is_active: bool = True
    notify_email: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class UserListOut(UserOut):
    """A user plus how many items they own — the Users page list."""
    script_count: int = 0
    dashboard_count: int = 0
    sharepoint_site_count: int = 0
    schedule_count: int = 0
    feedback_count: int = 0


# ── Script ────────────────────────────────────────────────────────────────────
class ScriptCreate(BaseModel):
    name: str
    description: str = ""
    category: str = "General"
    filename: str
    entry_point: str = "main.py"
    script_type: str = "script"  # "script" | "app"
    timeout_sec: Optional[int] = None  # NULL = default 1 hour

class ScriptUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    entry_point: Optional[str] = None
    script_type: Optional[str] = None
    timeout_sec: Optional[int] = None  # send null to reset to the default
    is_active: Optional[bool] = None

class ScriptOut(BaseModel):
    id: int
    name: str
    description: str
    category: str
    filename: str
    entry_point: str = "main.py"
    is_active: bool
    script_type: str = "script"
    timeout_sec: Optional[int] = None
    owner: Optional[UserOut] = None
    created_at: datetime
    last_run: Optional[datetime] = None
    last_status: Optional[str] = None
    schedule_count: int = 0
    path_warnings: List[str] = []  # only filled on /scripts/register

    class Config:
        from_attributes = True


# ── Dashboard ─────────────────────────────────────────────────────────────────
class DashboardCreate(BaseModel):
    name: str
    description: str = ""
    category: str = "General"
    view_url: str
    additional_urls: List[str] = []
    filters: Dict[str, str] = {}
    fmt: str = "pdf"

class DashboardUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    view_url: Optional[str] = None
    additional_urls: Optional[List[str]] = None
    filters: Optional[Dict[str, str]] = None
    fmt: Optional[str] = None
    is_active: Optional[bool] = None

class DashboardRunNow(BaseModel):
    email_to: str
    cc_to: str = ""
    fmt: str = "pdf"
    filters: Dict[str, str] = {}

class DashboardOut(BaseModel):
    id: int
    name: str
    description: str
    category: str
    view_url: str
    additional_urls: List[str] = []
    filters: Dict[str, str] = {}
    fmt: str
    is_active: bool
    owner: Optional[UserOut] = None
    created_at: datetime
    last_run: Optional[datetime] = None
    last_status: Optional[str] = None
    schedule_count: int = 0

    class Config:
        from_attributes = True


# ── Schedule ──────────────────────────────────────────────────────────────────
class ScriptScheduleCreate(BaseModel):
    schedule_type: str = "script"
    script_id: int
    frequency: str                      # once|hourly|daily|weekly|monthly|quarterly
    run_time: str = ""                  # HH:MM (daily/weekly/monthly/quarterly)
    days_of_week: List[str] = []
    week_of_month: str = "1st"
    start_date: Optional[str] = None    # YYYY-MM-DD — don't fire before this date
    # once/hourly — aligned with Tableau schedule fields
    run_at_local: str = ""              # YYYY-MM-DDTHH:MM, for frequency="once"/"hourly"
    timezone: str = "America/Los_Angeles"
    interval_hours: int = 1             # for frequency="hourly"
    hourly_end_time: Optional[str] = None  # HH:MM "to" time for frequency="hourly"; days_of_week reused for "on these days"
    is_active: bool = True
    email_on_success: bool = True
    email_on_failure: bool = True
    recipients: List[str] = []
    # SharePoint add-on — optional; only set when "Also post output to SharePoint" toggle is on
    sharepoint_site_id: Optional[int] = None
    sharepoint_folder:  Optional[str] = None
    output_file_path:   Optional[str] = None
    append_timestamp_to_filename: bool = False
    # Upload mode — same options as SharePoint schedules:
    #   "replace"    → overwrite the whole destination file (default, current behavior)
    #   "update_tab" → write data into a named Excel Table in an existing .xlsx (preserves pivots)
    upload_mode:        Optional[str] = "replace"
    target_sheet:       Optional[str] = None   # worksheet/tab name (informational/validation)
    target_table:       Optional[str] = None   # named Excel Table to write into (update_tab mode)

class ScriptScheduleUpdate(ScriptScheduleCreate):
    pass

class TableauScheduleCreate(BaseModel):
    schedule_type: str = "tableau"
    name: str
    dashboard_id: Optional[int] = None
    email_to: str
    cc_to: str = ""
    fmt: str = "pdf"
    view_urls: List[str] = []
    filters: Dict[str, str] = {}
    recurrence: str = "once"
    interval_hours: int = 1
    hourly_end_time: Optional[str] = None  # HH:MM "to" time for recurrence="hourly"; days_of_week reused for "on these days"
    run_at_local: str = ""            # YYYY-MM-DDTHH:MM from datetime-local input
    timezone: str = "America/Los_Angeles"
    is_active: bool = True
    days_of_week: List[str] = []        # weekly: ["Monday","Tuesday",...]
    week_of_month: str = "1st"          # monthly/quarterly: "1st"|"2nd"|"3rd"|"4th"
    # SharePoint add-on — optional; only set when "Also post to SharePoint" toggle is on
    sharepoint_site_id: Optional[int] = None
    sharepoint_folder:  Optional[str] = None

class TableauScheduleUpdate(TableauScheduleCreate):
    pass

class ScheduleOut(BaseModel):
    id: int
    schedule_type: str
    name: str
    # script fields
    script_id: Optional[int] = None
    script_name: Optional[str] = None
    frequency: Optional[str] = None
    run_time: Optional[str] = None
    days_of_week: Optional[List[str]] = None
    week_of_month: Optional[str] = None
    start_date: Optional[datetime] = None
    # tableau fields
    dashboard_id: Optional[int] = None
    dashboard_name: Optional[str] = None
    email_to: Optional[str] = None
    cc_to: Optional[str] = None
    fmt: Optional[str] = None
    view_urls: Optional[List[str]] = None
    filters: Optional[Dict[str, str]] = None
    recurrence: Optional[str] = None
    run_at_utc: Optional[datetime] = None
    timezone: Optional[str] = None
    interval_hours: Optional[int] = None
    hourly_end_time: Optional[str] = None
    # shared
    is_active: bool = True
    email_on_success: bool = True
    email_on_failure: bool = True
    recipients: Optional[List[str]] = None
    owner: Optional[UserOut] = None
    status: Optional[str] = None
    last_run_utc: Optional[datetime] = None
    last_run_status: Optional[str] = None
    last_error: Optional[str] = None
    next_run_utc: Optional[datetime] = None
    created_at: datetime
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None
    # sharepoint
    sharepoint_site_id: Optional[int] = None
    sharepoint_folder:  Optional[str] = None
    output_file_path:   Optional[str] = None
    append_timestamp_to_filename: bool = False
    source_folder:      Optional[str] = None
    filename_pattern:   Optional[str] = None
    date_format:        Optional[str] = None
    target_period:      Optional[str] = None
    destination_filename: Optional[str] = None
    upload_mode:        Optional[str] = "replace"
    target_sheet:       Optional[str] = None
    target_table:       Optional[str] = None
    notify_email_to:    Optional[str] = None
    notify_cc_to:       Optional[str] = None
    sharepoint_site_name: Optional[str] = None
    # Sharing: my role on this schedule ("owner" | "admin" | "edit" | "view"),
    # how many people it's shared with, and who last changed its settings.
    my_access:           str = "owner"
    share_people:        List[Dict[str, Any]] = []   # [{name, access}] — owner/admin only
    shared_at:           Optional[datetime] = None   # when it was shared with the current user (shared schedules only)
    share_count:         int = 0
    last_edited_by_name: Optional[str] = None
    last_edited_at:      Optional[datetime] = None

    class Config:
        from_attributes = True


class ShareIn(BaseModel):
    user_id: int
    access: str = "edit"

class ShareAccessIn(BaseModel):
    access: str

class ShareOut(BaseModel):
    user_id: int
    name: str
    email: str
    access: str
    created_at: Optional[datetime] = None
    shared_by_name: Optional[str] = None


# ── RunLog ────────────────────────────────────────────────────────────────────
class RunLogOut(BaseModel):
    id: int
    log_type: str = "script"
    script_id: Optional[int] = None
    script_name: Optional[str] = None
    schedule_id: Optional[int] = None
    schedule_name: Optional[str] = None
    trigger: str = ""
    triggered_by: str = ""
    triggered_by_name: str = ""
    status: str = ""
    output: str = ""
    error: str = ""
    duration_ms: int = 0
    started_at: datetime
    finished_at: Optional[datetime] = None
    email_to: Optional[str] = None
    cc_to: Optional[str] = None
    recipients: Optional[list] = None
    notify_email_to: Optional[str] = None
    notify_cc_to: Optional[str] = None
    sp_site_name: Optional[str] = None
    sp_folder: Optional[str] = None

    class Config:
        from_attributes = True


# ── Feedback ──────────────────────────────────────────────────────────────────
class FeedbackCreate(BaseModel):
    type: str = "Bug"
    message: str

class FeedbackUpdate(BaseModel):
    status: str

class FeedbackOut(BaseModel):
    id: int
    type: str
    message: str
    status: str
    user: Optional[UserOut] = None
    created_at: datetime
    edited_at: Optional[datetime] = None
    vote_count: int = 0
    voted: bool = False          # the current user has upvoted it
    comment_count: int = 0

    class Config:
        from_attributes = True


class CommentCreate(BaseModel):
    message: str

class FeedbackEdit(BaseModel):
    type: str
    message: str

class CommentOut(BaseModel):
    id: int
    feedback_id: int
    message: str
    created_at: datetime
    edited_at: Optional[datetime] = None
    user: Optional[UserOut] = None
    vote_count: int = 0
    voted: bool = False

    class Config:
        from_attributes = True


class VoteOut(BaseModel):
    vote_count: int
    voted: bool


# ── User search ───────────────────────────────────────────────────────────────
class TMUser(BaseModel):
    fullname: str
    title: str
    department: str
    email: str


TokenResponse.model_rebuild()


# ── SharepointSite ────────────────────────────────────────────────────────────
class SharepointSiteCreate(BaseModel):
    name:          str
    site_url:      str
    site_type:     str           = "internal"   # 'internal' | 'external'
    # Required only for external sites; internal sites use .env credentials
    tenant_id:     Optional[str] = None
    client_id:     Optional[str] = None
    client_secret: Optional[str] = None
    drive_id:      Optional[str] = None

class SharepointSiteUpdate(BaseModel):
    name:          Optional[str]  = None
    site_url:      Optional[str]  = None
    site_type:     Optional[str]  = None
    tenant_id:     Optional[str]  = None
    client_id:     Optional[str]  = None
    client_secret: Optional[str]  = None   # omit to keep existing secret
    drive_id:      Optional[str]  = None
    is_active:     Optional[bool] = None

class SharepointSiteOut(BaseModel):
    id:              int
    name:            str
    site_url:        str
    site_type:       str                = "internal"
    tenant_id:       Optional[str]      = None
    client_id:       Optional[str]      = None
    # client_secret intentionally excluded from API output
    drive_id:        Optional[str]      = None
    is_active:       bool
    owner:           Optional[UserOut]  = None
    created_by_name: str                = ""
    created_at:      datetime
    schedule_count:  int                = 0

    class Config:
        from_attributes = True


# ── SharePoint schedule (stored in schedules table, schedule_type='sharepoint') ──
class SharepointScheduleCreate(BaseModel):
    name:                          str
    schedule_type:                 str           = "sharepoint"
    sharepoint_site_id:            int
    sharepoint_folder:             str           = "/"
    destination_filename:          Optional[str] = None
    output_file_path:              Optional[str] = None
    append_timestamp_to_filename:  bool          = False
    source_path:                   Optional[str] = None
    source_folder:                 Optional[str] = None
    filename_pattern:              Optional[str] = None
    date_format:                   Optional[str] = None
    target_period:                 str           = "current"
    notify_email_to:               Optional[str] = None
    notify_cc_to:                  Optional[str] = None
    email_on_success:              bool          = True
    email_on_failure:              bool          = True
    recurrence:                    str           = "once"
    run_at_local:                  str           = ""
    timezone:                      str           = "America/Los_Angeles"
    days_of_week:                  Optional[str] = None
    week_of_month:                 Optional[str] = None
    interval_hours:                int           = 1
    hourly_end_time:               Optional[str] = None
    upload_mode:                   str           = "replace"
    target_sheet:                  Optional[str] = None
    target_table:                  Optional[str] = None
    is_active:                     bool          = True

class SharepointScheduleUpdate(SharepointScheduleCreate):
    pass