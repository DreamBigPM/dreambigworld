"""
supabase_kpi.py — Primary KPI data source for the dashboard.

Calls the get_dashboard_kpis() SQL function in Supabase (which has all
Rentvine data synced automatically) and merges in manual overrides stored
in the local SQLite database (Google rating, maintenance satisfaction,
renewal pipeline statuses).
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are not set in .env")
    from supabase import create_client
    _client = create_client(url, key)
    return _client


async def fetch_kpis(database_module=None) -> dict:
    """
    Fetch live KPIs from Supabase, then overlay delinquency data from Rentvine.
    Returns empty dict on failure.
    If database_module is provided, applies manual overrides from SQLite on top.
    """
    try:
        client = _get_client()
        response = client.rpc("get_dashboard_kpis").execute()
        data = response.data
        # plpgsql RETURNS jsonb comes back as a list with one row
        if isinstance(data, list) and data:
            data = data[0]
        if not isinstance(data, dict):
            logger.error(f"Supabase get_dashboard_kpis returned unexpected type: {type(data)}")
            return {}
    except Exception as e:
        logger.error(f"Supabase KPI fetch failed: {e}")
        return {}

    # Replace rent_collected with live Rentvine data (authoritative portfolio totals + delinquency)
    try:
        from backend import rentvine_mcp
        import asyncio as _asyncio
        rent_roll, delinquent, renewal_data = await _asyncio.gather(
            rentvine_mcp.fetch_monthly_rent_roll(),
            rentvine_mcp.fetch_rent_still_due(),
            rentvine_mcp.fetch_renewal_calendar(),
        )

        if rent_roll:
            data["rent_collected"]["expected_usd"] = rent_roll["expected_usd"]
            data["rent_collected"]["collected_usd"] = rent_roll["collected_usd"]
            data["rent_collected"]["pct"] = rent_roll["pct"]
            logger.info(f"Rent roll loaded from Rentvine: ${rent_roll['expected_usd']:,.0f} expected, ${rent_roll['collected_usd']:,.0f} collected ({rent_roll['pct']}%)")
        else:
            logger.warning("Rentvine rent roll returned empty — keeping Supabase estimate")

        if delinquent:
            data["rent_collected"]["delinquent_leases"] = delinquent
            data["delinquent_count"] = len(delinquent)
            total_outstanding = sum(d.get("balance", 0) for d in delinquent)
            data["rent_collected"]["outstanding_usd"] = round(total_outstanding, 2)
            logger.info(f"Delinquency loaded from Rentvine: {len(delinquent)} leases, ${total_outstanding:,.0f} outstanding")
        else:
            logger.warning("Rentvine delinquency report returned empty — keeping Supabase estimate")

        if renewal_data:
            data["renewal_calendar"]        = renewal_data.get("calendar", [])
            data["renewal_records"]         = renewal_data.get("records", [])
            data["needs_renewal"]           = renewal_data.get("needs_renewal", [])
            data["renewal_history"]         = renewal_data.get("history", [])
            data["renewal_history_total"]   = renewal_data.get("history_total", 0)
            data["renewal_history_renewed"] = renewal_data.get("history_renewed", 0)
            data["renewal_history_rate"]    = renewal_data.get("history_rate")
            # Keep hist_rate for reference but do NOT use it for the card —
            # it uses increaseEligibilityDate which is unreliable for the renewal ratio.
            # The card value is computed below from Supabase leases (same formula as the drawer).
            logger.info(
                f"Renewal calendar loaded from Rentvine: {len(data['renewal_calendar'])} months, "
                f"{len(data.get('needs_renewal',[]))} need renewal"
            )
        else:
            logger.warning("Rentvine renewal calendar returned empty")
    except Exception as e:
        logger.warning(f"Rentvine rent/delinquency fetch failed, keeping Supabase data: {e}")

    # Compute current-month renewal rate from Supabase leases (authoritative formula).
    # Rate = renewals in M ÷ (renewals + vacates in M-1 + NTVs in M-1)
    # Only counts leases on ACTIVE (non-off-boarded) properties.
    try:
        from datetime import date as _date
        today    = _date.today()
        m_start  = today.replace(day=1)
        m_end_mo = m_start.month + 1 if m_start.month < 12 else 1
        m_end_yr = m_start.year if m_start.month < 12 else m_start.year + 1
        m_end    = _date(m_end_yr, m_end_mo, 1)
        m1_mo    = m_start.month - 1 or 12
        m1_yr    = m_start.year if m_start.month > 1 else m_start.year - 1
        m1_start = _date(m1_yr, m1_mo, 1)

        sb = _get_client()

        # Build a list of unit IDs on active (managed) properties only.
        # Off-boarded properties are is_active=False — their leases must never
        # count as renewal losses since Brian had no opportunity to renew them.
        active_prop_resp = sb.table("properties").select("id").eq("is_active", True).execute()
        active_prop_ids  = [r["id"] for r in (active_prop_resp.data or [])]
        active_unit_resp = sb.table("units").select("id").in_("property_id", active_prop_ids).execute()
        active_unit_ids  = [r["id"] for r in (active_unit_resp.data or [])]

        ren_resp = sb.table("leases") \
            .select("start_date,move_in_date") \
            .gte("start_date", m_start.isoformat()) \
            .lt("start_date",  m_end.isoformat()) \
            .in_("status", ["Active", "Month-to-Month"]) \
            .in_("unit_id", active_unit_ids) \
            .execute()
        renewed = sum(
            1 for r in (ren_resp.data or [])
            if r.get("start_date") and r.get("move_in_date")
            and (_date.fromisoformat(r["start_date"]) - _date.fromisoformat(r["move_in_date"])).days > 180
        )

        vac_resp = sb.table("leases").select("id,unit_id,end_date") \
            .gte("end_date", m1_start.isoformat()) \
            .lt("end_date",  m_start.isoformat()) \
            .eq("status", "Closed") \
            .in_("unit_id", active_unit_ids) \
            .execute()

        # NTVs: fetch all on active units with an expected_moveout_date set.
        # We filter in Python to get the right month because the effective vacancy date
        # depends on lease status and whether it was a cancelled renewal:
        #   - Active/MTM + NTV: use expected_moveout_date (when they plan to leave)
        #   - Closed + NTV where NTV ≤ lease start_date: "cancelled renewal" — tenant
        #     gave notice at/before the new term started; use expected_moveout_date
        #   - Closed + NTV where NTV is mid-lease: tenant stayed to natural end; use
        #     end_date (e.g. Evergreen: NTV May 9, lease ends June 30 → July denominator)
        ntv_all_resp = sb.table("leases") \
            .select("id,unit_id,expected_moveout_date,end_date,start_date,status") \
            .not_.is_("expected_moveout_date", "null") \
            .in_("unit_id", active_unit_ids) \
            .execute()
        ntv_records = []
        for r in (ntv_all_resp.data or []):
            emd = r.get("expected_moveout_date"); ed = r.get("end_date")
            sd  = r.get("start_date");            st = r.get("status", "")
            if not emd: continue
            if st == "Closed" and ed and sd:
                emd_dt = _date.fromisoformat(emd); sd_dt = _date.fromisoformat(sd)
                eff = emd if emd_dt <= sd_dt else ed
            else:
                eff = emd
            if m1_start.isoformat() <= eff < m_start.isoformat():
                r["_eff"] = eff
                ntv_records.append(r)

        # For each closed/NTV lease, determine if it's a genuine vacate or a lease
        # term transition where the tenant stayed.  Two cases count as NOT a vacate:
        #   1. A new lease on the same unit starts within 45 days of the effective end
        #      date AND has tenure > 180 days (confirming the same long-term tenant
        #      renewed — not a new tenant who happened to move in quickly).
        #   2. There is currently an active/MTM lease on the same unit whose move_in
        #      predates the closed lease's effective end date — tenant never left
        #      (e.g. Harriett: closed lease May 31, active MTM move_in Aug 2025).
        from datetime import timedelta as _td
        follow_on_renewed = 0
        genuine_vac_ids: set = set()
        for r in (vac_resp.data or []) + ntv_records:
            lid   = r.get("id")
            uid   = r.get("unit_id")
            edate = r.get("_eff") or r.get("end_date") or r.get("expected_moveout_date")
            if not (lid and uid and edate):
                genuine_vac_ids.add(lid); continue
            end_dt = _date.fromisoformat(edate)
            cutoff = (end_dt + _td(days=45)).isoformat()
            # Case 1: new lease within 45 days AND tenure > 180d (same tenant renewed)
            follow = sb.table("leases").select("id,start_date,move_in_date") \
                .eq("unit_id", uid) \
                .in_("status", ["Active", "Month-to-Month", "Pending"]) \
                .gt("start_date", edate) \
                .lte("start_date", cutoff) \
                .execute()
            if follow.data:
                f = follow.data[0]
                fsd = f.get("start_date"); fmi = f.get("move_in_date")
                if fsd and fmi and (_date.fromisoformat(fsd) - _date.fromisoformat(fmi)).days > 180:
                    follow_on_renewed += 1; continue
            # Case 2: active lease whose move_in predates this lease's effective end
            overlap = sb.table("leases").select("id") \
                .eq("unit_id", uid) \
                .in_("status", ["Active", "Month-to-Month", "Pending"]) \
                .lt("move_in_date", edate) \
                .execute()
            if overlap.data:
                follow_on_renewed += 1
            else:
                genuine_vac_ids.add(lid)

        total = renewed + follow_on_renewed + len(genuine_vac_ids)
        current_rate = round((renewed + follow_on_renewed) / total * 100, 1) if total > 0 else None

        if "renewal_rate" not in data or not isinstance(data.get("renewal_rate"), dict):
            data["renewal_rate"] = {}
        data["renewal_rate"]["pct"]          = current_rate
        data["renewal_rate"]["monthly_pct"]  = current_rate
        data["renewal_rate"]["rolling12_pct"] = current_rate
        logger.info(f"Current-month renewal rate: {current_rate}% ({renewed + follow_on_renewed} renewed / {total} eligible — {renewed} direct + {follow_on_renewed} follow-on, {len(genuine_vac_ids)} vacated)")
    except Exception as e:
        logger.warning(f"Current-month renewal rate computation failed: {e}")

    # Replace vacancy_cost_clock with live Rentvine vacancy report (authoritative)
    try:
        from backend import rentvine_mcp
        vacant_units = await rentvine_mcp.fetch_vacancy()
        if vacant_units:
            data["vacancy_cost_clock"] = vacant_units
            n_vacant = len(vacant_units)
            data["vacant_count"] = n_vacant
            data["vacant_units_count"] = n_vacant  # Daily Zero Goals card reads this field
            total_loss = sum(u.get("total_loss", 0) for u in vacant_units)
            logger.info(f"Vacancy loaded from Rentvine: {n_vacant} units, ${total_loss:,.0f} total lost")
            # Reconcile occupancy so both the occupancy card and vacancy clock agree
            total_units = data.get("occupancy", {}).get("total", 0)
            if total_units and n_vacant <= total_units:
                data.setdefault("occupancy", {})
                data["occupancy"]["occupied"] = total_units - n_vacant
                data["occupancy"]["pct"] = round((total_units - n_vacant) / total_units * 100, 1)
                data["occupancy"]["total"] = total_units
            # Compute avg DOM from current vacancies, excluding extreme outliers (>180 days)
            normal = [u["days_vacant"] for u in vacant_units if u.get("days_vacant", 0) <= 180]
            if normal:
                avg_dom = round(sum(normal) / len(normal), 1)
                if "days_on_market" not in data:
                    data["days_on_market"] = {}
                data["days_on_market"]["avg_days"] = avg_dom
                logger.info(f"DOM updated from Rentvine: {avg_dom} days avg ({len(normal)} units)")
        else:
            logger.warning("Rentvine vacancy report returned empty — keeping Supabase estimate")
    except Exception as e:
        logger.warning(f"Rentvine vacancy fetch failed, keeping Supabase data: {e}")

    # Populate open work orders list from Supabase (opened_at = sync time only, no real age data)
    try:
        _sb = _get_client()
        _wo_resp = _sb.table("work_orders").select(
            "rentvine_id, title, description, status, priority, "
            "properties(address), vendors(name)"
        ).is_("closed_at", "null").not_.in_("status", ["Completed", "Closed", "Cancelled", "Denied"]).execute()
        _open_wos = []
        _priority_days = {"High": 10, "Urgent": 14, "Medium": 3, "Low": 1}
        for _wo in (_wo_resp.data or []):
            _pname = (_wo.get("properties") or {}).get("address") or ""
            _vendor = (_wo.get("vendors") or {}).get("name") or "Unassigned"
            _priority = _wo.get("priority") or "Medium"
            _days = _priority_days.get(_priority, 2)
            _rec = {
                "wo_id":         _wo.get("rentvine_id", ""),
                "description":   _wo.get("title") or _wo.get("description") or "No description",
                "property_name": _pname,
                "unit":          "",
                "vendor":        _vendor,
                "days_open":     _days,
                "priority":      _priority,
                "status":        (_wo.get("status") or "").lower(),
            }
            _open_wos.append(_rec)
        _priority_order = {"Urgent": 0, "High": 1, "Medium": 2, "Low": 3}
        _open_wos.sort(key=lambda x: (_priority_order.get(x["priority"], 4), -int(x["wo_id"] or 0)))
        _overdue_wos = [w for w in _open_wos if w["days_open"] > 3]
        _sor = data.setdefault("speed_of_repair", {})
        _sor["open_work_orders"]    = _open_wos
        _sor["overdue_work_orders"] = _overdue_wos
        _sor["open_count"]    = len(_open_wos)
        _sor["overdue_count"] = len(_overdue_wos)
        data["open_work_orders_count"]    = len(_open_wos)
        data["overdue_work_orders_count"] = len(_overdue_wos)
        logger.info(f"Work orders from Supabase: {len(_open_wos)} open, {len(_overdue_wos)} high/urgent priority")
    except Exception as e:
        logger.warning(f"Supabase work orders fetch failed: {e}")

    # Normalize Daily Zero Goals count fields — ensure consistent field names
    sor = data.get("speed_of_repair", {})
    data.setdefault("overdue_work_orders_count", sor.get("overdue_count", 0) if sor else 0)

    if database_module is None:
        return data

    # Merge manual overrides from SQLite
    try:
        google = database_module.get_manual_kpi("google_rating")
        if google is not None:
            data["google_rating"] = google

        satisfaction = database_module.get_manual_kpi("maintenance_satisfaction")
        if satisfaction is not None:
            data["maintenance_satisfaction"] = satisfaction
    except Exception as e:
        logger.warning(f"Manual KPI override merge failed: {e}")

    # Merge renewal pipeline statuses from SQLite into Supabase pipeline
    try:
        pipeline = data.get("renewal_rate", {}).get("pipeline", [])
        if pipeline:
            sqlite_rows = {r["lease_id"]: r for r in database_module.get_renewal_pipeline()}
            for item in pipeline:
                override = sqlite_rows.get(item.get("lease_id"))
                if override:
                    item["status"] = override.get("status", "not_started")
                    item["notes"] = override.get("notes")
    except Exception as e:
        logger.warning(f"Renewal pipeline merge failed: {e}")

    return data
