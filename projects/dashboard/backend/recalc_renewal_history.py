"""
One-time script to recalculate all historical renewal rate months using the
corrected formula: active properties only, follow-on lease detection, 90-day
NTV window heuristic.

Run from the dashboard/ directory:
    python3 -m backend.recalc_renewal_history

Note: This uses the CURRENT lease data in Supabase. For annual leases, the
current start_date reflects the most recent renewal term. Leases that have
been renewed since the target month appear as Closed records in Supabase
(old term = Closed, current term = Active). The numerator query includes all
statuses so we capture both.
"""

import sys, asyncio
from datetime import date, timedelta

sys.path.insert(0, ".")
from dotenv import load_dotenv; load_dotenv()
from backend.supabase_kpi import _get_client


def compute_month(client, m_start: date, active_unit_ids: list):
    """
    Compute renewal rate for month M (m_start = first day of M).
    Returns dict with rate_pct, renewals, expirations, total_eligible.
    """
    m_end = date(m_start.year + (m_start.month // 12),
                 (m_start.month % 12) + 1, 1) if m_start.month < 12 \
        else date(m_start.year + 1, 1, 1)

    m1_mo  = m_start.month - 1 or 12
    m1_yr  = m_start.year if m_start.month > 1 else m_start.year - 1
    m1_start = date(m1_yr, m1_mo, 1)

    # Numerator: ALL statuses (captures leases that have since been renewed/closed)
    ren_resp = client.table("leases") \
        .select("start_date,move_in_date") \
        .gte("start_date", m_start.isoformat()) \
        .lt("start_date",  m_end.isoformat()) \
        .in_("unit_id", active_unit_ids) \
        .execute()
    renewals = sum(
        1 for r in (ren_resp.data or [])
        if r.get("start_date") and r.get("move_in_date")
        and (date.fromisoformat(r["start_date"]) - date.fromisoformat(r["move_in_date"])).days > 180
    )

    # Denominator: closed leases and NTVs in M-1
    vac_resp = client.table("leases").select("id,unit_id,end_date") \
        .gte("end_date", m1_start.isoformat()) \
        .lt("end_date",  m_start.isoformat()) \
        .eq("status", "Closed") \
        .in_("unit_id", active_unit_ids) \
        .execute()

    ntv_resp = client.table("leases").select("id,unit_id,expected_moveout_date,end_date") \
        .gte("expected_moveout_date", m1_start.isoformat()) \
        .lt("expected_moveout_date",  m_start.isoformat()) \
        .not_.is_("expected_moveout_date", "null") \
        .in_("unit_id", active_unit_ids) \
        .execute()

    follow_on = 0
    genuine_vac_ids: set = set()
    for r in (vac_resp.data or []) + (ntv_resp.data or []):
        lid = r.get("id"); uid = r.get("unit_id")
        emd = r.get("expected_moveout_date"); ed = r.get("end_date")
        if emd and ed:
            emd_dt = date.fromisoformat(emd); ed_dt = date.fromisoformat(ed)
            edate = ed if (ed_dt - emd_dt).days <= 90 else emd
        else:
            edate = ed or emd
        if not (lid and uid and edate):
            genuine_vac_ids.add(lid); continue
        end_dt = date.fromisoformat(edate)
        cutoff = (end_dt + timedelta(days=45)).isoformat()
        f = client.table("leases").select("id").eq("unit_id", uid) \
            .in_("status", ["Active", "Month-to-Month", "Pending"]) \
            .gt("start_date", edate).lte("start_date", cutoff).execute()
        if f.data:
            follow_on += 1; continue
        o = client.table("leases").select("id").eq("unit_id", uid) \
            .in_("status", ["Active", "Month-to-Month", "Pending"]) \
            .lt("move_in_date", edate).execute()
        if o.data:
            follow_on += 1
        else:
            genuine_vac_ids.add(lid)

    total = renewals + follow_on + len(genuine_vac_ids)
    rate  = round((renewals + follow_on) / total * 100, 2) if total > 0 else None
    return {
        "month_key":      m_start.strftime("%Y-%m"),
        "month_start":    m_start.isoformat(),
        "renewals":       renewals + follow_on,
        "expirations":    len(genuine_vac_ids),
        "ntv_count":      0,
        "total_eligible": total,
        "rate_pct":       rate,
        "is_complete":    True,
    }


def main():
    client = _get_client()

    # Build active unit ID list (current is_active state)
    active_props = [r["id"] for r in
                    client.table("properties").select("id").eq("is_active", True).execute().data or []]
    active_units = [r["id"] for r in
                    client.table("units").select("id").in_("property_id", active_props).execute().data or []]
    print(f"Active properties: {len(active_props)}  Active units: {len(active_units)}")

    # Build list of months to recalculate: last 24 months (excluding current)
    today = date.today()
    current_month = today.replace(day=1)
    months = []
    m = current_month
    for _ in range(24):
        m_mo = m.month - 1 or 12
        m_yr = m.year if m.month > 1 else m.year - 1
        m = date(m_yr, m_mo, 1)
        months.append(m)

    print(f"Recalculating {len(months)} months: {months[-1].strftime('%Y-%m')} → {months[0].strftime('%Y-%m')}")
    print()

    results = []
    for m_start in reversed(months):
        row = compute_month(client, m_start, active_units)
        results.append(row)
        print(f"  {row['month_key']}: {row['rate_pct']}%  ({row['renewals']} renewed / {row['total_eligible']} total, {row['expirations']} vacated)")

    print()
    print("Upserting to renewal_rate_monthly...")
    for row in results:
        client.table("renewal_rate_monthly").upsert(row, on_conflict="month_key").execute()
    print("Done.")


if __name__ == "__main__":
    main()
