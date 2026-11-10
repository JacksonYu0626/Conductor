# services/tableau_client.py
"""
Tableau REST API client — ported from MPM Snapshot Scheduler.
Uses environment variables directly (no Flask Config dependency).
"""
import os
import threading
from typing import Optional, Dict, List
from urllib.parse import urlparse, unquote, quote, quote_plus
from datetime import datetime, date, timedelta

from requests.exceptions import HTTPError

# ── PAT session lock ────────────────────────────────────────────────────────
# Tableau Personal Access Tokens allow only ONE active session per token.
# If two callers (e.g. the scheduler and a manual search) try to use the same
# PAT concurrently, one invalidates the other's token and operations fail
# mid-flight. This module-level lock serializes every Tableau API call across
# the whole process.
_PAT_LOCK = threading.Lock()


def get_pat_lock() -> threading.Lock:
    """Return the shared PAT lock (for callers that need to wrap batch work)."""
    return _PAT_LOCK

# Tableau config from env
def _cfg(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _parse_date_any(s: str) -> Optional[date]:
    """
    Parse a flexible date string into a Python date object, evaluated at call time.

    Supported formats:
      Absolute : "2026-03-01", "03/01/2026", "2026-03", "2026"
      Keywords : "today", "yesterday", "last week", "this month", "last month",
                 "this year", "last year"
      Relative : "past N days", "past N weeks", "past N months", "past N years"
                 (N = any positive integer, e.g. "past 6 months", "past 13 months")
    """
    import re
    if not s:
        return None

    today = date.today()
    t = s.strip().lower()

    # ── keywords ──────────────────────────────────────────────────────────
    if t in ("_latest_", "today"):
        return today
    if t == "yesterday":
        return today - timedelta(days=1)
    if t == "last week":
        # Monday of last week
        return today - timedelta(days=today.weekday() + 7)
    if t == "this month":
        return today.replace(day=1)
    if t == "last month":
        first_this = today.replace(day=1)
        return (first_this - timedelta(days=1)).replace(day=1)
    if t == "this year":
        return today.replace(month=1, day=1)
    if t == "last year":
        return today.replace(year=today.year - 1, month=1, day=1)

    # ── relative: "past N days/weeks/months/years" ────────────────────────
    m = re.match(r"past\s+(\d+)\s+(day|days|week|weeks|month|months|year|years)$", t)
    if m:
        n    = int(m.group(1))
        unit = m.group(2).rstrip("s")   # normalise to singular
        if unit == "day":
            return today - timedelta(days=n)
        if unit == "week":
            return today - timedelta(weeks=n)
        if unit == "month":
            target_month = (today.month - 1 - n) % 12 + 1
            target_year  = today.year + ((today.month - 1 - n) // 12)
            return date(target_year, target_month, 1)
        if unit == "year":
            return today.replace(year=today.year - n, month=1, day=1)

    # ── absolute formats ──────────────────────────────────────────────────
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except Exception:
            pass
    try:
        dt = datetime.strptime(s.strip(), "%Y-%m")
        return date(dt.year, dt.month, 1)
    except Exception:
        pass
    try:
        dt = datetime.strptime(s.strip(), "%Y")
        return date(dt.year, 1, 1)
    except Exception:
        pass
    return None


def _daterange_as_list(d1: date, d2: date, max_days: int = 62) -> List[str]:
    if d2 < d1:
        d1, d2 = d2, d1
    days = (d2 - d1).days + 1
    if days > max_days:
        raise ValueError(f"Date range too large ({days} days). Keep it under ~{max_days} days.")
    out, cur = [], d1
    while cur <= d2:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


class TableauClient:
    """
    Export Tableau views via tableau_api_lib (REST) with URL-style filters.
    Requires env vars: TSC_SERVER_URL, TSC_SITE_ID, TSC_PAT_NAME, TSC_PAT_SECRET
    """

    def __init__(self) -> None:
        self.server_url  = _cfg("TSC_SERVER_URL").rstrip("/")
        self.site_url    = _cfg("TSC_SITE_ID")
        self.api_version = _cfg("TSC_API_VERSION", "3.19")
        self.pat_name    = _cfg("TSC_PAT_NAME")
        self.pat_secret  = _cfg("TSC_PAT_SECRET")

        if not (self.server_url and self.pat_name and self.pat_secret):
            raise RuntimeError(
                "Tableau config incomplete. Set TSC_SERVER_URL, TSC_PAT_NAME, TSC_PAT_SECRET in .env"
            )

        self._conn        = None
        self._auth_token  = None
        self._site_id     = None

    # ── connection ─────────────────────────────────────────────────────────
    def _get_conn(self):
        if self._conn is not None:
            return self._conn
        from tableau_api_lib import TableauServerConnection
        import time

        cfg = {
            "env": {
                "server": self.server_url,
                "api_version": self.api_version,
                "site_name": self.site_url or "",
                "site_url":  self.site_url or "",
                "personal_access_token_name":   self.pat_name,
                "personal_access_token_secret": self.pat_secret,
            }
        }

        max_attempts = 3
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                conn = TableauServerConnection(config_json=cfg, env="env")
                resp = conn.sign_in()
                try:
                    creds            = resp.json().get("credentials", {})
                    self._auth_token = creds.get("token") or ""
                    self._site_id    = (creds.get("site") or {}).get("id") or ""
                except Exception as e:
                    print(f"[TableauClient] Could not parse sign_in response: {e}")
                    self._auth_token = ""
                    self._site_id    = ""

                if not self._auth_token:
                    raise RuntimeError(
                        f"Tableau sign-in returned no token. "
                        f"Response: {resp.text[:300]}"
                    )

                self._conn = conn
                if attempt > 1:
                    print(f"[TableauClient] Sign-in succeeded on attempt {attempt}")
                return conn

            except Exception as e:
                last_error = e
                print(f"[TableauClient] Sign-in attempt {attempt}/{max_attempts} failed: {e}")
                if attempt < max_attempts:
                    time.sleep(2 * attempt)  # 2s, then 4s

        raise RuntimeError(
            f"Tableau sign-in failed after {max_attempts} attempts. "
            f"Last error: {last_error}"
        )

    def _close_conn(self) -> None:
        if self._conn is not None:
            try:
                self._conn.sign_out()
            except Exception:
                pass
            self._conn = None

    # ── URL parsing ────────────────────────────────────────────────────────
    @staticmethod
    def _extract_content_url(view_url: str) -> str:
        s = (view_url or "").strip()
        if not s:
            return s
        if s.startswith("http://") or s.startswith("https://"):
            parts = urlparse(s)
            raw = parts.fragment or parts.path
            idx = raw.find("/views/")
            tail = raw[idx + len("/views/"):] if idx >= 0 else raw.lstrip("/")
            if "?" in tail:
                tail = tail.split("?", 1)[0]
            segs = [seg for seg in unquote(tail).split("/") if seg and seg.lower() != "sheets"]
            base = segs[:2] if len(segs) >= 2 else segs
            return "/".join(base).strip("/")
        return s.strip("/")

    @staticmethod
    def _variants(content_url: str) -> List[str]:
        cu = content_url.strip("/")
        out = [cu]
        if "/" in cu:
            wb, v = cu.rsplit("/", 1)
            # e.g. WorkbookName/ViewName → also try WorkbookName/sheets/ViewName
            out.append(f"{wb}/sheets/{v}")
        else:
            # Only workbook name provided (no view segment) — Tableau contentUrl is
            # typically WorkbookName/sheets/ViewName. When the view shares the same
            # name as the workbook, generate that variant automatically.
            out.append(f"{cu}/sheets/{cu}")
            # Also try without the /sheets/ middle segment (some older views)
            out.append(f"{cu}/{cu}")
        seen, uniq = set(), []
        for x in out:
            k = x.lower()
            if k not in seen:
                seen.add(k)
                uniq.append(x)
        return uniq

    # ── view lookup ────────────────────────────────────────────────────────
    def _resolve_view_id(self, conn, content_or_name: str) -> str:
        from tableau_api_lib.utils.querying import get_views_dataframe
        content  = self._extract_content_url(content_or_name)
        views_df = get_views_dataframe(conn)
        for cand in self._variants(content):
            hit = views_df[views_df["contentUrl"].str.lower() == cand.lower()]
            if not hit.empty:
                return hit.iloc[0]["id"]
        name = content.rsplit("/", 1)[-1]
        hits = views_df[views_df["name"] == name]
        if not hits.empty:
            return hits.iloc[0]["id"]
        raise RuntimeError(
            f"View not found for '{content_or_name}'. Check contentUrl spelling/casing."
        )

    # ── search views (for Dashboard registration) ──────────────────────────
    def search_views(self, query: str = "") -> List[dict]:
        """Return list of {name, contentUrl, workbookName} matching query."""
        from tableau_api_lib.utils.querying import get_views_dataframe
        with _PAT_LOCK:
            try:
                conn = self._get_conn()
                df = get_views_dataframe(conn)
                if query:
                    mask = (
                        df["name"].str.lower().str.contains(query.lower(), na=False) |
                        df["contentUrl"].str.lower().str.contains(query.lower(), na=False)
                    )
                    df = df[mask]
                results = []
                for _, row in df.head(200).iterrows():
                    results.append({
                        "name": row.get("name", ""),
                        "contentUrl": row.get("contentUrl", ""),
                        "workbookName": row.get("workbookName", "") if "workbookName" in df.columns else "",
                        "viewUrl": f"{self.server_url}/#/views/{row.get('contentUrl', '')}",
                    })
                return results
            finally:
                self._close_conn()

    # ── filter normalization ───────────────────────────────────────────────
    @staticmethod
    def _is_date_key(k: str) -> bool:
        """Only auto-format values as dates if the key name suggests it's a date field."""
        low = k.lower().lstrip(":")
        return any(word in low for word in ("date", "day", "month", "year", "time", "period"))

    @staticmethod
    def _normalize_filters(raw_filters: Optional[Dict[str, str]]) -> Dict[str, str]:
        if not raw_filters:
            return {}
        base: Dict[str, str] = {}
        ranges: Dict[str, Dict[str, str]] = {}
        for k, v in raw_filters.items():
            if not k:
                continue
            k = k.strip()
            v = (v or "").strip()
            low = k.lower()
            if low.endswith("__from"):
                ranges.setdefault(k[:-6], {})["from"] = v
            elif low.endswith("__to"):
                ranges.setdefault(k[:-4], {})["to"] = v
            else:
                base[k] = v

        for root, pair in ranges.items():
            d_from = _parse_date_any(pair.get("from", ""))
            d_to   = _parse_date_any(pair.get("to", ""))
            if d_from and d_to:
                if d_to < d_from:
                    d_from, d_to = d_to, d_from
                is_param = root.strip().startswith(":")
                if is_param:
                    # Tableau parameters accept one value — use the "from" date in ISO format
                    # (Tableau REST API expects YYYY-MM-DD for Date-type parameters, not display format)
                    base[root] = d_from.strftime("%Y-%m-%d")
                else:
                    # vf_ filter: pass min,max pair for continuous date fields
                    base[root] = f"{d_from.strftime('%Y-%m-%d')},{d_to.strftime('%Y-%m-%d')}"

        # Only reformat values as dates when the key name suggests it's a date field.
        # Skipping this for non-date keys (e.g. Company ID, numeric IDs) prevents
        # _parse_date_any from silently corrupting values like "2024" → "2024-01-01".
        for k, v in list(base.items()):
            if not TableauClient._is_date_key(k):
                continue
            d = _parse_date_any(v)
            if d:
                # Both parameters and vf_ filters use ISO format for REST API
                base[k] = d.strftime("%Y-%m-%d")

        return base

    @staticmethod
    def _build_parameter_dict(fmt: str, filters: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        param_dict: Dict[str, str] = {}
        if (fmt or "").lower() == "pdf":
            param_dict["type"]        = "type=A4"
            param_dict["orientation"] = "orientation=Landscape"
        param_dict["maxAge"] = "maxAge=1"

        nf = TableauClient._normalize_filters(filters)
        if nf:
            vf_parts: List[str] = []
            for k, v in nf.items():
                if not v:
                    continue
                if k.strip().startswith(":"):
                    # # Tableau Parameter — add as its own param_dict entry so it becomes
                    # # a standalone URL query parameter (?:ParamName=value), NOT embedded
                    # # inside the filter string. Some tableau_api_lib versions don't parse
                    # # &-joined parameters correctly when inside the filter value.
                    # k_enc = quote(str(k), safe=":")        # keep leading colon
                    # v_enc = quote(str(v), safe="-_.,")     # encode / in dates → %2F
                    # safe_key = k.strip().lstrip(":").replace(" ", "_")
                    # param_dict[f"param_{safe_key}"] = f"{k_enc}={v_enc}"

                    # Tableau Parameter — raw string, same as vf_ approach.
                    # Let the HTTP layer handle any encoding.
                    safe_key = k.strip().lstrip(":").replace(" ", "_")
                    param_dict[f"param_{safe_key}"] = f"{k}={v}"
                else:
                    # View filter — vf_FieldName=value
                    # Per the tableau-api-lib author's own examples, the filter string
                    # is passed as a raw unencoded string (e.g. 'vf_Sub-Category=Binders').
                    # Pre-encoding with quote() risks double-encoding when requests builds
                    # the final HTTP request. Pass raw and let the HTTP layer handle it.
                    vf_parts.append(f"vf_{k}={v}")
            if vf_parts:
                param_dict["filter"] = "&".join(vf_parts)

        return param_dict

    # ── public render API ──────────────────────────────────────────────────
    def render_view(
        self,
        view_url: str,
        fmt: str = "png",
        out_dir: str = "tmp",
        extra_filters: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Render a single Tableau view to disk. Caller is responsible for
        holding the PAT lock and for calling _close_conn() when done with
        a batch of renders (so we re-use the auth token).
        """
        os.makedirs(out_dir, exist_ok=True)
        try:
            conn    = self._get_conn()
            view_id = self._resolve_view_id(conn, view_url)
            params  = self._build_parameter_dict(fmt, extra_filters)
            # Log the exact URL sent to Tableau for filter debugging
            query_string = "&".join(params.values()) if params else ""
            print(f"[TableauClient] Export fmt={fmt} view_id={view_id}")
            print(f"[TableauClient] Filter params sent: {query_string}")

            if (fmt or "").lower() == "pdf":
                resp = conn.query_view_pdf(view_id=view_id, parameter_dict=params)
                resp.raise_for_status()
                ext, data = "pdf", resp.content
            else:
                resp = conn.query_view_image(view_id=view_id, parameter_dict=params)
                resp.raise_for_status()
                ext, data = "png", resp.content

            out_path = os.path.join(out_dir, f"tableau_view_{view_id}.{ext}")
            with open(out_path, "wb") as f:
                f.write(data)
            return out_path

        except HTTPError as e:
            raise RuntimeError(f"Tableau export failed: {e}") from e
