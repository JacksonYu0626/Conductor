"""
services/sharepoint_service.py — Microsoft Graph API helper for SharePoint uploads.

Adapted from post_to_sharepoint_v2.py (proven in production).

Public API:
    get_access_token(site)                                       → str
    resolve_site_and_drive(token, site_url)                      → (graph_site_id, drive_id)
    resolve_drive_for_folder(token, graph_site_id, folder)       → (drive_id, remaining_folder)
    upload_bytes(token, drive_id, folder, filename, file_bytes)  → dict
    upload_from_path(token, drive_id, folder, filename, path)    → dict
    fetch_from_sftp(sftp_url)                                    → bytes
    resolve_tokens(text)                                         → str
"""
import logging
import time
import tempfile
import os
# from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from datetime import datetime, date, time as _time
from decimal import Decimal

import requests

log = logging.getLogger(__name__)

GRAPH_ROOT  = "https://graph.microsoft.com/v1.0"
MAX_RETRIES = 5
CHUNK_SIZE  = 10 * 1024 * 1024   # 10 MB
SMALL_LIMIT = 3_500_000           # files <= 3.5 MB use simple PUT


# ── Token helpers ─────────────────────────────────────────────────────────────

def get_access_token(site) -> str:
    """
    Acquire a Graph API access token using client credentials flow.
    `site` is a SharepointSite ORM object (has tenant_id, client_id, client_secret).
    """
    url  = f"https://login.microsoftonline.com/{site.tenant_id}/oauth2/v2.0/token"
    data = {
        "client_id":     site.client_id,
        "client_secret": site.client_secret,
        "grant_type":    "client_credentials",
        "scope":         "https://graph.microsoft.com/.default",
    }
    r = requests.post(url, data=data, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Token request failed ({r.status_code}): {r.text}")
    log.info(f"[sharepoint] Token acquired for site '{site.name}'")
    return r.json()["access_token"]


# ── Site / drive resolution ───────────────────────────────────────────────────

def resolve_site_and_drive(token: str, site_url: str) -> Tuple[str, str]:
    """
    Given a SharePoint site URL, return (graph_site_id, drive_id).
    Prefers the 'Documents' library; falls back to the first available drive.
    Results can be cached on the SharepointSite.drive_id column to avoid
    repeated lookups.
    """
    # Normalize
    site_url = site_url.rstrip("/")
    no_proto = site_url.replace("https://", "", 1)
    host, _, path = no_proto.partition("/")
    site_path = "/" + path if path else ""

    # Resolve site ID
    r = _request_with_retry("GET", f"{GRAPH_ROOT}/sites/{host}:{site_path}", token)
    if r.status_code >= 300:
        raise RuntimeError(f"Resolve site failed ({r.status_code}): {r.text}")
    graph_site_id = r.json()["id"]

    # Resolve drive ID
    r = _request_with_retry("GET", f"{GRAPH_ROOT}/sites/{graph_site_id}/drives", token)
    if r.status_code >= 300:
        raise RuntimeError(f"List drives failed ({r.status_code}): {r.text}")
    drives = r.json().get("value", [])
    if not drives:
        raise RuntimeError("No document libraries found for this SharePoint site")

    drive_id = next(
        (d["id"] for d in drives if (d.get("name") or "").lower() == "documents"),
        drives[0]["id"],
    )
    log.info(f"[sharepoint] Resolved site_id={graph_site_id} drive_id={drive_id}")
    return graph_site_id, drive_id


def resolve_drive_for_folder(token: str, graph_site_id: str, folder: str) -> Tuple[str, str]:
    """
    Given a graph_site_id and a folder path, return (drive_id, remaining_folder).

    Matching is case-insensitive. "Shared Documents" is treated as an alias for
    the "Documents" library (Graph API names the drive "Documents" even though
    the SharePoint UI and URLs show "Shared Documents").

        /HR Files/Redetermination Reports  →  drive=HR Files,  folder=Redetermination Reports
        /Shared Documents/Some Folder      →  drive=Documents, folder=Some Folder
        /SHARED DOCUMENTS/Some Folder      →  drive=Documents, folder=Some Folder
        Redetermination Reports            →  drive=Documents (fallback), folder=Redetermination Reports

    Falls back to the "Documents" library (or first available drive) when no segment matches,
    preserving full backward compatibility for existing schedules that omit the library prefix.
    """
    r = _request_with_retry("GET", f"{GRAPH_ROOT}/sites/{graph_site_id}/drives", token)
    if r.status_code >= 300:
        raise RuntimeError(f"List drives failed ({r.status_code}): {r.text}")
    drives = r.json().get("value", [])
    if not drives:
        raise RuntimeError("No document libraries found for this SharePoint site")

    # Build a name → id lookup (lowercase keys for case-insensitive match)
    drive_map = {(d.get("name") or "").lower(): d["id"] for d in drives}

    # Default drive: prefer 'Documents', else first available
    default_drive_id = drive_map.get("documents") or drives[0]["id"]

    # Parse first segment of the folder path
    clean = folder.strip("/")
    parts = clean.split("/", 1)
    first_segment = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    # Normalize SharePoint URL alias → Graph API drive name
    # (SharePoint UI shows "Shared Documents" but Graph names the drive "Documents")
    if first_segment == "shared documents":
        first_segment = "documents"

    if first_segment and first_segment in drive_map:
        matched_drive_id = drive_map[first_segment]
        remaining_folder = rest
        log.info(f"[sharepoint] Library match '{parts[0]}' → drive_id={matched_drive_id}, folder='{remaining_folder}'")
        return matched_drive_id, remaining_folder

    # No match — use default drive, keep full folder path
    log.info(f"[sharepoint] No library match for '{parts[0]}', using default drive, folder='{clean}'")
    return default_drive_id, clean


# ── Token resolution ──────────────────────────────────────────────────────────

def resolve_tokens(text: str) -> str:
    """
    Replace date/period tokens in a path or filename string.

      {YYYY}    → 4-digit year   (e.g. 2026)
      {MM}      → 2-digit month  (e.g. 05)
      {DD}      → 2-digit day    (e.g. 19)
      {MON}     → Month name     (e.g. May)
      {QUARTER} → Quarter label  (e.g. Q2)
    """
    now = datetime.now()
    quarter = f"Q{(now.month - 1) // 3 + 1}"
    return (
        text
        .replace("{YYYY}",    now.strftime("%Y"))
        .replace("{MM}",      now.strftime("%m"))
        .replace("{DD}",      now.strftime("%d"))
        .replace("{MON}",     now.strftime("%B"))
        .replace("{QUARTER}", quarter)
    )


# ── SFTP fetch ────────────────────────────────────────────────────────────────

def fetch_from_sftp(sftp_url: str) -> bytes:
    """
    Download a file from an internal SFTP server (no credentials required).
    sftp_url format: sftp://hostname/path/to/file.pdf
    Returns file contents as bytes.
    """
    try:
        import paramiko
    except ImportError:
        raise RuntimeError("paramiko is required for SFTP support: pip install paramiko")

    # Parse sftp://hostname/path
    no_proto = sftp_url.replace("sftp://", "", 1)
    host, _, remote_path = no_proto.partition("/")
    remote_path = "/" + remote_path

    transport = paramiko.Transport((host, 22))
    try:
        transport.connect()   # no credentials — internal SFTP
        sftp = paramiko.SFTPClient.from_transport(transport)
        with sftp.open(remote_path, "rb") as f:
            data = f.read()
        log.info(f"[sharepoint] SFTP fetched {len(data):,} bytes from {sftp_url}")
        return data
    finally:
        transport.close()


# ── Upload helpers ────────────────────────────────────────────────────────────

def upload_bytes(
    token:      str,
    drive_id:   str,
    folder:     str,
    filename:   str,
    file_bytes: bytes,
) -> dict:
    """Upload raw bytes to SharePoint. Chooses small PUT vs chunked session automatically."""
    if len(file_bytes) <= SMALL_LIMIT:
        return _upload_small(token, drive_id, folder, filename, file_bytes)
    return _upload_large_bytes(token, drive_id, folder, filename, file_bytes)


def upload_from_path(
    token:    str,
    drive_id: str,
    folder:   str,
    filename: str,
    path:     str,
) -> dict:
    """Upload a local file to SharePoint by path."""
    file_bytes = Path(path).read_bytes()
    return upload_bytes(token, drive_id, folder, filename, file_bytes)


def _item_url(drive_id: str, folder: str, filename: str) -> str:
    folder   = folder.strip("/")
    rel_path = f"{folder}/{filename}" if folder else filename
    return f"{GRAPH_ROOT}/drives/{drive_id}/root:/{rel_path}"


def _upload_small(token: str, drive_id: str, folder: str, filename: str, data: bytes) -> dict:
    # Explicit replace keeps behavior identical to the large/chunked path
    # (which sets @microsoft.graph.conflictBehavior=replace on the session).
    url = _item_url(drive_id, folder, filename) + ":/content?@microsoft.graph.conflictBehavior=replace"
    r   = _request_with_retry(
        "PUT", url, token,
        headers={"Content-Type": "application/octet-stream"},
        data=data,
        timeout=300,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"Upload failed ({r.status_code}): {r.text}")
    log.info(f"[sharepoint] Small upload OK → {filename}")
    return r.json()


def _upload_large_bytes(token: str, drive_id: str, folder: str, filename: str, data: bytes) -> dict:
    """Write bytes to a temp file, use chunked upload session, then clean up."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        return _upload_large(token, drive_id, folder, filename, Path(tmp_path))
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _upload_large(token: str, drive_id: str, folder: str, filename: str, path: Path) -> dict:
    # Create upload session
    url  = _item_url(drive_id, folder, filename) + ":/createUploadSession"
    body = {"item": {"@microsoft.graph.conflictBehavior": "replace", "name": filename}}
    r    = _request_with_retry("POST", url, token, json_body=body, timeout=120)
    if r.status_code >= 300:
        raise RuntimeError(f"Create upload session failed ({r.status_code}): {r.text}")
    upload_url = r.json()["uploadUrl"]

    size  = path.stat().st_size
    start = 0
    with path.open("rb") as f:
        while start < size:
            end   = min(size - 1, start + CHUNK_SIZE - 1)
            chunk = f.read(end - start + 1)
            hdrs  = {
                "Content-Length": str(len(chunk)),
                "Content-Range":  f"bytes {start}-{end}/{size}",
            }
            for attempt in range(1, MAX_RETRIES + 1):
                cr = requests.put(upload_url, headers=hdrs, data=chunk, timeout=300)
                if cr.status_code in (423, 429, 500, 502, 503, 504):
                    time.sleep(min(60, 2 ** attempt))
                    continue
                break
            if cr.status_code in (200, 201):
                log.info(f"[sharepoint] Large upload complete → {filename}")
                return cr.json()
            if cr.status_code == 202:
                start = end + 1
                continue
            raise RuntimeError(f"Chunk upload failed ({cr.status_code}): {cr.text}")

    raise RuntimeError("Upload session ended without completion")


# ── Retry wrapper ─────────────────────────────────────────────────────────────

def resolve_item_id(token: str, drive_id: str, folder: str, filename: str) -> str:
    """Resolve the driveItem id for an existing file at folder/filename.

    Graph's root:/{path} syntax treats parentheses, apostrophes, and other
    special chars as OData operators unless each path segment is URL-encoded.
    We encode each segment individually (not the slashes) so paths like
    'LA Care FWA Audit-2026 (Kovel Privileged)/Summary.xlsx' resolve correctly.
    """
    from urllib.parse import quote
    parts = [p for p in [folder.strip("/"), filename] if p]
    # Encode each segment separately, preserving slashes as path separators.
    # safe='' encodes parentheses, apostrophes, spaces, hashes, etc.
    encoded = "/".join(quote(p, safe="") for p in "/".join(parts).split("/"))
    url = f"{GRAPH_ROOT}/drives/{drive_id}/root:/{encoded}"
    r = _request_with_retry("GET", url, token)
    if r.status_code == 404:
        raise RuntimeError(f"Destination workbook not found: /{'/'.join(parts)}")
    if r.status_code >= 300:
        raise RuntimeError(f"Could not resolve workbook ({r.status_code}): {r.text}")
    return r.json()["id"]

# Excel's date epoch is 1899-12-30 (accounts for the historical 1900 leap-year bug).
# Writing dates as serial numbers + a date numberFormat makes them REAL Excel dates:
# sortable, filterable, and usable by pivot tables — unlike text strings.
_EXCEL_EPOCH = datetime(1899, 12, 30)


def _to_excel_serial(v):
    """Convert a date/datetime to an Excel serial number (float days since epoch)."""
    if isinstance(v, datetime):
        delta = v - _EXCEL_EPOCH
    else:  # date
        delta = datetime(v.year, v.month, v.day) - _EXCEL_EPOCH
    return delta.days + delta.seconds / 86400.0


def _col_index_to_letter(idx: int) -> str:
    """0-based column index → Excel column letter (0→A, 25→Z, 26→AA)."""
    letters = ""
    idx += 1
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _shift_col_letter(start_letter: str, offset: int) -> str:
    """Return the column letter `offset` columns to the right of start_letter."""
    # convert start letter → 0-based index
    idx = 0
    for ch in start_letter.upper():
        idx = idx * 26 + (ord(ch) - 64)
    idx -= 1
    return _col_index_to_letter(idx + offset)


def _detect_date_columns(rows: list) -> dict:
    """
    Scan rows to find which column indices hold date/datetime values, and whether
    any value in that column carries a time component (→ datetime format).
    Returns {col_index: has_time_bool}. Robust to None/blank cells: a column is
    classified by the first non-None value seen, but time-detection scans all rows.
    """
    date_cols: dict = {}
    for row in rows:
        for ci, val in enumerate(row):
            if isinstance(val, (datetime, date)):
                has_time = isinstance(val, datetime) and bool(val.hour or val.minute or val.second)
                # once a column is known to contain a time, keep it
                date_cols[ci] = date_cols.get(ci, False) or has_time
    return date_cols


def _json_safe_cell(v):
    """Convert a single cell value to something Graph's workbook API accepts."""
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return _to_excel_serial(v)          # real Excel date (serial number)
    if isinstance(v, _time):
        return v.strftime("%H:%M:%S")       # bare times → text (no date anchor)
    if isinstance(v, Decimal):
        return float(v)
    return v


def _json_safe_rows(rows):
    return [[_json_safe_cell(c) for c in row] for row in rows]

def update_table_in_workbook(
    token: str,
    drive_id: str,
    item_id: str,
    table_name: str,
    rows: list,
    *,
    replace: bool = True,
    expected_headers: Optional[list] = None,
) -> dict:
    """
    Write data into a named Excel Table (ListObject) inside an .xlsx, in place,
    via the Graph workbook API. Preserves everything else in the workbook
    (pivot tables, other sheets, formatting).

    Strategy: use PATCH on the worksheet range directly rather than
    POST /tables/{name}/rows — the row-add API is unreliable when the table
    body is empty (reports success but data doesn't land visibly). The range
    PATCH is reliable, well-documented (v1.0), and writes directly to cells.

    Steps:
    1. Open a persistent workbook session.
    2. Validate headers (optional, protects pivot field names).
    3. Get the table's current address to find which worksheet and start column.
    4. Resize the table to exactly header + new data rows.
    5. PATCH the data body range with all new values (chunked by rows if large).
    6. Close the session.
    """
    base = f"{GRAPH_ROOT}/drives/{drive_id}/items/{item_id}/workbook"

    # 1) Open a workbook session
    sess = _request_with_retry(
        "POST", f"{base}/createSession", token,
        headers={"Content-Type": "application/json"},
        json_body={"persistChanges": True},
    )
    if sess.status_code >= 300:
        raise RuntimeError(f"Could not open workbook session ({sess.status_code}): {sess.text}")
    session_id = sess.json().get("id")
    sess_hdr   = {"workbook-session-id": session_id, "Content-Type": "application/json"} if session_id else {"Content-Type": "application/json"}

    try:
        # 2) Get table metadata (address + worksheet)
        tbl_r = _request_with_retry("GET", f"{base}/tables/{table_name}", token, headers=sess_hdr)
        if tbl_r.status_code >= 300:
            raise RuntimeError(f"Table '{table_name}' not found ({tbl_r.status_code}): {tbl_r.text}")
        tbl_data   = tbl_r.json()
        sheet_name = None

        # Resolve which worksheet hosts this table
        ws_r = _request_with_retry("GET", f"{base}/tables/{table_name}/worksheet", token, headers=sess_hdr)
        if ws_r.status_code < 300:
            sheet_name = ws_r.json().get("name")
        if not sheet_name:
            raise RuntimeError(f"Could not resolve worksheet for table '{table_name}'")

        # 3) Optional header validation
        if expected_headers:
            hr = _request_with_retry(
                "GET", f"{base}/tables/{table_name}/headerRowRange", token, headers=sess_hdr,
            )
            if hr.status_code < 300:
                actual = (hr.json().get("values") or [[]])[0]
                log.info(f"[sharepoint] Header check — source cols: {len(expected_headers)}, dest cols: {len(actual)}")
                if [str(h).strip() for h in actual] != [str(h).strip() for h in expected_headers]:
                    raise RuntimeError(
                        "Source columns do not match the destination Table headers. "
                        f"Destination: {actual} | Source: {expected_headers}. "
                        "Update the source to match, or the pivot's fields will break."
                    )

        # 4) Get the header row range to find start cell (e.g. A1)
        hdr_range_r = _request_with_retry(
            "GET", f"{base}/tables/{table_name}/headerRowRange", token, headers=sess_hdr,
        )
        if hdr_range_r.status_code >= 300:
            raise RuntimeError(f"Could not get header range ({hdr_range_r.status_code})")
        hdr_addr = hdr_range_r.json().get("address", "")
        # address is like "Sheet1!A1:P1" — extract sheet and start/end columns
        # strip sheet prefix
        if "!" in hdr_addr:
            hdr_addr = hdr_addr.split("!")[1]
        # hdr_addr is now like "A1:P1"
        start_cell = hdr_addr.split(":")[0]  # "A1"
        end_col    = hdr_addr.split(":")[1]  # "P1" → strip row to get col letter
        end_col_letter = "".join(c for c in end_col if c.isalpha())
        start_row  = int("".join(c for c in start_cell if c.isdigit()))  # 1
        data_start = start_row + 1  # row after header

        num_data_rows = len(rows)
        log.info(f"[sharepoint] Writing {num_data_rows} rows to '{sheet_name}'!{start_cell}:{end_col_letter}{data_start + num_data_rows - 1}")

        # 5) Clear the existing data body range before resizing.
        # This wipes stale values from previous runs so they don't accumulate
        # below the new data after the table is resized.
        clr = _request_with_retry(
            "POST", f"{base}/tables/{table_name}/dataBodyRange/clear",
            token, headers=sess_hdr,
            json_body={"applyTo": "Contents"},
        )
        if clr.status_code >= 300 and clr.status_code not in (400, 404):
            log.warning(f"[sharepoint] dataBodyRange/clear returned {clr.status_code} — continuing")
        else:
            log.info(f"[sharepoint] Cleared existing data body (status {clr.status_code})")

        # 6) Resize the table to header + new data rows
        # Build new table address e.g. A1:P1629
        new_end_row  = start_row + num_data_rows
        new_tbl_addr = f"{start_cell}:{end_col_letter}{new_end_row}"
        resize_r = _request_with_retry(
            "PATCH", f"{base}/tables/{table_name}",
            token, headers=sess_hdr,
            json_body={"name": table_name},  # keep name; resize via range below
        )
        # Resize via the table's range — update the range address
        resize2 = _request_with_retry(
            "POST", f"{base}/tables/{table_name}/resize",
            token, headers=sess_hdr,
            json_body={"newRange": {"address": f"'{sheet_name}'!{new_tbl_addr}"}},
        )
        if resize2.status_code >= 300:
            # resize API may not be available on all tenants — log and continue
            log.warning(f"[sharepoint] Table resize returned {resize2.status_code} — continuing with range PATCH anyway")

        # 6) Write data rows via PATCH on worksheet range (chunked)
        # Each PATCH covers a band of rows to stay within Graph's size limits.
        #
        # Detect date columns from the ORIGINAL rows (before serialization), so we
        # can apply a date numberFormat afterward — this keeps them as real,
        # sortable/filterable Excel dates that pivot tables can group on.
        start_col_letter = "".join(c for c in start_cell if c.isalpha())
        date_cols = _detect_date_columns(rows)

        CHUNK_ROWS = 200
        written = 0
        for i in range(0, num_data_rows, CHUNK_ROWS):
            # batch     = rows[i:i + CHUNK_ROWS]
            batch     = _json_safe_rows(rows[i:i + CHUNK_ROWS])
            row_start = data_start + i
            row_end   = row_start + len(batch) - 1
            patch_r = _request_with_retry(
                "PATCH",
                f"{base}/worksheets/{sheet_name}/range(address='{start_col_letter}{row_start}:{end_col_letter}{row_end}')",
                token, headers=sess_hdr,
                json_body={"values": batch},
            )
            if patch_r.status_code >= 300:
                raise RuntimeError(f"Range PATCH failed (chunk {i//CHUNK_ROWS+1}, rows {row_start}-{row_end}, status {patch_r.status_code}): {patch_r.text}")
            written += len(batch)
            log.info(f"[sharepoint] Patched rows {row_start}-{row_end} ({written}/{num_data_rows} total)")

        # 6b) Apply a date numberFormat to any detected date column(s) so the
        # serial numbers render as dates. numberFormat does NOT broadcast — it
        # must match the range shape, so we send one format string per data row.
        if date_cols and num_data_rows:
            for ci, has_time in date_cols.items():
                col_letter = _shift_col_letter(start_col_letter, ci)
                fmt        = "mm/dd/yyyy hh:mm:ss" if has_time else "mm/dd/yyyy"
                fmt_grid   = [[fmt] for _ in range(num_data_rows)]
                rng        = f"{col_letter}{data_start}:{col_letter}{data_start + num_data_rows - 1}"
                try:
                    fmt_r = _request_with_retry(
                        "PATCH",
                        f"{base}/worksheets/{sheet_name}/range(address='{rng}')",
                        token, headers=sess_hdr,
                        json_body={"numberFormat": fmt_grid},
                    )
                    if fmt_r.status_code >= 300:
                        log.warning(f"[sharepoint] Date format PATCH on {rng} returned "
                                    f"{fmt_r.status_code} — values written, display format unchanged")
                    else:
                        log.info(f"[sharepoint] Applied date format '{fmt}' to {rng}")
                except Exception as e:
                    # Formatting is cosmetic; never fail the whole upload over it.
                    log.warning(f"[sharepoint] Could not apply date format to {rng}: {e}")

        log.info(f"[sharepoint] Table '{table_name}' update complete: {written} rows written")
        return {"table": table_name, "rows_added": written, "replaced": replace}

    finally:
        try:
            _request_with_retry("POST", f"{base}/closeSession", token, headers=sess_hdr)
        except Exception as e:
            log.warning(f"[sharepoint] Could not close workbook session: {e}")


def _request_with_retry(
    method:    str,
    url:       str,
    token:     str,
    *,
    headers:   Optional[dict] = None,
    data:                      None = None,
    json_body: Optional[dict] = None,
    timeout:   int            = 120,
) -> requests.Response:
    hdrs = {"Authorization": f"Bearer {token}"}
    if headers:
        hdrs.update(headers)

    last_status = None
    last_body   = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.request(
                method, url,
                headers=hdrs, data=data, json=json_body, timeout=timeout,
            )
            # 423 Locked = destination file is open/checked out in SharePoint.
            # Transient (clears when the file is closed), so retry with backoff
            # alongside the standard throttling/server-error codes.
            if r.status_code in (423, 429, 500, 502, 503, 504):
                last_status = r.status_code
                last_body   = r.text[:300]
                if r.status_code == 423:
                    log.warning(f"[sharepoint] 423 Locked on {method} {url} — "
                                f"retry {attempt}/{MAX_RETRIES}; destination may be open in Excel")
                time.sleep(min(60, 2 ** attempt))
                continue
            return r
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(min(60, 2 ** attempt))
            log.warning(f"[sharepoint] Retry {attempt}/{MAX_RETRIES} for {method} {url}: {e}")

    detail = f" (last status {last_status}: {last_body})" if last_status else ""
    raise RuntimeError(f"Request failed after {MAX_RETRIES} retries: {method} {url}{detail}")