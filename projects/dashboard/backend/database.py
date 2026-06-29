"""
database.py — SQLite operations for the Dream Big PM Company KPI Dashboard.

All SQL lives here. No ORM. Uses Python's built-in sqlite3 module.
Schema is defined in SPEC.md Section 3 — tables are reproduced exactly.
"""

import sqlite3
import os
from datetime import date, datetime, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Path configuration
# ---------------------------------------------------------------------------

# Resolve DB path relative to this file's location so it works regardless of
# which directory the process is started from.
_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_HERE, "..", "db", "dashboard.db")
DB_PATH = os.path.normpath(DB_PATH)


def _connect() -> sqlite3.Connection:
    """Open a connection with row_factory set to sqlite3.Row for dict-like access."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safe for concurrent readers
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

_CREATE_KPI_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS kpi_snapshots (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date            TEXT NOT NULL UNIQUE,
    rent_collected_pct       REAL,
    occupancy_pct            REAL,
    avg_days_on_market       REAL,
    renewal_rate_pct         REAL,
    speed_of_repair_days     REAL,
    maintenance_satisfaction REAL,
    google_rating            REAL,
    created_at               TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_CREATE_METRIC_HISTORY = """
CREATE TABLE IF NOT EXISTS metric_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    record_date TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value       REAL NOT NULL,
    property_id TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(record_date, metric_name, property_id)
);
"""

_CREATE_ALERT_LOG = """
CREATE TABLE IF NOT EXISTS alert_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type    TEXT NOT NULL,
    message       TEXT NOT NULL,
    property_id   TEXT,
    unit_id       TEXT,
    lease_id      TEXT,
    work_order_id TEXT,
    severity      TEXT NOT NULL DEFAULT 'WARN',
    fired_at      TEXT NOT NULL DEFAULT (datetime('now')),
    cleared_at    TEXT,
    cleared_by    TEXT
);
"""

_CREATE_THRESHOLD_CONFIG = """
CREATE TABLE IF NOT EXISTS threshold_config (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name    TEXT NOT NULL UNIQUE,
    warning_value  REAL NOT NULL,
    critical_value REAL NOT NULL,
    direction      TEXT NOT NULL,
    unit           TEXT,
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_CREATE_RENEWAL_PIPELINE = """
CREATE TABLE IF NOT EXISTS renewal_pipeline (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lease_id        TEXT NOT NULL UNIQUE,
    tenant_name     TEXT NOT NULL,
    unit_label      TEXT NOT NULL,
    property_name   TEXT NOT NULL,
    lease_end_date  TEXT NOT NULL,
    monthly_rent    REAL NOT NULL,
    risk_score      INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'not_started',
    notes           TEXT,
    last_updated    TEXT NOT NULL DEFAULT (datetime('now')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_CREATE_MANUAL_KPI_OVERRIDES = """
CREATE TABLE IF NOT EXISTS manual_kpi_overrides (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name TEXT NOT NULL,
    value       REAL NOT NULL,
    notes       TEXT,
    entered_by  TEXT NOT NULL DEFAULT 'brian',
    entered_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_CREATE_BRIEFINGS = """
CREATE TABLE IF NOT EXISTS briefings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    text         TEXT NOT NULL,
    generated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    email                 TEXT NOT NULL UNIQUE,
    role                  TEXT NOT NULL,
    assigned_property_ids TEXT,
    display_name          TEXT,
    is_active             INTEGER NOT NULL DEFAULT 1,
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    last_login            TEXT
);
"""

_CREATE_OAUTH_TOKENS = """
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    service       TEXT NOT NULL UNIQUE,
    access_token  TEXT NOT NULL,
    refresh_token TEXT,
    expires_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_CREATE_ROLE_BRIEFINGS = """
CREATE TABLE IF NOT EXISTS role_briefings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    role         TEXT NOT NULL,
    text         TEXT NOT NULL,
    generated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_CREATE_PORTFOLIO_HISTORY = """
CREATE TABLE IF NOT EXISTS portfolio_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date     TEXT NOT NULL,
    doors_count    INTEGER NOT NULL,
    change         INTEGER NOT NULL,
    property_name  TEXT,
    reason         TEXT,
    year           INTEGER NOT NULL,
    month          INTEGER NOT NULL
);
"""

_CREATE_RAW_KPI_DATA = """
CREATE TABLE IF NOT EXISTS raw_kpi_data (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL UNIQUE,
    data_json     TEXT NOT NULL,
    synced_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_CREATE_FINANCIAL_UPLOADS = """
CREATE TABLE IF NOT EXISTS financial_uploads (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    period         TEXT,
    uploaded_at    TEXT,
    gross_revenue  REAL,
    direct_labor   REAL,
    mgmt_labor     REAL,
    total_expenses REAL,
    net_income     REAL,
    door_count     INTEGER,
    metrics_json   TEXT
);
"""

_SEED_THRESHOLDS = """
INSERT OR IGNORE INTO threshold_config (metric_name, warning_value, critical_value, direction, unit) VALUES
('rent_collected_pct',       93.0, 90.0, 'below', 'pct'),
('occupancy_pct',            91.0, 90.0, 'below', 'pct'),
('avg_days_on_market',       30.0, 45.0, 'above', 'days'),
('renewal_rate_pct',         80.0, 75.0, 'below', 'pct'),
('speed_of_repair_days',      7.0, 14.0, 'above', 'days'),
('maintenance_satisfaction', 60.0, 55.0, 'below', 'count'),
('google_rating',             4.5,  4.0, 'below', 'stars'),
('vacancy_days',             21.0, 30.0, 'above', 'days'),
('work_order_age_days',      14.0, 21.0, 'above', 'days'),
('delinquency_pct',           5.0, 10.0, 'above', 'pct');
"""


def init_db() -> None:
    """
    Create all tables if they do not exist and seed threshold_config with
    default values. Safe to call on every app startup — uses IF NOT EXISTS
    and INSERT OR IGNORE so it is fully idempotent.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _connect() as conn:
        conn.execute(_CREATE_KPI_SNAPSHOTS)
        conn.execute(_CREATE_METRIC_HISTORY)
        conn.execute(_CREATE_ALERT_LOG)
        conn.execute(_CREATE_THRESHOLD_CONFIG)
        conn.execute(_CREATE_RENEWAL_PIPELINE)
        conn.execute(_CREATE_MANUAL_KPI_OVERRIDES)
        conn.execute(_CREATE_BRIEFINGS)
        conn.execute(_CREATE_USERS)
        conn.execute(_CREATE_OAUTH_TOKENS)
        conn.execute(_CREATE_ROLE_BRIEFINGS)
        conn.execute(_CREATE_PORTFOLIO_HISTORY)
        conn.execute(_CREATE_RAW_KPI_DATA)
        conn.execute(_CREATE_FINANCIAL_UPLOADS)
        conn.executescript(_SEED_THRESHOLDS)
        conn.execute(
            "INSERT OR IGNORE INTO users (email, role, display_name) "
            "VALUES ('brian@dreambigpm.com', 'admin', 'Brian Bean')"
        )


# ---------------------------------------------------------------------------
# KPI Snapshots
# ---------------------------------------------------------------------------

def save_kpi_snapshot(data: dict) -> None:
    """
    Upsert a row into kpi_snapshots for today's date.

    data keys (all optional except snapshot_date):
        snapshot_date, rent_collected_pct, occupancy_pct, avg_days_on_market,
        renewal_rate_pct, speed_of_repair_days, maintenance_satisfaction,
        google_rating

    If snapshot_date is omitted, today's date (YYYY-MM-DD) is used.
    Existing row for that date is replaced entirely.
    """
    snapshot_date = data.get("snapshot_date", date.today().isoformat())
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO kpi_snapshots
                (snapshot_date, rent_collected_pct, occupancy_pct,
                 avg_days_on_market, renewal_rate_pct, speed_of_repair_days,
                 maintenance_satisfaction, google_rating)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_date) DO UPDATE SET
                rent_collected_pct       = excluded.rent_collected_pct,
                occupancy_pct            = excluded.occupancy_pct,
                avg_days_on_market       = excluded.avg_days_on_market,
                renewal_rate_pct         = excluded.renewal_rate_pct,
                speed_of_repair_days     = excluded.speed_of_repair_days,
                maintenance_satisfaction = excluded.maintenance_satisfaction,
                google_rating            = excluded.google_rating
            """,
            (
                snapshot_date,
                data.get("rent_collected_pct"),
                data.get("occupancy_pct"),
                data.get("avg_days_on_market"),
                data.get("renewal_rate_pct"),
                data.get("speed_of_repair_days"),
                data.get("maintenance_satisfaction"),
                data.get("google_rating"),
            ),
        )


def get_kpi_snapshots(days: int = 90) -> list:
    """
    Return the last N days of KPI snapshot rows, oldest first.

    Each row is a dict with keys matching the kpi_snapshots columns.
    Missing days are not back-filled — the caller receives only rows that exist.
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM kpi_snapshots
            WHERE snapshot_date >= ?
            ORDER BY snapshot_date ASC
            """,
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Metric History
# ---------------------------------------------------------------------------

def save_metric(
    record_date: str,
    metric_name: str,
    value: float,
    property_id: Optional[str] = None,
) -> None:
    """
    Upsert a single metric value for a given date and property.

    property_id=None means portfolio-level (not property-specific).
    Duplicate (record_date, metric_name, property_id) rows are replaced.

    Note: SQLite NULL != NULL in unique indexes, so we cannot rely on
    ON CONFLICT for the NULL property_id case. Instead we UPDATE first and
    INSERT only when no existing row was found.
    """
    with _connect() as conn:
        if property_id is None:
            updated = conn.execute(
                """
                UPDATE metric_history SET value = ?
                WHERE record_date = ? AND metric_name = ? AND property_id IS NULL
                """,
                (value, record_date, metric_name),
            ).rowcount
        else:
            updated = conn.execute(
                """
                UPDATE metric_history SET value = ?
                WHERE record_date = ? AND metric_name = ? AND property_id = ?
                """,
                (value, record_date, metric_name, property_id),
            ).rowcount

        if updated == 0:
            conn.execute(
                """
                INSERT OR IGNORE INTO metric_history
                    (record_date, metric_name, value, property_id)
                VALUES (?, ?, ?, ?)
                """,
                (record_date, metric_name, value, property_id),
            )


def get_metric_history(
    metric_name: str,
    days: int = 90,
    property_id: Optional[str] = None,
) -> list:
    """
    Return the last N days of history for a single metric, oldest first.

    Pass property_id=None for portfolio-level history.
    Each item is a dict with keys: id, record_date, metric_name, value,
    property_id, created_at.
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM metric_history
            WHERE metric_name = ?
              AND record_date >= ?
              AND (property_id IS ? OR property_id = ?)
            ORDER BY record_date ASC
            """,
            (metric_name, cutoff, property_id, property_id),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

def fire_alert(
    alert_type: str,
    message: str,
    severity: str,
    property_id: Optional[str] = None,
    unit_id: Optional[str] = None,
    lease_id: Optional[str] = None,
    work_order_id: Optional[str] = None,
) -> Optional[int]:
    """
    Insert a new alert into alert_log, but only if no matching active alert
    already exists.

    A "matching" alert is one with the same alert_type AND the same unit_id
    (when provided) or the same work_order_id (when provided). This prevents
    the same overdue work order from generating duplicate alerts on every
    refresh cycle.

    Returns the new alert's id, or None if a duplicate was found and skipped.
    """
    with _connect() as conn:
        # Build duplicate-check query dynamically based on which reference
        # fields were supplied.
        if unit_id is not None:
            existing = conn.execute(
                """
                SELECT id FROM alert_log
                WHERE alert_type = ? AND unit_id = ? AND cleared_at IS NULL
                LIMIT 1
                """,
                (alert_type, unit_id),
            ).fetchone()
        elif work_order_id is not None:
            existing = conn.execute(
                """
                SELECT id FROM alert_log
                WHERE alert_type = ? AND work_order_id = ? AND cleared_at IS NULL
                LIMIT 1
                """,
                (alert_type, work_order_id),
            ).fetchone()
        elif lease_id is not None:
            existing = conn.execute(
                """
                SELECT id FROM alert_log
                WHERE alert_type = ? AND lease_id = ? AND cleared_at IS NULL
                LIMIT 1
                """,
                (alert_type, lease_id),
            ).fetchone()
        else:
            # Portfolio-level alert — match on type + property only
            existing = conn.execute(
                """
                SELECT id FROM alert_log
                WHERE alert_type = ?
                  AND (property_id IS ? OR property_id = ?)
                  AND cleared_at IS NULL
                LIMIT 1
                """,
                (alert_type, property_id, property_id),
            ).fetchone()

        if existing:
            return None  # already active, skip

        cursor = conn.execute(
            """
            INSERT INTO alert_log
                (alert_type, message, property_id, unit_id, lease_id,
                 work_order_id, severity)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (alert_type, message, property_id, unit_id, lease_id,
             work_order_id, severity),
        )
        return cursor.lastrowid


def clear_alert(alert_id: int, cleared_by: str = "system") -> None:
    """
    Mark a single alert as cleared by setting cleared_at and cleared_by.

    The alert is identified by its integer primary key.
    """
    now = datetime.utcnow().isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            UPDATE alert_log
            SET cleared_at = ?, cleared_by = ?
            WHERE id = ? AND cleared_at IS NULL
            """,
            (now, cleared_by, alert_id),
        )


def auto_clear_alerts(alert_type: str, reference_id: str) -> int:
    """
    Clear all active alerts of a given type whose unit_id, work_order_id, or
    lease_id matches reference_id.

    Used when a condition resolves automatically — e.g., a work order closes
    or a new lease is signed on a previously vacant unit.

    Returns the number of rows cleared.
    """
    now = datetime.utcnow().isoformat(timespec="seconds")
    with _connect() as conn:
        cursor = conn.execute(
            """
            UPDATE alert_log
            SET cleared_at = ?, cleared_by = 'system'
            WHERE alert_type = ?
              AND cleared_at IS NULL
              AND (unit_id = ? OR work_order_id = ? OR lease_id = ?)
            """,
            (now, alert_type, reference_id, reference_id, reference_id),
        )
        return cursor.rowcount


def get_active_alerts() -> list:
    """
    Return all uncleared alerts, sorted by severity (CRITICAL first) then
    fired_at descending.

    Each item is a dict with all alert_log columns.
    """
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM alert_log
            WHERE cleared_at IS NULL
            ORDER BY
                CASE severity WHEN 'CRITICAL' THEN 0 ELSE 1 END,
                fired_at DESC
            """,
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Threshold Config
# ---------------------------------------------------------------------------

def get_thresholds() -> dict:
    """
    Return all threshold_config rows as a dict keyed by metric_name.

    Example:
        {
            'rent_collected_pct': {
                'warning_value': 93.0,
                'critical_value': 90.0,
                'direction': 'below',
                'unit': 'pct',
                ...
            },
            ...
        }
    """
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM threshold_config").fetchall()
    return {r["metric_name"]: dict(r) for r in rows}


# ---------------------------------------------------------------------------
# Renewal Pipeline
# ---------------------------------------------------------------------------

def upsert_renewal(lease_id: str, data: dict) -> None:
    """
    Insert or update a row in renewal_pipeline for the given lease_id.

    data keys (all required for insert; partial updates supported for
    existing rows):
        tenant_name, unit_label, property_name, lease_end_date,
        monthly_rent, risk_score, status, notes

    last_updated is always set to now on upsert.
    """
    now = datetime.utcnow().isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO renewal_pipeline
                (lease_id, tenant_name, unit_label, property_name,
                 lease_end_date, monthly_rent, risk_score, status, notes,
                 last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(lease_id) DO UPDATE SET
                tenant_name    = excluded.tenant_name,
                unit_label     = excluded.unit_label,
                property_name  = excluded.property_name,
                lease_end_date = excluded.lease_end_date,
                monthly_rent   = excluded.monthly_rent,
                risk_score     = excluded.risk_score,
                status         = excluded.status,
                notes          = excluded.notes,
                last_updated   = excluded.last_updated
            """,
            (
                lease_id,
                data.get("tenant_name", ""),
                data.get("unit_label", ""),
                data.get("property_name", ""),
                data.get("lease_end_date", ""),
                data.get("monthly_rent", 0.0),
                data.get("risk_score", 1),
                data.get("status", "not_started"),
                data.get("notes"),
                now,
            ),
        )


def update_renewal_status(
    lease_id: str, status: str, notes: Optional[str] = None
) -> None:
    """
    Update the status (and optionally the notes) of a renewal pipeline row.

    Valid status values: 'not_started', 'contacted', 'in_negotiation',
    'signed', 'lost'.
    """
    now = datetime.utcnow().isoformat(timespec="seconds")
    with _connect() as conn:
        if notes is not None:
            conn.execute(
                """
                UPDATE renewal_pipeline
                SET status = ?, notes = ?, last_updated = ?
                WHERE lease_id = ?
                """,
                (status, notes, now, lease_id),
            )
        else:
            conn.execute(
                """
                UPDATE renewal_pipeline
                SET status = ?, last_updated = ?
                WHERE lease_id = ?
                """,
                (status, now, lease_id),
            )


def get_renewal_pipeline() -> list:
    """
    Return all rows in renewal_pipeline ordered by lease_end_date ascending
    (soonest expiring first).

    Each item is a dict with all renewal_pipeline columns.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM renewal_pipeline ORDER BY lease_end_date ASC"
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Manual KPI Overrides
# ---------------------------------------------------------------------------

def set_manual_kpi(
    metric_name: str, value: float, notes: Optional[str] = None
) -> None:
    """
    Insert a new row into manual_kpi_overrides for the given metric.

    Each call appends a new row — history is preserved. Use get_manual_kpi
    to read the most recent value. Designed for metrics that cannot be fetched
    automatically (Google rating, maintenance satisfaction score).
    """
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO manual_kpi_overrides (metric_name, value, notes)
            VALUES (?, ?, ?)
            """,
            (metric_name, value, notes),
        )


def get_manual_kpi(metric_name: str) -> Optional[float]:
    """
    Return the most recently entered value for a manual KPI metric.

    Returns None if no entry exists yet.
    """
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT value FROM manual_kpi_overrides
            WHERE metric_name = ?
            ORDER BY entered_at DESC
            LIMIT 1
            """,
            (metric_name,),
        ).fetchone()
    return row["value"] if row else None


# ---------------------------------------------------------------------------
# Briefings
# ---------------------------------------------------------------------------

def save_briefing(text: str) -> int:
    """
    Store a newly generated AI briefing text in the briefings table.

    generated_at is set to the current UTC time automatically.
    Returns the new row's id.
    """
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO briefings (text) VALUES (?)",
            (text,),
        )
        return cursor.lastrowid


def get_todays_briefing() -> Optional[str]:
    """
    Return today's most recently generated briefing text, or None if no
    briefing has been generated today yet.
    """
    today = date.today().isoformat()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT text FROM briefings
            WHERE date(generated_at) = ?
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (today,),
        ).fetchone()
    return row["text"] if row else None


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_user_by_email(email: str) -> Optional[dict]:
    """Return a user row by email, or None if not found."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? AND is_active = 1",
            (email,),
        ).fetchone()
    return dict(row) if row else None


def get_or_create_user(email: str, display_name: str = None) -> dict:
    """
    Look up user by email. If not found, create with role='property_manager'
    (or 'admin' for brian@dreambigpm.com). Returns the user dict.
    """
    existing = get_user_by_email(email)
    if existing:
        return existing

    role = "admin" if email == "brian@dreambigpm.com" else "property_manager"
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (email, role, display_name) VALUES (?, ?, ?)",
            (email, role, display_name or email.split("@")[0]),
        )
    return get_user_by_email(email)


def update_user_last_login(user_id: int) -> None:
    """Set last_login to current UTC time."""
    now = datetime.utcnow().isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (now, user_id),
        )


# ---------------------------------------------------------------------------
# Role Briefings
# ---------------------------------------------------------------------------

def save_role_briefing(role: str, text: str) -> int:
    """Store a role-specific briefing. Returns new row id."""
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO role_briefings (role, text) VALUES (?, ?)",
            (role, text),
        )
        return cursor.lastrowid


def clear_todays_briefings() -> None:
    """Delete all briefings generated today so they regenerate with fresh data on next request."""
    today = date.today().isoformat()
    with _connect() as conn:
        conn.execute("DELETE FROM role_briefings WHERE date(generated_at) = ?", (today,))


def get_todays_role_briefing(role: str) -> Optional[str]:
    """Return today's briefing for the given role, or None if not yet generated."""
    today = date.today().isoformat()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT text FROM role_briefings
            WHERE role = ? AND date(generated_at) = ?
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (role, today),
        ).fetchone()
    return row["text"] if row else None


# ---------------------------------------------------------------------------
# OAuth Tokens
# ---------------------------------------------------------------------------

def save_oauth_token(
    service: str,
    access_token: str,
    refresh_token: str,
    expires_at: str,
) -> None:
    """Upsert an OAuth token record for the given service (e.g. 'quickbooks')."""
    now = datetime.utcnow().isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO oauth_tokens (service, access_token, refresh_token, expires_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(service) DO UPDATE SET
                access_token  = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at    = excluded.expires_at,
                updated_at    = excluded.updated_at
            """,
            (service, access_token, refresh_token, expires_at, now),
        )


def get_oauth_token(service: str) -> Optional[dict]:
    """Return the stored OAuth token for a service, or None if not set."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM oauth_tokens WHERE service = ?",
            (service,),
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Raw KPI Data (MCP sync output — full API response stored as JSON)
# ---------------------------------------------------------------------------

def save_raw_kpi_data(snapshot_date: str, data: dict) -> None:
    """
    Upsert the full KPI response dict for a given date.

    This is the primary data store written by sync.py after a Rentvine MCP
    fetch. The FastAPI /api/kpis endpoint reads from here so the dashboard
    always shows real data regardless of whether the Rentvine REST API works.
    """
    import json
    now = datetime.utcnow().isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO raw_kpi_data (snapshot_date, data_json, synced_at)
            VALUES (?, ?, ?)
            ON CONFLICT(snapshot_date) DO UPDATE SET
                data_json = excluded.data_json,
                synced_at = excluded.synced_at
            """,
            (snapshot_date, json.dumps(data), now),
        )


def get_latest_raw_kpi_data() -> Optional[dict]:
    """
    Return the most recently synced full KPI response dict, or None if the
    table is empty. Used by kpi.py as the primary data source.
    """
    import json
    with _connect() as conn:
        row = conn.execute(
            "SELECT data_json, synced_at FROM raw_kpi_data ORDER BY synced_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    data = json.loads(row["data_json"])
    data["_synced_at"] = row["synced_at"]
    return data


# ---------------------------------------------------------------------------
# Financial Uploads (P&L PDF uploads — replaces QuickBooks OAuth)
# ---------------------------------------------------------------------------

def save_financial_upload(period: str, parsed: dict, metrics: dict, door_count: int) -> int:
    """Save a parsed P&L upload. Returns the new row id."""
    import json
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO financial_uploads
               (period, uploaded_at, gross_revenue, direct_labor, mgmt_labor,
                total_expenses, net_income, door_count, metrics_json)
               VALUES (?,datetime('now'),?,?,?,?,?,?,?)""",
            (
                period,
                parsed["gross_revenue"],
                parsed["direct_labor"],
                parsed["mgmt_labor"],
                parsed["total_expenses"],
                parsed["net_income"],
                door_count,
                json.dumps(metrics),
            ),
        )
        return cur.lastrowid


def get_latest_financial_upload() -> Optional[dict]:
    """Return the most recent P&L period (latest upload wins per period), sorted chronologically."""
    history = get_financial_history()
    if not history:
        return None
    return history[-1]


def get_financial_history() -> list:
    """Return one row per period (latest upload wins), sorted chronologically by period."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT f.* FROM financial_uploads f
               INNER JOIN (
                 SELECT MAX(id) AS max_id FROM financial_uploads GROUP BY period
               ) g ON f.id = g.max_id"""
        ).fetchall()
    if not rows:
        return []

    _MONTHS = {'January':1,'February':2,'March':3,'April':4,'May':5,'June':6,
               'July':7,'August':8,'September':9,'October':10,'November':11,'December':12}

    def _sort_key(row):
        parts = row['period'].split()
        if len(parts) == 2:
            return (int(parts[1]), _MONTHS.get(parts[0], 0))
        return (0, 0)

    return sorted([dict(r) for r in rows], key=_sort_key)
