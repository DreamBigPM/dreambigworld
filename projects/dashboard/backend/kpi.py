"""
kpi.py — KPI computation logic for Dream Big PM Dashboard.

All functions are async and pull live data from Rentvine.
Results are saved to SQLite for trend lines and caching.
"""

import asyncio
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from backend import rentvine, database, rentvine_mcp

logger = logging.getLogger(__name__)

_MONTH_START = date.today().replace(day=1).isoformat()
_TODAY = date.today().isoformat()


def _today() -> str:
    return date.today().isoformat()


def _month_start() -> str:
    return date.today().replace(day=1).isoformat()


def _days_between(start_str: Optional[str], end_str: Optional[str] = None) -> int:
    if not start_str:
        return 0
    try:
        start = date.fromisoformat(start_str[:10])
        end = date.fromisoformat(end_str[:10]) if end_str else date.today()
        return max(0, (end - start).days)
    except Exception:
        return 0


async def compute_rent_collected() -> dict:
    """Rent collected % for the current month."""
    try:
        leases, transactions = await asyncio.gather(
            rentvine.fetch_leases(status="active"),
            rentvine.fetch_transactions(
                start_date=_month_start(), end_date=_today()
            ),
        )

        # Sum charges due this month across active leases
        expected_usd = 0.0
        for lease in leases:
            rent = lease.get("monthlyRent") or lease.get("rent") or 0
            expected_usd += float(rent)

        # Sum payments received this month
        collected_usd = 0.0
        for txn in transactions:
            txn_type = (txn.get("type") or txn.get("transactionType") or "").lower()
            if "payment" in txn_type or "receipt" in txn_type:
                collected_usd += float(txn.get("amount") or 0)

        pct = (collected_usd / expected_usd * 100) if expected_usd > 0 else 0.0

        # Build delinquent list
        delinquent_leases = []
        for lease in leases:
            balance_data = await rentvine.fetch_lease_balance(
                str(lease.get("id") or lease.get("leaseId") or "")
            )
            balance = float(
                balance_data.get("balance") or balance_data.get("balanceDue") or 0
            )
            if balance > 0:
                delinquent_leases.append({
                    "lease_id": lease.get("id"),
                    "tenant_name": lease.get("tenantName") or lease.get("primaryTenant") or "Unknown",
                    "unit": lease.get("unitLabel") or lease.get("unit") or "",
                    "property": lease.get("propertyName") or lease.get("property") or "",
                    "balance": balance,
                    "days_late": _days_between(
                        lease.get("lastPaymentDate") or _month_start()
                    ),
                    "last_payment_date": lease.get("lastPaymentDate") or "",
                })

        return {
            "pct": round(pct, 1),
            "collected_usd": round(collected_usd, 2),
            "expected_usd": round(expected_usd, 2),
            "delinquent_leases": delinquent_leases,
        }
    except Exception as e:
        logger.error(f"compute_rent_collected failed: {e}")
        return {"pct": 0, "collected_usd": 0, "expected_usd": 0, "delinquent_leases": [], "error": str(e)}


async def compute_occupancy() -> dict:
    """Physical occupancy rate."""
    try:
        units, vacancy_list = await asyncio.gather(
            rentvine.fetch_units(),
            rentvine_mcp.fetch_vacancy(),
        )

        total = len(units)
        # fetch_vacancy() is the authoritative source for vacant units — it returns
        # real street addresses and correct days_vacant from the Rentvine vacancy report.
        vacant_units = [
            {
                "unit_id": v["unit_id"],
                "property_name": v["property_name"],
                "unit_label": v["unit_label"],
                "days_vacant": v["days_vacant"],
                "daily_rent_estimate": v["daily_cost"],
            }
            for v in vacancy_list
        ]

        occupied = total - len(vacant_units)
        pct = (occupied / total * 100) if total > 0 else 0.0

        return {
            "pct": round(pct, 1),
            "occupied": occupied,
            "total": total,
            "vacant_units": vacant_units,
        }
    except Exception as e:
        logger.error(f"compute_occupancy failed: {e}")
        return {"pct": 0, "occupied": 0, "total": 0, "vacant_units": [], "error": str(e)}


async def compute_days_on_market() -> dict:
    """Average days on market for currently vacant units."""
    try:
        occ = await compute_occupancy()
        vacant = occ.get("vacant_units", [])

        dom_values = [v["days_vacant"] for v in vacant if v["days_vacant"] > 0]
        avg_days = sum(dom_values) / len(dom_values) if dom_values else 0.0

        return {
            "avg_days": round(avg_days, 1),
            "vacant_units": vacant,
        }
    except Exception as e:
        logger.error(f"compute_days_on_market failed: {e}")
        return {"avg_days": 0, "vacant_units": [], "error": str(e)}


async def compute_renewal_rate() -> dict:
    """
    Lease renewal rate using startDate vs moveInDate heuristic.

    For each lease that expired in the evaluation window, find the next active
    lease on the same unit. If that lease's startDate != moveInDate, the same
    tenant renewed. If startDate == moveInDate, a new tenant moved in — that
    expiration is excluded from the calc entirely (not a renewal opportunity).
    Units with no subsequent lease count as failed renewals (in denominator only).

    Returns monthly_pct (last completed calendar month) and rolling12_pct
    (trailing 365 days). headline pct = monthly if available, else rolling12.
    """
    try:
        leases = await rentvine.fetch_leases()
        pipeline_rows = database.get_renewal_pipeline()

        today = date.today()
        first_of_this_month = today.replace(day=1)
        last_of_prev_month = first_of_this_month - timedelta(days=1)
        first_of_prev_month = last_of_prev_month.replace(day=1)
        rolling_start = (today - timedelta(days=365)).isoformat()
        yesterday = (today - timedelta(days=1)).isoformat()

        # Group and sort leases by unit
        by_unit: dict = defaultdict(list)
        for lease in leases:
            uid = str(lease.get("unitId") or lease.get("unit_id") or "")
            if uid:
                by_unit[uid].append(lease)
        for uid in by_unit:
            by_unit[uid].sort(key=lambda l: l.get("startDate") or "")

        def _classify(window_start: str, window_end: str):
            renewed = 0
            total = 0
            for uid, unit_leases in by_unit.items():
                for i, lease in enumerate(unit_leases):
                    end = lease.get("endDate") or ""
                    if not (window_start <= end <= window_end):
                        continue
                    next_lease = unit_leases[i + 1] if i + 1 < len(unit_leases) else None
                    if next_lease:
                        start = next_lease.get("startDate") or ""
                        move_in = next_lease.get("moveInDate") or ""
                        if not start or not move_in:
                            continue  # can't determine — skip
                        if start == move_in:
                            continue  # new tenant — exclude from calc
                        # startDate != moveInDate → same tenant renewed
                        renewed += 1
                        total += 1
                    else:
                        # Unit vacant after expiration → failed renewal
                        total += 1
            return renewed, total

        m_renewed, m_total = _classify(
            first_of_prev_month.isoformat(),
            last_of_prev_month.isoformat(),
        )
        r_renewed, r_total = _classify(rolling_start, yesterday)

        monthly_pct = round(m_renewed / m_total * 100, 1) if m_total > 0 else None
        rolling12_pct = round(r_renewed / r_total * 100, 1) if r_total > 0 else None
        headline_pct = monthly_pct if monthly_pct is not None else rolling12_pct

        return {
            "pct": headline_pct,
            "monthly_pct": monthly_pct,
            "rolling12_pct": rolling12_pct,
            "monthly_signed": m_renewed,
            "monthly_expired": m_total,
            "rolling12_signed": r_renewed,
            "rolling12_expired": r_total,
            "pipeline": pipeline_rows,
        }
    except Exception as e:
        logger.error(f"compute_renewal_rate failed: {e}")
        return {
            "pct": None,
            "monthly_pct": None,
            "rolling12_pct": None,
            "monthly_signed": 0,
            "monthly_expired": 0,
            "rolling12_signed": 0,
            "rolling12_expired": 0,
            "pipeline": [],
            "error": str(e),
        }


async def _get_renewal_pipeline():
    return database.get_renewal_pipeline()


async def compute_speed_of_repair() -> dict:
    """Average days to close work orders; open and overdue counts."""
    try:
        work_orders = await rentvine.fetch_work_orders()

        open_wos = []
        overdue_wos = []
        closed_days = []

        for wo in work_orders:
            status = (wo.get("status") or wo.get("statusName") or "").lower()
            opened = wo.get("openedDate") or wo.get("createdDate") or wo.get("createdAt") or ""
            closed = wo.get("closedDate") or wo.get("completedDate") or ""
            days_open = _days_between(opened, closed if closed else None)

            wo_record = {
                "wo_id": wo.get("id") or wo.get("workOrderId"),
                "description": wo.get("description") or wo.get("title") or "No description",
                "property_name": wo.get("propertyName") or wo.get("property") or "",
                "unit": wo.get("unitLabel") or wo.get("unit") or "",
                "vendor": wo.get("vendorName") or wo.get("vendor") or "Unassigned",
                "days_open": days_open,
                "status": status,
            }

            if not closed or status in ("open", "new", "in progress", "in_progress", "pending"):
                open_wos.append(wo_record)
                if days_open > 3:
                    overdue_wos.append(wo_record)
            elif closed:
                closed_days.append(days_open)

        avg_days_to_close = (
            round(sum(closed_days) / len(closed_days), 1) if closed_days else 0.0
        )

        return {
            "avg_days_to_close": avg_days_to_close,
            "open_count": len(open_wos),
            "overdue_count": len(overdue_wos),
            "open_work_orders": sorted(open_wos, key=lambda x: x["days_open"], reverse=True),
            "overdue_work_orders": sorted(overdue_wos, key=lambda x: x["days_open"], reverse=True),
        }
    except Exception as e:
        logger.error(f"compute_speed_of_repair failed: {e}")
        return {
            "avg_days_to_close": 0,
            "open_count": 0,
            "overdue_count": 0,
            "open_work_orders": [],
            "overdue_work_orders": [],
            "error": str(e),
        }


async def compute_vacancy_cost_clock() -> list:
    """Running dollar cost of each vacant unit."""
    try:
        occ = await compute_occupancy()
        result = []
        for unit in occ.get("vacant_units", []):
            days = unit["days_vacant"]
            daily = unit["daily_rent_estimate"]
            result.append({
                "unit_id": unit["unit_id"],
                "property_name": unit["property_name"],
                "unit_label": unit["unit_label"],
                "days_vacant": days,
                "daily_cost": daily,
                "total_loss": round(days * daily, 2),
            })
        return sorted(result, key=lambda x: x["total_loss"], reverse=True)
    except Exception as e:
        logger.error(f"compute_vacancy_cost_clock failed: {e}")
        return []


async def compute_at_risk_scores() -> list:
    """Top 10 at-risk tenants scored on delinquency, lease expiry, and maintenance."""
    try:
        leases, work_orders = await asyncio.gather(
            rentvine.fetch_leases(status="active"),
            rentvine.fetch_work_orders(),
        )

        ninety_days_ago = (date.today() - timedelta(days=90)).isoformat()
        sixty_days_out = (date.today() + timedelta(days=60)).isoformat()

        # Build WO count per unit for last 90 days
        wo_count_by_unit = {}
        for wo in work_orders:
            opened = wo.get("openedDate") or wo.get("createdDate") or ""
            if opened >= ninety_days_ago:
                uid = str(wo.get("unitId") or wo.get("unit_id") or "")
                wo_count_by_unit[uid] = wo_count_by_unit.get(uid, 0) + 1

        scored = []
        for lease in leases:
            score = 0
            risk_factors = []
            unit_id = str(lease.get("unitId") or lease.get("unit_id") or "")

            # Balance due check
            balance_data = await rentvine.fetch_lease_balance(
                str(lease.get("id") or "")
            )
            balance = float(balance_data.get("balance") or balance_data.get("balanceDue") or 0)
            if balance > 0:
                score += 2
                risk_factors.append(f"${balance:.0f} past due")
            if balance > 500:
                score += 1
                risk_factors.append("balance over $500")

            # Lease expiry
            end_date = lease.get("endDate") or lease.get("leaseEndDate") or ""
            if end_date and end_date <= sixty_days_out:
                score += 1
                risk_factors.append(f"lease ends {end_date}")

            # High maintenance
            wo_count = wo_count_by_unit.get(unit_id, 0)
            if wo_count > 3:
                score += 1
                risk_factors.append(f"{wo_count} WOs in 90 days")

            if score > 0:
                scored.append({
                    "lease_id": lease.get("id"),
                    "tenant_name": lease.get("tenantName") or lease.get("primaryTenant") or "Unknown",
                    "unit": lease.get("unitLabel") or lease.get("unit") or "",
                    "property": lease.get("propertyName") or lease.get("property") or "",
                    "score": score,
                    "risk_factors": risk_factors,
                })

        return sorted(scored, key=lambda x: x["score"], reverse=True)[:10]
    except Exception as e:
        logger.error(f"compute_at_risk_scores failed: {e}")
        return []


async def compute_owner_health_scores() -> list:
    """Owner health scores based on open WOs >30 days."""
    try:
        owners, work_orders = await asyncio.gather(
            rentvine.fetch_owners(),
            rentvine.fetch_work_orders(),
        )

        # Map work orders to properties — find old open ones
        thirty_days_ago = (date.today() - timedelta(days=30)).isoformat()
        old_open_wos_by_property = {}
        for wo in work_orders:
            status = (wo.get("status") or wo.get("statusName") or "").lower()
            opened = wo.get("openedDate") or wo.get("createdDate") or ""
            closed = wo.get("closedDate") or wo.get("completedDate") or ""
            if not closed and opened and opened <= thirty_days_ago:
                prop_id = str(wo.get("propertyId") or wo.get("property_id") or "")
                old_open_wos_by_property.setdefault(prop_id, 0)
                old_open_wos_by_property[prop_id] += 1

        results = []
        for owner in owners:
            score = 100
            deductions = []

            # Check if any of their properties have old open WOs
            owner_properties = owner.get("properties") or owner.get("propertyIds") or []
            for prop_id in owner_properties:
                count = old_open_wos_by_property.get(str(prop_id), 0)
                if count > 0:
                    score -= 40
                    deductions.append(f"{count} work order(s) open >30 days")
                    break

            results.append({
                "owner_id": owner.get("id") or owner.get("ownerId"),
                "owner_name": f"{owner.get('firstName', '')} {owner.get('lastName', '')}".strip()
                    or owner.get("name") or "Unknown",
                "score": max(0, score),
                "deductions": deductions,
            })

        return sorted(results, key=lambda x: x["score"])
    except Exception as e:
        logger.error(f"compute_owner_health_scores failed: {e}")
        return []


async def compute_turnover_cost() -> dict:
    """Average turnover cost for units that turned in the last 12 months."""
    try:
        one_year_ago = (date.today() - timedelta(days=365)).isoformat()
        leases, bills = await asyncio.gather(
            rentvine.fetch_leases(),
            rentvine.fetch_bills(start_date=one_year_ago),
        )

        # Find leases that started in the last year (these are "turns")
        turned_leases = [
            l for l in leases
            if (l.get("startDate") or l.get("leaseStartDate") or "") >= one_year_ago
        ]

        unit_costs = []
        bills_by_unit = {}
        for bill in bills:
            uid = str(bill.get("unitId") or bill.get("unit_id") or "")
            amount = float(bill.get("amount") or bill.get("total") or 0)
            bills_by_unit[uid] = bills_by_unit.get(uid, 0) + amount

        for lease in turned_leases:
            unit_id = str(lease.get("unitId") or lease.get("unit_id") or "")
            monthly_rent = float(lease.get("monthlyRent") or lease.get("rent") or 0)
            daily_rent = monthly_rent / 30 if monthly_rent else 0

            # Estimate vacancy days from prior lease end to this lease start
            start = lease.get("startDate") or lease.get("leaseStartDate") or ""
            vacancy_days = 30  # default estimate if no prior lease data
            vacancy_cost = round(vacancy_days * daily_rent, 2)
            make_ready_cost = round(bills_by_unit.get(unit_id, 0), 2)
            total_cost = vacancy_cost + make_ready_cost

            unit_costs.append({
                "unit_id": unit_id,
                "unit_label": lease.get("unitLabel") or lease.get("unit") or "",
                "property": lease.get("propertyName") or lease.get("property") or "",
                "vacancy_days": vacancy_days,
                "vacancy_cost": vacancy_cost,
                "make_ready_cost": make_ready_cost,
                "total_cost": total_cost,
            })

        avg_cost = (
            round(sum(u["total_cost"] for u in unit_costs) / len(unit_costs), 2)
            if unit_costs else 0.0
        )
        total_cost = round(sum(u["total_cost"] for u in unit_costs), 2)

        return {
            "avg_cost": avg_cost,
            "total_cost": total_cost,
            "units": sorted(unit_costs, key=lambda x: x["total_cost"], reverse=True),
        }
    except Exception as e:
        logger.error(f"compute_turnover_cost failed: {e}")
        return {"avg_cost": 0, "total_cost": 0, "units": [], "error": str(e)}


async def compute_inspection_compliance() -> list:
    """Inspection compliance status per property."""
    try:
        properties, inspections = await asyncio.gather(
            rentvine.fetch_properties(),
            rentvine.fetch_inspections(),
        )

        # Map latest inspection per property
        latest_by_property = {}
        for insp in inspections:
            prop_id = str(insp.get("propertyId") or insp.get("property_id") or "")
            insp_date = insp.get("inspectionDate") or insp.get("date") or insp.get("completedDate") or ""
            if prop_id and insp_date > latest_by_property.get(prop_id, ""):
                latest_by_property[prop_id] = insp_date

        results = []
        for prop in properties:
            prop_id = str(prop.get("id") or prop.get("propertyId") or "")
            last_date = latest_by_property.get(prop_id)
            days_since = _days_between(last_date) if last_date else 9999

            if days_since < 300:
                status = "Current"
            elif days_since < 365:
                status = "Due Soon"
            else:
                status = "Overdue"

            results.append({
                "property_id": prop_id,
                "property_name": prop.get("name") or prop.get("address") or prop_id,
                "last_inspection_date": last_date or "Never",
                "days_since": days_since if last_date else None,
                "status": status,
            })

        return sorted(results, key=lambda x: (x["status"] == "Current", x["days_since"] or 9999), reverse=False)
    except Exception as e:
        logger.error(f"compute_inspection_compliance failed: {e}")
        return []


def load_kpis_from_db() -> Optional[dict]:
    """
    Return the most recently synced full KPI payload from raw_kpi_data, or
    None if no sync has been run yet. Used as the primary data source — the
    Rentvine REST API calls are a secondary fallback that may never succeed.
    """
    return database.get_latest_raw_kpi_data()


async def compute_all_kpis() -> dict:
    """Run all KPI computations in parallel and return combined result."""
    today = _today()

    (
        rent,
        occ,
        dom,
        renewal,
        repair,
        vacancy_clock,
        at_risk,
        owner_health,
        turnover,
        inspections,
        manual_satisfaction,
        manual_google,
    ) = await asyncio.gather(
        compute_rent_collected(),
        compute_occupancy(),
        compute_days_on_market(),
        compute_renewal_rate(),
        compute_speed_of_repair(),
        compute_vacancy_cost_clock(),
        compute_at_risk_scores(),
        compute_owner_health_scores(),
        compute_turnover_cost(),
        compute_inspection_compliance(),
        asyncio.coroutine(lambda: database.get_manual_kpi("maintenance_satisfaction"))(),
        asyncio.coroutine(lambda: database.get_manual_kpi("google_rating"))(),
    )

    kpis = {
        "rent_collected": rent,
        "occupancy": occ,
        "days_on_market": dom,
        "renewal_rate": renewal,
        "speed_of_repair": repair,
        "vacancy_cost_clock": vacancy_clock,
        "at_risk_tenants": at_risk,
        "owner_health": owner_health,
        "turnover_cost": turnover,
        "inspection_compliance": inspections,
        "maintenance_satisfaction": manual_satisfaction or 0,
        "google_rating": manual_google or 0,
        "refreshed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }

    # Save snapshot to SQLite
    try:
        database.save_kpi_snapshot({
            "snapshot_date": today,
            "rent_collected_pct": rent.get("pct"),
            "occupancy_pct": occ.get("pct"),
            "avg_days_on_market": dom.get("avg_days"),
            "renewal_rate_pct": renewal.get("pct"),
            "speed_of_repair_days": repair.get("avg_days_to_close"),
            "maintenance_satisfaction": manual_satisfaction,
            "google_rating": manual_google,
        })

        # Save metric history for sparklines
        for metric, value in [
            ("rent_collected_pct", rent.get("pct")),
            ("occupancy_pct", occ.get("pct")),
            ("avg_days_on_market", dom.get("avg_days")),
            ("renewal_rate_pct", renewal.get("pct")),
            ("speed_of_repair_days", repair.get("avg_days_to_close")),
        ]:
            if value is not None:
                database.save_metric(today, metric, value)
    except Exception as e:
        logger.error(f"Failed to save KPI snapshot: {e}")

    # Fire/clear alerts based on thresholds
    try:
        _check_and_fire_alerts(kpis)
    except Exception as e:
        logger.error(f"Alert check failed: {e}")

    return kpis


def _check_and_fire_alerts(kpis: dict):
    """Fire alerts for KPIs that breach thresholds."""
    thresholds = database.get_thresholds()

    checks = [
        ("rent_collected_pct", kpis["rent_collected"].get("pct", 0)),
        ("occupancy_pct", kpis["occupancy"].get("pct", 0)),
        ("avg_days_on_market", kpis["days_on_market"].get("avg_days", 0)),
        ("renewal_rate_pct", kpis["renewal_rate"].get("pct", 0)),
        ("speed_of_repair_days", kpis["speed_of_repair"].get("avg_days_to_close", 0)),
        ("maintenance_satisfaction", kpis.get("maintenance_satisfaction", 0)),
        ("google_rating", kpis.get("google_rating", 0)),
    ]

    for metric_name, value in checks:
        cfg = thresholds.get(metric_name)
        if not cfg or value is None:
            continue

        direction = cfg["direction"]
        crit = cfg["critical_value"]
        warn = cfg["warning_value"]

        if direction == "below":
            if value < crit:
                database.fire_alert(
                    alert_type=f"{metric_name}_critical",
                    message=f"{metric_name} is {value} — below critical threshold of {crit}",
                    severity="CRITICAL",
                )
            elif value < warn:
                database.fire_alert(
                    alert_type=f"{metric_name}_warn",
                    message=f"{metric_name} is {value} — below warning threshold of {warn}",
                    severity="WARN",
                )
        else:
            if value > crit:
                database.fire_alert(
                    alert_type=f"{metric_name}_critical",
                    message=f"{metric_name} is {value} — above critical threshold of {crit}",
                    severity="CRITICAL",
                )
            elif value > warn:
                database.fire_alert(
                    alert_type=f"{metric_name}_warn",
                    message=f"{metric_name} is {value} — above warning threshold of {warn}",
                    severity="WARN",
                )

    # Overdue work order alerts
    for wo in kpis["speed_of_repair"].get("overdue_work_orders", []):
        database.fire_alert(
            alert_type="overdue_work_order",
            message=f"WO #{wo['wo_id']} overdue {wo['days_open']} days — {wo['description'][:60]} at {wo['property_name']}",
            severity="CRITICAL" if wo["days_open"] > 14 else "WARN",
            work_order_id=str(wo["wo_id"]),
        )

    # Vacant unit alerts (21+ days)
    for unit in kpis["vacancy_cost_clock"]:
        if unit["days_vacant"] >= 21:
            database.fire_alert(
                alert_type="unit_vacancy",
                message=f"{unit['unit_label']} at {unit['property_name']} vacant {unit['days_vacant']} days — ${unit['total_loss']:.0f} lost",
                severity="WARN",
                unit_id=str(unit["unit_id"]),
            )

    # Renewal pipeline — no contact started
    for row in kpis["renewal_rate"].get("pipeline", []):
        if row.get("status") == "not_started":
            end = row.get("lease_end_date") or ""
            days_left = _days_between(_today(), end) if end else 999
            if days_left < 30:
                database.fire_alert(
                    alert_type="renewal_no_contact",
                    message=f"Lease for {row['tenant_name']} at {row['unit_label']} expires in {days_left} days — no renewal started",
                    severity="CRITICAL",
                    lease_id=str(row.get("lease_id", "")),
                )
