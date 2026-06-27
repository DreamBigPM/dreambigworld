"""
sync.py — Rentvine MCP Data Sync for Dream Big PM Dashboard

This module is called from Claude Code sessions after fetching fresh data
from Rentvine via MCP tools. It accepts a snapshot dict and writes it to
SQLite so the FastAPI backend serves real numbers.

How a sync works:
  1. Brian says "sync the dashboard" (or Claude Code runs daily at 6am)
  2. Claude Code calls Rentvine MCP tools to fetch properties, leases,
     work orders, transactions, etc.
  3. Claude Code calls sync_snapshot(snapshot) with processed data
  4. sync.py writes to SQLite — kpi_snapshots, metric_history, raw_kpi_data,
     renewal_pipeline, and alert_log
  5. FastAPI serves the fresh data from SQLite via /api/kpis

Can also be run from command line with a JSON file:
  python -m backend.sync --file snapshot.json

Snapshot dict keys (all optional except snapshot_date):
  snapshot_date         str  "YYYY-MM-DD"
  rent_collected_pct    float  e.g. 93.0
  rent_collected_usd    float
  rent_expected_usd     float
  occupancy_pct         float  e.g. 94.1
  total_units           int    e.g. 120
  active_leases         int
  vacant_units          int
  avg_days_on_market    float
  renewal_rate_pct      float | None
  speed_of_repair_days  float
  open_work_orders      int
  overdue_work_orders   int
  delinquent_count      int
  maintenance_satisfaction  float | None
  google_rating         float | None
  delinquent_leases     list[dict]
  open_work_order_list  list[dict]
  overdue_work_order_list  list[dict]
  vacant_unit_list      list[dict]
  renewal_pipeline_list list[dict]
  at_risk_tenants       list[dict]
  inspection_compliance list[dict]
"""

import sys
import json
import logging
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Import database using the same pattern as the rest of the backend
try:
    from backend import database
except ImportError:
    import database  # allow running as: python backend/sync.py


def sync_snapshot(snapshot: dict) -> dict:
    """
    Write a complete KPI snapshot to SQLite.

    Returns a summary dict with counts of records written.
    """
    today = snapshot.get("snapshot_date", date.today().isoformat())
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    summary = {"snapshot_date": today, "tables_written": [], "alerts_fired": 0, "renewals_written": 0}

    # ── 1. kpi_snapshots ──────────────────────────────────────────────────────
    database.save_kpi_snapshot({
        "snapshot_date": today,
        "rent_collected_pct":    snapshot.get("rent_collected_pct"),
        "occupancy_pct":         snapshot.get("occupancy_pct"),
        "avg_days_on_market":    snapshot.get("avg_days_on_market"),
        "renewal_rate_pct":      snapshot.get("renewal_rate_pct"),
        "speed_of_repair_days":  snapshot.get("speed_of_repair_days"),
        "maintenance_satisfaction": snapshot.get("maintenance_satisfaction"),
        "google_rating":         snapshot.get("google_rating"),
    })
    summary["tables_written"].append("kpi_snapshots")

    # ── 2. metric_history (powers sparklines) ─────────────────────────────────
    history_metrics = [
        ("rent_collected_pct",   snapshot.get("rent_collected_pct")),
        ("occupancy_pct",        snapshot.get("occupancy_pct")),
        ("avg_days_on_market",   snapshot.get("avg_days_on_market")),
        ("renewal_rate_pct",     snapshot.get("renewal_rate_pct")),
        ("speed_of_repair_days", snapshot.get("speed_of_repair_days")),
        ("open_work_orders",     snapshot.get("open_work_orders")),
        ("overdue_work_orders",  snapshot.get("overdue_work_orders")),
        ("delinquent_count",     snapshot.get("delinquent_count")),
        ("vacant_units",         snapshot.get("vacant_units")),
        ("occupancy_total_units", snapshot.get("total_units")),
    ]
    for metric_name, value in history_metrics:
        if value is not None:
            database.save_metric(today, metric_name, float(value))
    summary["tables_written"].append("metric_history")

    # ── 3. renewal_pipeline ───────────────────────────────────────────────────
    renewal_list = snapshot.get("renewal_pipeline_list", [])
    for row in renewal_list:
        lease_id = str(row.get("lease_id", ""))
        if not lease_id:
            continue
        database.upsert_renewal(lease_id, {
            "tenant_name":   row.get("tenant_name", "Unknown"),
            "unit_label":    row.get("unit_label", ""),
            "property_name": row.get("property_name", ""),
            "lease_end_date": row.get("lease_end_date", ""),
            "monthly_rent":  float(row.get("monthly_rent") or 0),
            "risk_score":    int(row.get("risk_score") or 1),
            "status":        row.get("status", "not_started"),
            "notes":         row.get("notes"),
        })
    summary["renewals_written"] = len(renewal_list)
    summary["tables_written"].append("renewal_pipeline")

    # ── 4. Manual KPI overrides (google rating / maintenance satisfaction) ────
    if snapshot.get("google_rating") is not None:
        database.set_manual_kpi(
            "google_rating",
            float(snapshot["google_rating"]),
            "set by sync.py from snapshot",
        )
    if snapshot.get("maintenance_satisfaction") is not None:
        database.set_manual_kpi(
            "maintenance_satisfaction",
            float(snapshot["maintenance_satisfaction"]),
            "set by sync.py from snapshot",
        )

    # ── 5. Fire/clear alerts ──────────────────────────────────────────────────
    _auto_clear_resolved_metric_alerts(snapshot)
    alerts_fired = _fire_alerts(snapshot)
    summary["alerts_fired"] = alerts_fired
    summary["tables_written"].append("alert_log")

    # ── 6. raw_kpi_data — the full API response payload ───────────────────────
    api_payload = _build_api_payload(snapshot, now)
    database.save_raw_kpi_data(today, api_payload)
    summary["tables_written"].append("raw_kpi_data")

    logger.info(f"sync_snapshot complete: {summary}")
    print(f"[sync] {today} — KPIs saved. Alerts fired: {alerts_fired}. Renewals: {len(renewal_list)}.")
    return summary


def _build_api_payload(snapshot: dict, refreshed_at: str) -> dict:
    """
    Build the full dict that /api/kpis returns. Mirrors the shape that
    kpi.compute_all_kpis() produces so the frontend sees a consistent format.
    """
    total_units = snapshot.get("total_units", 120)
    active_leases = snapshot.get("active_leases", 0)
    vacant_units = snapshot.get("vacant_units", total_units - active_leases)

    rent_pct = snapshot.get("rent_collected_pct", 0.0)
    rent_usd = snapshot.get("rent_collected_usd", 0.0)
    rent_exp = snapshot.get("rent_expected_usd", 0.0)

    return {
        "rent_collected": {
            "pct": rent_pct,
            "collected_usd": rent_usd,
            "expected_usd": rent_exp,
            "delinquent_leases": snapshot.get("delinquent_leases", []),
        },
        "occupancy": {
            "pct": snapshot.get("occupancy_pct", 0.0),
            "occupied": active_leases,
            "total": total_units,
            "vacant_units": snapshot.get("vacant_unit_list", []),
        },
        "days_on_market": {
            "avg_days": snapshot.get("avg_days_on_market", 0.0),
            "vacant_units": snapshot.get("vacant_unit_list", []),
        },
        "renewal_rate": {
            "pct": snapshot.get("renewal_rate_pct") or 0.0,
            "signed": 0,
            "total_expired": 0,
            "pipeline": snapshot.get("renewal_pipeline_list", []),
        },
        "speed_of_repair": {
            "avg_days_to_close": snapshot.get("speed_of_repair_days", 0.0),
            "open_count": snapshot.get("open_work_orders", 0),
            "overdue_count": snapshot.get("overdue_work_orders", 0),
            "open_work_orders": snapshot.get("open_work_order_list", []),
            "overdue_work_orders": snapshot.get("overdue_work_order_list", []),
        },
        "vacancy_cost_clock": _build_vacancy_clock(snapshot),
        "at_risk_tenants": snapshot.get("at_risk_tenants", []),
        "owner_health": snapshot.get("owner_health", []),
        "turnover_cost": {"avg_cost": 0, "total_cost": 0, "units": []},
        "inspection_compliance": snapshot.get("inspection_compliance", []),
        "maintenance_satisfaction": snapshot.get("maintenance_satisfaction") or 0,
        "google_rating": snapshot.get("google_rating") or 0,
        "delinquent_count": snapshot.get("delinquent_count", 0),
        "open_work_orders_count": snapshot.get("open_work_orders", 0),
        "overdue_work_orders_count": snapshot.get("overdue_work_orders", 0),
        "total_units": total_units,
        "active_leases": active_leases,
        "vacant_units_count": vacant_units,
        "refreshed_at": refreshed_at,
    }


def _build_vacancy_clock(snapshot: dict) -> list:
    """Convert vacant_unit_list to vacancy_cost_clock format."""
    result = []
    for unit in snapshot.get("vacant_unit_list", []):
        days = unit.get("days_vacant", 0)
        daily = unit.get("daily_rent_estimate", 0.0)
        result.append({
            "unit_id":      unit.get("unit_id", ""),
            "property_name": unit.get("property_name", ""),
            "unit_label":   unit.get("unit_label", ""),
            "days_vacant":  days,
            "daily_cost":   daily,
            "total_loss":   round(days * daily, 2),
        })
    return sorted(result, key=lambda x: x["total_loss"], reverse=True)


def _fire_alerts(snapshot: dict) -> int:
    """Fire threshold-based alerts and return count of new alerts."""
    thresholds = database.get_thresholds()
    fired = 0

    scalar_checks = [
        ("rent_collected_pct",      snapshot.get("rent_collected_pct", 0)),
        ("occupancy_pct",           snapshot.get("occupancy_pct", 0)),
        ("avg_days_on_market",      snapshot.get("avg_days_on_market", 0)),
        ("renewal_rate_pct",        snapshot.get("renewal_rate_pct") or 0),
        ("speed_of_repair_days",    snapshot.get("speed_of_repair_days", 0)),
        ("maintenance_satisfaction", snapshot.get("maintenance_satisfaction") or 0),
        ("google_rating",           snapshot.get("google_rating") or 0),
    ]
    for metric_name, value in scalar_checks:
        cfg = thresholds.get(metric_name)
        if not cfg or not value:
            continue
        direction = cfg["direction"]
        crit = cfg["critical_value"]
        warn = cfg["warning_value"]
        if direction == "below":
            if value < crit:
                aid = database.fire_alert(f"{metric_name}_critical",
                    f"{metric_name} is {value} — below critical threshold of {crit}", "CRITICAL")
                if aid:
                    fired += 1
            elif value < warn:
                aid = database.fire_alert(f"{metric_name}_warn",
                    f"{metric_name} is {value} — below warning threshold of {warn}", "WARN")
                if aid:
                    fired += 1
        else:
            if value > crit:
                aid = database.fire_alert(f"{metric_name}_critical",
                    f"{metric_name} is {value} — above critical threshold of {crit}", "CRITICAL")
                if aid:
                    fired += 1
            elif value > warn:
                aid = database.fire_alert(f"{metric_name}_warn",
                    f"{metric_name} is {value} — above warning threshold of {warn}", "WARN")
                if aid:
                    fired += 1

    # Overdue work order alerts
    for wo in snapshot.get("overdue_work_order_list", []):
        wo_id = str(wo.get("wo_id", ""))
        days = wo.get("days_open", 0)
        desc = str(wo.get("description", ""))[:60]
        prop = wo.get("property_name", "")
        severity = "CRITICAL" if days > 14 else "WARN"
        aid = database.fire_alert(
            "overdue_work_order",
            f"WO #{wo_id} overdue {days} days — {desc} at {prop}",
            severity,
            work_order_id=wo_id,
        )
        if aid:
            fired += 1

    # Vacant unit alerts (21+ days)
    for unit in snapshot.get("vacant_unit_list", []):
        days = unit.get("days_vacant", 0)
        if days >= 21:
            uid = str(unit.get("unit_id", ""))
            label = unit.get("unit_label", uid)
            prop = unit.get("property_name", "")
            loss = round(days * unit.get("daily_rent_estimate", 0), 0)
            aid = database.fire_alert(
                "unit_vacancy",
                f"{label} at {prop} vacant {days} days — ${loss:.0f} lost",
                "WARN",
                unit_id=uid,
            )
            if aid:
                fired += 1

    # Renewal no-contact alerts
    today_str = date.today().isoformat()
    for row in snapshot.get("renewal_pipeline_list", []):
        if row.get("status", "not_started") == "not_started":
            end = row.get("lease_end_date", "")
            if end and end <= today_str:
                continue  # already expired
            try:
                days_left = (
                    date.fromisoformat(end[:10]) - date.today()
                ).days if end else 999
            except Exception:
                days_left = 999
            if days_left < 30:
                lease_id = str(row.get("lease_id", ""))
                aid = database.fire_alert(
                    "renewal_no_contact",
                    f"Lease for {row.get('tenant_name','')} at {row.get('unit_label','')} "
                    f"expires in {days_left} days — no renewal started",
                    "CRITICAL",
                    lease_id=lease_id,
                )
                if aid:
                    fired += 1

    return fired


def _auto_clear_resolved_metric_alerts(snapshot: dict) -> int:
    """
    Clear any active metric-level alerts whose condition is now resolved.
    Called by sync_snapshot after _fire_alerts so stale alerts don't accumulate.
    """
    thresholds = database.get_thresholds()
    cleared = 0

    metric_values = {
        "rent_collected_pct":       snapshot.get("rent_collected_pct"),
        "occupancy_pct":            snapshot.get("occupancy_pct"),
        "avg_days_on_market":       snapshot.get("avg_days_on_market"),
        "renewal_rate_pct":         snapshot.get("renewal_rate_pct"),
        "speed_of_repair_days":     snapshot.get("speed_of_repair_days"),
        "maintenance_satisfaction": snapshot.get("maintenance_satisfaction"),
        "google_rating":            snapshot.get("google_rating"),
    }

    import sqlite3
    conn = sqlite3.connect(database.DB_PATH)
    try:
        for metric, value in metric_values.items():
            if value is None:
                continue
            cfg = thresholds.get(metric)
            if not cfg:
                continue
            direction = cfg["direction"]
            warn = cfg["warning_value"]
            # If value is now healthy (above warning for "below" metrics, below warning for "above"),
            # clear any active alerts for this metric.
            is_healthy = (
                (direction == "below" and value >= warn) or
                (direction == "above" and value <= warn)
            )
            if is_healthy:
                cur = conn.execute(
                    """
                    UPDATE alert_log SET cleared_at=datetime('now'), cleared_by='sync_auto_clear'
                    WHERE cleared_at IS NULL
                      AND (alert_type=? OR alert_type=?)
                    """,
                    (f"{metric}_critical", f"{metric}_warn"),
                )
                cleared += cur.rowcount
        conn.commit()
    finally:
        conn.close()

    return cleared


# ── Command-line entry point ───────────────────────────────────────────────────

def _main():
    """Run sync from a JSON snapshot file: python -m backend.sync --file path.json"""
    import argparse
    parser = argparse.ArgumentParser(description="Sync Rentvine MCP snapshot to SQLite")
    parser.add_argument("--file", required=True, help="Path to snapshot JSON file")
    args = parser.parse_args()

    with open(args.file) as f:
        snapshot = json.load(f)

    database.init_db()
    result = sync_snapshot(snapshot)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    _main()
