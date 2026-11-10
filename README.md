# MPM Conductor

Unified automation & reporting platform for MedPoint Management. Schedules Python scripts, delivers Tableau dashboard snapshots via email, and manages SharePoint file uploads — all from a single web interface.

---

## What it does

**Script scheduling** — Register Python scripts from the `scripts/` folder, run them on-demand or on recurring schedules (daily / weekly / monthly / quarterly / hourly), and receive email notifications on success or failure.

**Tableau snapshot delivery** — Register Tableau views, schedule automated PDF or PNG snapshot delivery via Microsoft Graph email, apply view filters and parameter overrides per schedule, and send ad-hoc snapshots directly from the UI.

**SharePoint uploads** — Schedule automated file uploads to SharePoint document libraries. Create and manage site connections from the SharePoint Sites page. SharePoint schedules share the same scheduling engine and run history as script and Tableau jobs.

**Unified dashboard** — One summary page with stat cards, a "Runs over time" chart (successful runs above the line, failed runs below it), runs by type, Needs attention and Up next. Filterable by type (Script / Tableau / SharePoint) with live auto-refresh. Click a stat card or a chart bar to jump to those runs in Run History.

**Welcome page** — After sign-in, a welcome page shows runs since yesterday, what's running now and what needs attention; each count opens the matching page.

**Schedule sharing** — The owner of a schedule can share it with teammates as **Can edit** (change settings, run, pause, stop, test-run its script) or **Can view** (see it, its run history and logs). People get an email when access is given, changed or removed, and newly shared schedules show a **New** tag until opened. Only the owner or an admin can delete a schedule or share it further.

**Feedback board** — Everyone sees all feedback. Upvote items and comments, comment on them, and edit or delete your own (shown as "· edited"). Admins set the status.

**Per-script time limits** — Each script has its own max run time (5 minutes – 12 hours, default 1 hour). Scripts still running past their limit are stopped and marked failed. Scripts registered as **App** have no limit.

**Live test runs** — **Test run** on the Scripts page opens a console that streams the script's output while it runs. Closing it keeps the run going; the header's **"N running"** indicator shows every running job with its progress against its max run time, plus Stop.

**Production checklist** — Registering a script shows a checklist of things that break on the server (drive letters, missing files, output inside the script folder). After upload, Conductor scans the files for drive-letter paths like `F:\` or `N:\` and lists the lines to fix.

---

## Requirements

- Python 3.10+
- Windows (required for script execution via subprocess)
- SQL Server: MPMEDW1 / Audittables / MPMC schema
- Tableau Server access with a Personal Access Token (PAT)

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in your values:

```dotenv
# ── App ───────────────────────────────────────────────────────
APP_SECRET_KEY=<long-random-string>
DEV_MODE=false

# ── Sign-in (Global Security) ─────────────────────────────────
GS_BASE_URL=https://gsmodule.medpointmanagement.com
GS_APP_ID=1045

# ── Database (SQL Server) ─────────────────────────────────────
CONDUCTOR_DB_SERVER=MPMEDW1
CONDUCTOR_DB_DATABASE=Audittables
CONDUCTOR_DB_SCHEMA=MPMC
CONDUCTOR_DB_DRIVER=ODBC Driver 17 for SQL Server

# ── Local testing only (leave these out on the server) ────────
# DEV_MODE=true                 # use a local SQLite file instead of SQL Server
# DB_PATH=C:\path\to\conductor.db
# SCHEDULER_ENABLED=false       # schedules don't fire while you test

# ── Tableau Server ────────────────────────────────────────────
TSC_SERVER_URL=https://mpmtableau.medpointmanagement.com
TSC_SITE_ID=
TSC_PAT_NAME=<your-pat-name>
TSC_PAT_SECRET=<your-pat-secret>
TSC_API_VERSION=3.19

# ── MSSQL (employee search in email picker) ───────────────────
MSSQL_SERVER=MPMEDW1
MSSQL_DATABASE=mpm_edw
MSSQL_DRIVER={ODBC Driver 17 for SQL Server}

# ── Email (Microsoft Graph API) ──────────────────────────────────────────────
EMAIL_TENANT_ID=<azure-tenant-id>
EMAIL_CLIENT_ID=<app-registration-client-id>
EMAIL_CLIENT_SECRET=<app-registration-client-secret>
EMAIL_SENDER=conductor@medpointmanagement.com

# ── SharePoint (Microsoft Graph API) ─────────────────────────────────────────
SHAREPOINT_TENANT_ID=<azure-tenant-id>
SHAREPOINT_CLIENT_ID=<app-registration-client-id>
SHAREPOINT_CLIENT_SECRET=<app-registration-client-secret>
```

| Variable | Description |
|---|---|
| `APP_SECRET_KEY` | Long random string for JWT signing |
| `DEV_MODE` | `true` = use a local SQLite database (`DB_PATH`) instead of SQL Server. Leave `false` on the server |
| `DB_PATH` | SQLite file used when `DEV_MODE=true` |
| `SCHEDULER_ENABLED` | Set `false` on a test PC so schedules don't fire (default `true`). **Never set on the server** |
| `GS_BASE_URL` | Global Security module URL used for Windows sign-in. A URL containing `test` turns on manual username sign-in for development |
| `GS_APP_ID` | Conductor's app ID in Global Security |
| `CONDUCTOR_DB_SERVER` | SQL Server hostname |
| `CONDUCTOR_DB_DATABASE` | Database containing MPMC schema tables |
| `CONDUCTOR_DB_SCHEMA` | Schema prefix (default: `MPMC`) |
| `CONDUCTOR_DB_DRIVER` | ODBC driver name |
| `TSC_SERVER_URL` | Your Tableau Server base URL |
| `TSC_SITE_ID` | Tableau site ID (leave blank for Default site) |
| `TSC_PAT_NAME` | Tableau Personal Access Token name |
| `TSC_PAT_SECRET` | Tableau Personal Access Token secret |
| `TSC_API_VERSION` | Tableau REST API version (default: `3.19`) |
| `MSSQL_SERVER` | SQL Server hostname for employee search |
| `MSSQL_DATABASE` | Database containing employee records |
| `MSSQL_DRIVER` | ODBC driver string |
| `EMAIL_TENANT_ID` | Azure AD tenant ID for Graph API email |
| `EMAIL_CLIENT_ID` | App registration client ID |
| `EMAIL_CLIENT_SECRET` | App registration client secret |
| `EMAIL_SENDER` | Shared mailbox address to send from |
| `SHAREPOINT_TENANT_ID` | Azure AD tenant ID for SharePoint uploads |
| `SHAREPOINT_CLIENT_ID` | App registration client ID for SharePoint |
| `SHAREPOINT_CLIENT_SECRET` | App registration client secret for SharePoint |
| `CONDUCTOR_SUMMARY_CACHE_SECONDS` | Optional. How long Summary numbers are cached (default `300`). The cache is cleared automatically whenever a run starts or finishes |
| `CONDUCTOR_ANALYTICS_CACHE_SECONDS` | Optional. Same, for chart data (default `300`) |
| `CONDUCTOR_URL` | Optional. Overrides the address used for the "Open in Conductor" button in sharing emails (default `https://conductor.medpointmanagement.com`, set in `routers/schedules.py`) |

### 3. Add scripts

Scripts are normally uploaded from the **Scripts → Register script** page (a `.py` file or a `.zip` of the project), which places them in `scripts/<UserName_emailprefix>/<ScriptFolder>/`. Each folder must contain an entry point file (default: `main.py`):

```
scripts/
  Jackson_Yu_jyu/
    OHC Automation/
      main.py
      config.py
      ...
```

Scripts run **on the server**, from their own folder:
- Use full network paths (`\\mpmfileserver01\...`), not drive letters (`F:\`, `N:\`, `M:\`) — including in `.env` files.
- Relative paths to files inside the uploaded zip work.
- Don't write output into the script folder; it is replaced on every upload.
- New network folders or databases may need access granted to the Conductor service account.

### 4. Run

```bash
python main.py
```

The app starts on `http://localhost:8000` and opens in your browser.

**Sign-in:** users sign in with their MPM Windows account through Global Security — the sign-in page detects the account and shows "Found: <name>". Users are added by IT in Global Security; there is no Add User page. Sign-in sessions last 72 hours and are tied to the user's email.

**Local testing (SQLite):** set `DEV_MODE=true`, `DB_PATH=...` and `SCHEDULER_ENABLED=false`. A fresh SQLite database gets a default admin (`admin@medpointmanagement.com`). If you switch a test PC between SQLite and SQL Server, sign out and back in.

**After deploying a new version:** restart the service, then press **Ctrl+F5** once in the browser.

---

## Project structure

```
Conductor/
├── main.py                   # FastAPI app entry point, app version (__version__), summary stats, DB migrations
├── CHANGELOG.md              # "What's new" list shown in the app (newest first)
├── models.py                 # SQLAlchemy models (User, Script, Dashboard, Schedule, RunLog, Feedback, FeedbackComment,
│                             #   FeedbackVote, FeedbackCommentVote, ScheduleShare, SharepointSite)
├── database.py               # DB init, session factory, connection pool config
├── schemas.py                # Pydantic request/response schemas
├── deps.py                   # JWT auth dependencies (get_current_user, is_admin); token must match the user's email
├── requirements.txt
├── .env
├── routers/
│   ├── auth.py               # Login, /me, GS config, dev_mode
│   ├── scripts.py            # Script CRUD, register/upload (timeout + drive-letter path scan), run, stop, pause schedules
│   ├── dashboards.py         # Dashboard CRUD, ad-hoc send, Tableau view search
│   ├── schedules.py          # Unified schedule CRUD for all types (script + Tableau + SharePoint), sharing + share emails
│   ├── logs.py               # Run history: server-side filters, paging (limit/offset), counts, weekday × hour heatmap,
│   │                         #   /logs/running for the header
│   ├── analytics.py          # Chart data (Pacific time, click-through date ranges, counts by type)
│   ├── users.py              # User list with item counts (everyone); edit/remove (admin only)
│   ├── feedback.py           # Feedback board: items, upvotes, comments, edit/delete own
│   └── sharepoint_sites.py   # SharePoint site registration, management, and per-site activity
├── services/
│   ├── scheduler.py          # APScheduler setup, job management, misfire handling (script/tableau/sharepoint)
│   ├── runner.py             # Python subprocess execution, per-script timeout, live output, stale run cleanup
│   ├── pacific_time.py       # UTC ↔ Pacific conversion with daylight saving (no tzdata needed)
│   ├── tableau_client.py     # Tableau REST API client (PAT auth, filter/param encoding)
│   ├── tableau_runner.py     # Tableau snapshot capture and email delivery
│   ├── email_service.py      # Microsoft Graph API email (client credentials flow); run and sharing emails
│   ├── sharing.py            # Who can do what with a schedule (owner / admin / edit / view)
│   ├── sharepoint_service.py # SharePoint Graph API helper (token, drive resolution, chunked upload, SFTP fetch)
│   ├── sharepoint_runner.py  # SharePoint upload execution, run logging
│   └── global_security.py    # Windows GS SSO auth (requests-negotiate-sspi)
├── scripts/                  # Drop per-user script folders here
│   └── <Name_emailprefix>/
│       └── <ScriptFolder>/
│           └── main.py
├── sql/                      # One-time scripts for SQL Server (all safe to re-run; already applied on prod)
│   ├── add_script_timeout.sql   # scripts.timeout_sec
│   ├── performance_indexes.sql  # indexes for run_logs and schedules
│   ├── add_collaboration.sql    # feedback comments/votes, schedule_shares, schedules.last_edited_*
│   └── add_feedback_edited.sql  # feedback.edited_at, feedback_comments.edited_at
└── static/
    ├── index.html            # Small loader: React, Babel, then the app files below (in order)
    ├── app/
    │   ├── styles.css        # Design tokens (light/dark), layout, components, animations
    │   ├── core.jsx          # API client, helpers, icons, shared building blocks
    │   ├── charts.jsx        # SVG charts: mirrored run bars, donut, sparkline, weekday × hour heatmap
    │   ├── forms.jsx         # All create/edit forms (scripts, dashboards, schedules, sites)
    │   ├── login.jsx         # Sign-in and welcome screens
    │   ├── layout.jsx        # Sidebar, header, running panel, Ctrl+K quick search
    │   ├── overview.jsx      # Summary, Run History (heatmap + pages), run log panel
    │   ├── library.jsx       # Scripts, Dashboards, SharePoint sites, live test-run console
    │   ├── schedules.jsx     # Schedules list, "last 12 / next 12 hours" strip, sharing (Share window, New tags)
    │   ├── workspace.jsx     # Users, Feedback board, My profile
    │   └── app.jsx           # App shell: session, theme, navigation
    └── fonts/                # Inter, Manrope, JetBrains Mono (bundled, no internet needed)
```

> **Note on schedules:** All three schedule types — `script`, `tableau`, and `sharepoint` — are managed through the single unified `schedules.py` router and stored in one `MPMC.schedules` table, discriminated by the `schedule_type` column. There is no separate SharePoint schedules router or table.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | FastAPI 0.111, SQLAlchemy 2.0, APScheduler 3.10 |
| Database | SQL Server (MPMEDW1 / Audittables / MPMC schema) |
| Frontend | React 18 + in-browser Babel (no build step), split into `static/app/*.jsx`; SVG charts (no chart library); bundled fonts |
| Authentication | JWT via python-jose, bcrypt via passlib, Windows GS SSO |
| Email | Microsoft Graph API via Azure AD service account (shared mailbox) |
| Tableau | tableauserverclient, REST API, PAT authentication |
| SharePoint | Microsoft Graph API via Azure AD app registration; SFTP source via paramiko |
| Employee search | pyodbc → MPMEDW1 / mpm_edw |

---

## Email

Uses **Microsoft Graph API** with a shared mailbox service account provisioned by IT — no Outlook desktop app required.

| Variable | Description |
|---|---|
| `EMAIL_TENANT_ID` | Azure AD tenant ID |
| `EMAIL_CLIENT_ID` | App registration client ID |
| `EMAIL_CLIENT_SECRET` | App registration client secret |
| `EMAIL_SENDER` | Shared mailbox address emails are sent from |

**How it works:** On each send, the service acquires a short-lived access token via the Azure AD client credentials flow, then calls `POST /users/{sender}/sendMail` on the Graph API. Sent items are saved to the shared mailbox. No desktop app, no COM, no Windows-specific dependencies for email.

**What gets sent:**

| Email | When |
|---|---|
| Run result | A script / Tableau / SharePoint run finishes (per the schedule's notification settings) |
| Shared with you (blue) | Someone shares a schedule with you — shows the schedule, next run and your access |
| Access changed (purple) | Your access changes between Can edit and Can view |
| Access removed (grey) | Your access is removed |

Sharing emails are sent after the change is saved, so a mail problem never blocks sharing (failures are logged as `[email_service] Failed to send share email`). Their **Open in Conductor** button links to `/?schedule=<id>`, which opens Schedules on that schedule (after sign-in if needed).

---

## SharePoint

SharePoint uploads use the **Microsoft Graph API** via an Azure AD app registration. Sites are registered on the SharePoint Sites page, and SharePoint schedules run on the same APScheduler engine as script and Tableau jobs, logging to the shared `run_logs` table.

| Variable | Description |
|---|---|
| `SHAREPOINT_TENANT_ID` | Azure AD tenant ID |
| `SHAREPOINT_CLIENT_ID` | App registration client ID |
| `SHAREPOINT_CLIENT_SECRET` | App registration client secret |

**How it works:** The runner acquires a Graph token via client credentials, resolves the target site and drive (path-based, since multiple document libraries can live at the same site level), then uploads — a simple `PUT` for files ≤ 3.5 MB or a chunked upload session for larger files. Upload sources can be local paths or an internal SFTP URL (`sftp://host/path`, fetched via paramiko).

**Drive naming:** The Graph API returns the default library drive name as `Documents` while the SharePoint UI displays `Shared Documents`. The service normalizes this alias when resolving folders.

**Site types:** **External** sites are fully supported. **Internal** sites (company SharePoint via Azure AD) require the app registration to be granted `Sites.Read.All` / `Sites.ReadWrite.All` application permissions with admin consent.

---

## Database

SQL Server on `MPMEDW1 / Audittables` using the `MPMC` schema. The following tables are managed by the app:

| Table | Purpose |
|---|---|
| `MPMC.users` | User accounts and roles |
| `MPMC.scripts` | Registered Python scripts (incl. `timeout_sec`, the per-script max run time) |
| `MPMC.dashboards` | Registered Tableau views |
| `MPMC.schedules` | All schedule configs (script + Tableau + SharePoint), discriminated by `schedule_type`; `last_edited_by_id` / `last_edited_at` record the last settings change |
| `MPMC.run_logs` | Full execution history — `started_at`/`finished_at` in UTC |
| `MPMC.feedback` | Feedback items (`edited_at` set when the author edits) |
| `MPMC.feedback_comments` | Comments on feedback (`edited_at` set when edited) |
| `MPMC.feedback_votes` | Upvotes on feedback — one per person per item |
| `MPMC.feedback_comment_votes` | Upvotes on comments — one per person per comment |
| `MPMC.schedule_shares` | Who a schedule is shared with (`access` = `edit` / `view`, `created_at`) |
| `MPMC.sharepoint_sites` | Registered SharePoint site connections |

**Time zones:** All timestamps are stored in **UTC** — `run_at_utc` / `last_run_utc` on schedules and `started_at` / `finished_at` in `run_logs`. The app shows everything in Pacific time, and charts and the Run History date filter both use Pacific calendar days (with daylight saving) so a chart bar and its runs always match. When querying `run_logs` in SSMS, subtract 7 hours (PDT) or 8 hours (PST).

**Connection pool:** Configured with `pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`, `pool_recycle=1800` to handle concurrent runs without cold-connection delays.

**DB migrations** run automatically on startup via `ALTER TABLE` statements — safe to run repeatedly. On SQL Server, new tables and columns are created by the scripts in `sql/` (run once by IT).

---

## Run History

Every filter — type, status, name search, date range and heatmap cell — runs on the server, so the counts on the status buttons are exact. Dates are Pacific calendar days.

**Pages:** the table loads one page at a time (25 / 50 / 100 rows per page, remembered per person), so every page is as quick as the first. Changing a filter goes back to page 1; Group by (day / month / year) groups the rows on the current page.

**"When runs happen" heatmap:** runs per weekday and hour (Pacific) for the last 4 weeks, or for the date range if one is set. It follows the type, name and status filters (All runs shows red badges for failures). Click a cell to show only those runs — a "Showing Mondays · 6–7 AM" chip appears; click it again, the ✕, or press **Esc** to clear.

**Run log panel:** click any row to open its log on the right. For a running job the output updates live, and the run can be stopped from there.

**Refresh:** Summary and Run History refresh on their own when a run finishes (Run History also every 30 seconds). The server's Summary/chart cache is cleared whenever a run starts or finishes, so new results show up right away.

---

## Filters & Parameters (Tableau schedules)

When creating a Tableau schedule, you can add filters and parameter overrides in the **Filters & Parameters** section:

| Key format | What it does | Example |
|---|---|---|
| `FieldName` | View filter (`vf_` prefix) — field must be on the Filter shelf | `Company ID` = `HCLA` |
| `:ParamName` | Tableau Parameter override — must match the parameter name exactly | `:Selected Date` = `2026-03-01` |

**Date values** support natural language in addition to absolute dates:

| Value | Resolves to |
|---|---|
| `today`, `yesterday` | Today / yesterday at run time |
| `last week` | Monday of last week |
| `this month`, `last month` | 1st of current / previous month |
| `this year`, `last year` | Jan 1 of current / previous year |
| `past N days` | Today minus N days |
| `past N weeks` | Today minus N weeks |
| `past N months` | 1st of the month N months ago |
| `past N years` | Jan 1 of N years ago |
| `2026-03-01` or `03/01/2026` | Exact fixed date (both formats accepted) |

---

## User roles

| Role | Access |
|---|---|
| `admin` | Full access — see and manage everyone's scripts, dashboards, schedules, SharePoint sites and runs; edit/remove users; pause another user's schedules; set feedback status |
| `user` | Own scripts, dashboards, SharePoint sites, schedules and runs, plus schedules shared with them; can send ad-hoc Tableau snapshots |

The **Users** page is visible to everyone but only shows names, roles and basic counts. Opening another person's items is admin-only, and the server enforces it (other users' runs and items return "not found").

**Shared schedules** are the one exception, and only for the schedule that was shared:

| Access | Can do |
|---|---|
| Owner / admin | Everything, including delete and sharing |
| Can edit | Change settings, run now, pause/resume, stop, see run history and logs, test-run the schedule's script. Can't delete, share, or swap the owner's script, dashboard or SharePoint site |
| Can view | See the schedule, its run history and logs |

When access is removed the schedule disappears from that person's Schedules page (within a minute if it's open), along with its runs — except runs they started themselves.

---

## Notes

- **Tableau PAT sessions** — Only one active PAT session is allowed at a time. All Tableau API calls are serialized via a module-level lock to prevent token invalidation between concurrent runs.
- **Schedules survive restarts** — APScheduler rebuilds all active schedules from the database on startup.
- **Script types** — Scripts can be `script` (subprocess, blocking, stopped at its max run time) or `app` (detached Popen, shows `started` status, no time limit).
- **Live output** — Running scripts are started unbuffered and their output is saved every few seconds (2s at first, then 10s, then 30s for long jobs), which powers the live test-run console and log panel.
- **GZip compression** — All API responses and static files are GZip compressed in transit.
- **Frontend** — `index.html` loads React 18 and `@babel/standalone`, then the files in `static/app/` in order (no build step). Script tags carry a `?v=` version so browsers pick up new copies. `index.html` itself is never cached by the browser.
- **Version and What's new** — Date-based version (`YYYY.MM.DD`, then `.2`, `.3` for later releases that day). Each release, set the same version in three places: `__version__` in `main.py`, `UI_VERSION` in `static/app/core.jsx` and every `?v=` in `static/index.html`, and add the release at the top of `CHANGELOG.md` (shown in the app under **What's new**). The page checks `/api/version` every 5 minutes: when the server runs a newer version, a card asks people to **Refresh**; when the page is newer (files replaced but the service not restarted), the sidebar says "Server on …: restart Conductor".
- **Design** — Light and dark mode (header toggle; default set on My profile, saved per browser), fixed sidebar and header, Ctrl+K quick search. Animations always play, even when Windows "Animation effects" is turned off.