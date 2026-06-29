"""
sheets.py — Google Sheets integration for the Dream Big PM Dashboard.

Reads the door/churn tracking sheet and computes annual churn stats.
Uses a service account (no OAuth popup needed) — set GOOGLE_SERVICE_ACCOUNT_JSON
in .env pointing to the downloaded service account key file.

Sheet ID: 15IfjJljKTvXrTF0iqB6xT9mZupJ4uPiKMWZCXcZKuI8
Columns S:X  →  # DOORS, DATE, (+/-), MONTH, # / MONTH, property street name
"""

import os
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SHEET_ID   = "15IfjJljKTvXrTF0iqB6xT9mZupJ4uPiKMWZCXcZKuI8"
SHEET_RANGE = "Sheet1!S:X"   # columns S through X

# Column index within the S:X slice (0-based)
COL_DOORS    = 0  # S — cumulative door count
COL_DATE     = 1  # T — date of event
COL_NET      = 2  # U — running net cumulative count
COL_MONTH    = 3  # V — month label (last row of month only)
COL_NET_MO   = 4  # W — net doors that month
COL_PROPERTY = 5  # X — property street name


def _svc_key_path() -> Optional[str]:
    """Return the path to the service account JSON key file, or None if not set."""
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not raw:
        return None
    # Resolve relative paths from the dashboard root (parent of backend/)
    p = Path(raw)
    if not p.is_absolute():
        p = Path(__file__).parent.parent / p
    return str(p)


XLSX_URL = (
    "https://docs.google.com/spreadsheets/d/"
    f"{SHEET_ID}/export?format=xlsx"
)
RENT_ROLL_SHEET_INDEX = 1  # 0-based index of the RENT ROLL sheet


def is_sheets_connected() -> bool:
    """The sheet is public — always connected."""
    return True


def get_sheets_service():
    """
    Build and return an authenticated Google Sheets service client.
    Reads GOOGLE_SERVICE_ACCOUNT_JSON from env.
    Returns None if not configured or if the required packages are missing.
    """
    if not is_sheets_connected():
        return None
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_service_account_file(
            _svc_key_path(),
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        return service
    except ImportError:
        logger.warning(
            "Google API packages not installed. Run: "
            "pip install google-auth google-api-python-client"
        )
        return None
    except Exception as e:
        logger.error(f"Failed to build Sheets service: {e}")
        return None


def _parse_date(raw: str) -> Optional[str]:
    """
    Parse a date string in M/D/YY format and return ISO (YYYY-MM-DD).
    Returns None if unparseable.
    """
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _to_int(val) -> Optional[int]:
    """Convert a cell value to int, or None if blank/unparseable."""
    if val is None or str(val).strip() == "":
        return None
    try:
        return int(float(str(val).replace(",", "")))
    except (ValueError, TypeError):
        return None


def _excel_serial_to_iso(serial_str: str) -> Optional[str]:
    """Convert an Excel date serial number (e.g. '44986') to ISO date string."""
    try:
        serial = float(serial_str)
        if serial < 1:
            return None
        # Excel epoch: 1899-12-30 (accounts for the 1900 leap-year bug)
        from datetime import date, timedelta
        d = date(1899, 12, 30) + timedelta(days=int(serial))
        return d.isoformat()
    except Exception:
        return None


def _read_ytd_summary_xlsx() -> Optional[dict]:
    """
    Read the sheet's own YTD summary (last ADDED/LOST/CHURN block in col Y/Z).
    Returns {adds, offboards, churn_pct} or None on failure.
    """
    import io, zipfile, urllib.request
    import xml.etree.ElementTree as ET

    try:
        with urllib.request.urlopen(XLSX_URL, timeout=15) as resp:
            data = resp.read()
    except Exception as e:
        logger.error(f"_read_ytd_summary_xlsx: download failed: {e}")
        return None

    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        strings: list[str] = []
        ss = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        for si in ss.findall(".//x:si", ns):
            strings.append("".join(t.text or "" for t in si.findall(".//x:t", ns)))

        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_map = {r.get("Id"): r.get("Target") for r in rels.findall("*")}
        sheet_files = []
        for sh in wb.findall(".//x:sheet", ns):
            rid = sh.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rel_map.get(rid, "")
            sheet_files.append(target.replace("worksheets/", "xl/worksheets/"))

        ws = ET.fromstring(zf.read(sheet_files[RENT_ROLL_SHEET_INDEX]))
    except Exception as e:
        logger.error(f"_read_ytd_summary_xlsx: parse failed: {e}")
        return None

    def col_idx(ref: str) -> int:
        col = "".join(c for c in ref if c.isalpha())
        idx = 0
        for c in col:
            idx = idx * 26 + (ord(c) - ord("A") + 1)
        return idx - 1

    def cell_val(c) -> str:
        t = c.get("t"); v = c.find("x:v", ns)
        if v is None: return ""
        return strings[int(v.text)] if t == "s" else (v.text or "")

    # Build row-number → {col_idx: value} map for cols Y(25) and Z(26) only
    rows_map: dict[int, dict[int, str]] = {}
    for row in ws.findall(".//x:row", ns):
        rnum = int(row.get("r", 0))
        cells: dict[int, str] = {}
        for c in row.findall("x:c", ns):
            ci = col_idx(c.get("r", ""))
            if ci in (25, 26):
                cells[ci] = cell_val(c)
        if cells:
            rows_map[rnum] = cells

    # Find the LAST row where col Y == "ADDED"
    added_row = None
    for rnum in sorted(rows_map):
        if rows_map[rnum].get(25, "") == "ADDED":
            added_row = rnum

    if added_row is None:
        return None

    try:
        vals = rows_map.get(added_row + 1, {})
        adds     = int(float(vals.get(25, "0") or "0"))
        offboards = int(float(vals.get(26, "0") or "0"))

        churn_row = rows_map.get(added_row + 4, {})
        churn_pct = round(float(churn_row.get(26, "0") or "0") * 100, 2)
        return {"adds": adds, "offboards": offboards, "churn_pct": churn_pct}
    except Exception as e:
        logger.error(f"_read_ytd_summary_xlsx: value parse failed: {e}")
        return None


def _read_churn_xlsx() -> list[dict]:
    """
    Download the public xlsx and parse the RENT ROLL sheet columns S-X.
    Returns rows in the same format as read_churn_sheet().
    """
    import io, zipfile, urllib.request
    import xml.etree.ElementTree as ET

    try:
        with urllib.request.urlopen(XLSX_URL, timeout=15) as resp:
            data = resp.read()
    except Exception as e:
        logger.error(f"_read_churn_xlsx: download failed: {e}")
        return []

    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))

        # Shared strings table
        strings: list[str] = []
        ss = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        for si in ss.findall(".//x:si", ns):
            strings.append("".join(t.text or "" for t in si.findall(".//x:t", ns)))

        # Sheet index → file name mapping from workbook
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_map = {r.get("Id"): r.get("Target") for r in rels.findall("*")}
        sheet_files = []
        for sh in wb.findall(".//x:sheet", ns):
            rid = sh.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rel_map.get(rid, "")
            sheet_files.append(target.replace("worksheets/", "xl/worksheets/"))

        sheet_path = sheet_files[RENT_ROLL_SHEET_INDEX]
        ws = ET.fromstring(zf.read(sheet_path))
    except Exception as e:
        logger.error(f"_read_churn_xlsx: parse failed: {e}")
        return []

    def col_idx(ref: str) -> int:
        col = "".join(c for c in ref if c.isalpha())
        idx = 0
        for c in col:
            idx = idx * 26 + (ord(c) - ord("A") + 1)
        return idx - 1

    def cell_val(c) -> str:
        t = c.get("t")
        v = c.find("x:v", ns)
        if v is None:
            return ""
        return strings[int(v.text)] if t == "s" else (v.text or "")

    # Collect rows as col-index → value maps
    raw_rows: list[dict] = []
    for row in ws.findall(".//x:row", ns):
        cells: dict[int, str] = {}
        for c in row.findall("x:c", ns):
            cells[col_idx(c.get("r", ""))] = cell_val(c)
        raw_rows.append(cells)

    # S=18, T=19, U=20, V=21, W=22, X=23
    S, T, X = 18, 19, 23

    def pad(cells: dict, col: int) -> str:
        return cells.get(col, "").strip()

    parsed: list[dict] = []
    prev_doors: Optional[int] = None

    for cells in raw_rows:
        raw_doors    = pad(cells, S)
        raw_date     = pad(cells, T)
        raw_property = pad(cells, X)

        if not raw_date or not raw_property:
            d = _to_int(raw_doors)
            # Ignore year-label rows (e.g. "2026" in col S used as a section header)
            if d is not None and d < 500:
                prev_doors = d
            continue

        # Dates come as Excel serial numbers from xlsx
        date_iso = _excel_serial_to_iso(raw_date)
        if not date_iso:
            date_iso = _parse_date(raw_date)
        if not date_iso:
            continue

        doors = _to_int(raw_doors)
        if doors is None:
            continue

        is_add      = prev_doors is not None and doors > prev_doors
        is_offboard = prev_doors is not None and doors < prev_doors
        prev_doors  = doors

        parsed.append({
            "doors":         doors,
            "date_iso":      date_iso,
            "property_name": raw_property,
            "is_add":        is_add,
            "is_offboard":   is_offboard,
        })

    return parsed


def read_churn_sheet() -> list[dict]:
    """
    Read the door-event log from the public RENT ROLL sheet (columns S-X).
    Returns a list of row dicts: { doors, date_iso, property_name, is_add, is_offboard }
    """
    return _read_churn_xlsx()

def _read_churn_sheet_via_api() -> list[dict]:
    """Legacy service-account path — kept for reference but not called."""
    service = get_sheets_service()
    if service is None:
        logger.warning("read_churn_sheet: Sheets service not available")
        return []

    try:
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=SHEET_ID, range=SHEET_RANGE)
            .execute()
        )
    except Exception as e:
        logger.error(f"read_churn_sheet API error: {e}")
        return []

    raw_rows = result.get("values", [])
    if not raw_rows:
        return []

    # Pad each row to at least 6 elements so indexing is safe
    def pad(row):
        return row + [""] * (6 - len(row))

    # Skip header row (row 0)
    data_rows = [pad(r) for r in raw_rows[1:]]

    parsed = []
    prev_doors = None

    for row in data_rows:
        raw_date     = str(row[COL_DATE]).strip()
        raw_property = str(row[COL_PROPERTY]).strip()
        raw_doors    = str(row[COL_DOORS]).strip()

        # Skip if no date or no property name — these are summary/header rows
        if not raw_date or not raw_property:
            # Still update prev_doors if doors value is present
            d = _to_int(raw_doors)
            if d is not None:
                prev_doors = d
            continue

        date_iso = _parse_date(raw_date)
        if not date_iso:
            continue

        doors = _to_int(raw_doors)
        if doors is None:
            continue

        is_add      = False
        is_offboard = False

        if prev_doors is not None:
            if doors > prev_doors:
                is_add = True
            elif doors < prev_doors:
                is_offboard = True

        prev_doors = doors

        parsed.append(
            {
                "doors":        doors,
                "date_iso":     date_iso,
                "property_name": raw_property,
                "is_add":       is_add,
                "is_offboard":  is_offboard,
            }
        )

    return parsed


def compute_churn_summary(rows: list[dict]) -> dict:
    """
    From the parsed rows, compute annual churn stats.

    Returns:
    {
      history: [
        { year, start_doors, adds, offboards, end_doors, churn_pct },
        ...
      ],
      current_year: int,
      current_churn_pct: float | None,
      current_offboards: int,
      current_start_doors: int,
      current_adds: int,
      current_door_count: int,
      average_churn_pct: float | None,
    }
    """
    if not rows:
        return _empty_summary()

    current_year = date.today().year
    start_year   = 2023  # earliest year to report

    # Confirmed historical data — spreadsheet tracking has gaps for these years.
    # Brian verified these numbers directly (June 2026).
    # 2025 offboards = 16 actual losses; 4 additional were temporary deactivations
    # (not churn), which is why 2025 end_doors=119 despite start+adds-offboards=123.
    CONFIRMED_HISTORY = {
        2023: {"start_doors": 32,  "adds": 36,  "offboards": 0,  "end_doors": 68,  "churn_pct": 0.0},
        2024: {"start_doors": 68,  "adds": 27,  "offboards": 17, "end_doors": 78,  "churn_pct": round(17/68*100, 2)},
        2025: {"start_doors": 80,  "adds": 59,  "offboards": 16, "end_doors": 119, "churn_pct": round(16/80*100, 2)},
    }

    # Determine Jan 1 door count for current-year live computation.
    def _year_start_doors(year: int) -> int:
        if year in CONFIRMED_HISTORY:
            return CONFIRMED_HISTORY[year]["start_doors"]
        cutoff = f"{year - 1}-12-31"
        prior = [r for r in rows if r["date_iso"] <= cutoff]
        return prior[-1]["doors"] if prior else 0

    history = []
    for yr in range(start_year, current_year + 1):
        if yr in CONFIRMED_HISTORY:
            history.append({"year": yr, **CONFIRMED_HISTORY[yr]})
            continue

        yr_start = f"{yr}-01-01"
        yr_end   = f"{yr}-12-31"

        yr_rows = [r for r in rows if yr_start <= r["date_iso"] <= yr_end]

        start_doors = _year_start_doors(yr)
        adds        = sum(1 for r in yr_rows if r["is_add"])
        offboards   = sum(1 for r in yr_rows if r["is_offboard"])
        end_doors   = yr_rows[-1]["doors"] if yr_rows else start_doors
        churn_pct   = (
            round(offboards / start_doors * 100, 2)
            if start_doors > 0
            else 0.0
        )

        history.append(
            {
                "year":        yr,
                "start_doors": start_doors,
                "adds":        adds,
                "offboards":   offboards,
                "end_doors":   end_doors,
                "churn_pct":   churn_pct,
            }
        )

    # Current year stats
    current = next((h for h in history if h["year"] == current_year), None)
    current_churn_pct   = current["churn_pct"]   if current else None
    current_offboards   = current["offboards"]   if current else 0
    current_start_doors = current["start_doors"] if current else 0
    current_adds        = current["adds"]        if current else 0
    # Latest known door count
    current_door_count = rows[-1]["doors"] if rows else 0

    # Average churn across all years that have a nonzero start_doors
    valid_years = [h for h in history if h["start_doors"] > 0]
    average_churn_pct = (
        round(sum(h["churn_pct"] for h in valid_years) / len(valid_years), 2)
        if valid_years
        else None
    )

    return {
        "history":             history,
        "current_year":        current_year,
        "current_churn_pct":   current_churn_pct,
        "current_offboards":   current_offboards,
        "current_start_doors": current_start_doors,
        "current_adds":        current_adds,
        "current_door_count":  current_door_count,
        "average_churn_pct":   average_churn_pct,
    }


def _empty_summary() -> dict:
    return {
        "history":             [],
        "current_year":        date.today().year,
        "current_churn_pct":   None,
        "current_offboards":   0,
        "current_start_doors": 0,
        "current_adds":        0,
        "current_door_count":  0,
        "average_churn_pct":   None,
    }


def append_door_event(event_date: str, property_name: str, event_type: str) -> bool:
    """
    Append a new door event row to the sheet.

    Reads the last known # DOORS value, then:
    - Adds 1 for an 'add', subtracts 1 for an 'offboard'.
    - Writes: [new_doors, date, new_net_count, '', '', property_name]

    Returns True on success, False on failure.
    """
    service = get_sheets_service()
    if service is None:
        logger.error("append_door_event: Sheets service not available")
        return False

    try:
        # Read current last row to get doors and net count
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=SHEET_ID, range=SHEET_RANGE)
            .execute()
        )
        all_rows = result.get("values", [])

        last_doors = 0
        last_net   = 0
        for r in reversed(all_rows):
            padded = (r + [""] * 6)[:6]
            d = _to_int(padded[COL_DOORS])
            n = _to_int(padded[COL_NET])
            if d is not None:
                last_doors = d
                last_net   = n if n is not None else 0
                break

        delta = 1 if event_type == "add" else -1
        new_doors = last_doors + delta
        new_net   = last_net + delta

        # Format date back to M/D/YY
        dt = datetime.strptime(event_date, "%Y-%m-%d")
        formatted_date = f"{dt.month}/{dt.day}/{str(dt.year)[2:]}"

        new_row = [new_doors, formatted_date, new_net, "", "", property_name]

        service.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=SHEET_RANGE,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [new_row]},
        ).execute()

        logger.info(
            f"append_door_event: {event_type} '{property_name}' on {event_date} "
            f"→ doors {last_doors} → {new_doors}"
        )
        return True

    except Exception as e:
        logger.error(f"append_door_event failed: {e}")
        return False
