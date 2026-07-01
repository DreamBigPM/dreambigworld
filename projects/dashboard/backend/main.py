"""
main.py — FastAPI application for Dream Big PM Dashboard.

Serves the frontend at / and JSON API at /api/*.
Authentication via Microsoft 365 SSO (or SKIP_AUTH=true for local dev).
"""

import os
import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the dashboard root (one level up from backend/)
_DASHBOARD_DIR = Path(__file__).parent.parent
load_dotenv(_DASHBOARD_DIR / ".env")

from fastapi import FastAPI, Depends, Request, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend import database, kpi, briefing, auth, supabase_kpi
from backend import sheets as _sheets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# APScheduler instance
scheduler = AsyncIOScheduler()

# Simple in-memory cache for KPI data (avoids hammering Rentvine on every page load)
_kpi_cache: dict = {}
_kpi_cache_time: datetime = None
_CACHE_TTL_MINUTES = 15

# Churn data cache (15-min TTL, same pattern as KPI cache)
_churn_cache: dict = {}
_churn_cache_time: datetime = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    logger.info("=" * 60)
    logger.info("Dream Big PM Dashboard starting up")
    logger.info(f"Dashboard root: {_DASHBOARD_DIR}")

    if os.getenv("SKIP_AUTH", "").lower() == "true":
        logger.warning("⚠️  SKIP_AUTH=true — authentication is DISABLED (dev mode only)")

    # Initialize database
    database.init_db()
    logger.info("SQLite database initialized")

    # Seed known team members with correct roles
    database.seed_team_users()
    logger.info("Team users seeded")

    # Schedule daily KPI pull at 6:00am
    scheduler.add_job(
        _scheduled_kpi_refresh,
        trigger="cron",
        hour=6,
        minute=0,
        id="daily_kpi_refresh",
    )

    # Schedule daily briefings at 6:05am
    scheduler.add_job(
        _scheduled_briefings,
        trigger="cron",
        hour=6,
        minute=5,
        id="daily_briefings",
    )

    # Schedule daily Supabase sync at 4:00am (before KPI refresh)
    scheduler.add_job(
        _scheduled_supabase_sync,
        trigger="cron",
        hour=4,
        minute=0,
        id="daily_supabase_sync",
    )

    # Snapshot last month's renewal rate on the 1st of each month at 3:00am
    scheduler.add_job(
        _snapshot_renewal_rate,
        trigger="cron",
        day=1,
        hour=3,
        minute=0,
        id="monthly_renewal_rate_snapshot",
    )

    scheduler.start()
    logger.info("Scheduler started — daily KPI refresh at 6:00am, briefings at 6:05am")
    logger.info("API ready at http://localhost:8000")
    logger.info("=" * 60)

    yield

    scheduler.shutdown()
    logger.info("Scheduler stopped — dashboard shutting down")


async def _scheduled_kpi_refresh():
    global _kpi_cache, _kpi_cache_time
    logger.info("Scheduled KPI refresh starting...")
    try:
        data = await supabase_kpi.fetch_kpis(database_module=database)
        if data:
            _kpi_cache = data
            _kpi_cache_time = datetime.utcnow()
            logger.info("Scheduled KPI refresh complete (Supabase)")
        else:
            logger.error("Scheduled KPI refresh: Supabase returned no data")
    except Exception as e:
        logger.error(f"Scheduled KPI refresh failed: {e}")


async def _scheduled_briefings():
    logger.info("Generating daily briefings for all roles...")
    try:
        cached_kpis = _kpi_cache or {}
        await briefing.generate_all_briefings(cached_kpis)
        logger.info("Daily briefings generated")
    except Exception as e:
        logger.error(f"Briefing generation failed: {e}")


async def _scheduled_supabase_sync():
    logger.info("Scheduled Supabase sync starting...")
    try:
        from backend import supabase_sync
        result = await supabase_sync.run_full_sync()
        if result.get("errors"):
            logger.error(f"Supabase sync completed with errors: {result['errors']}")
        else:
            logger.info(
                f"Supabase sync complete — properties:{result.get('properties_synced',0)} "
                f"units:{result.get('units_synced',0)} leases:{result.get('leases_synced',0)} "
                f"tenants:{result.get('tenants_synced',0)}"
            )
    except Exception as e:
        logger.error(f"Scheduled Supabase sync failed: {e}")


async def _snapshot_renewal_rate():
    """
    Runs on the 1st of each month. Computes and stores last month's renewal rate.

    Renewal rate for month M:
      Numerator:   leases with start_date in M AND (start_date - move_in_date) > 180 days
      Denominator: renewals + closed leases (vacated) in M-1 + leases with expected_moveout_date in M-1
    """
    from datetime import date as _date
    logger.info("Monthly renewal rate snapshot starting...")
    try:
        today = _date.today()
        this_month = today.replace(day=1)

        # Month M = previous calendar month (the one we're computing the rate for)
        m_month = this_month.month - 1 or 12
        m_year  = this_month.year if this_month.month > 1 else this_month.year - 1
        m_start = _date(m_year, m_month, 1)
        m_end   = this_month  # exclusive upper bound

        # Month M-1 = two months ago (denominator source)
        m1_month = m_start.month - 1 or 12
        m1_year  = m_start.year if m_start.month > 1 else m_start.year - 1
        m1_start = _date(m1_year, m1_month, 1)
        m1_end   = m_start  # exclusive

        month_key = m_start.strftime("%Y-%m")
        client = supabase_kpi._get_client()

        # Only count leases on active (managed) properties.
        # Off-boarded properties are is_active=False and must not count as renewal losses.
        active_prop_resp = client.table("properties").select("id").eq("is_active", True).execute()
        active_prop_ids  = [r["id"] for r in (active_prop_resp.data or [])]
        active_unit_resp = client.table("units").select("id").in_("property_id", active_prop_ids).execute()
        active_unit_ids  = [r["id"] for r in (active_unit_resp.data or [])]

        # Renewals in month M
        ren_resp = client.table("leases").select("id, start_date, move_in_date") \
            .gte("start_date", m_start.isoformat()) \
            .lt("start_date", m_end.isoformat()) \
            .in_("unit_id", active_unit_ids) \
            .execute()
        renewals = [
            r for r in (ren_resp.data or [])
            if r.get("start_date") and r.get("move_in_date")
            and (_date.fromisoformat(r["start_date"]) - _date.fromisoformat(r["move_in_date"])).days > 180
        ]

        # Vacates in month M-1: closed leases with end_date in M-1
        exp_resp = client.table("leases").select("id,unit_id,end_date") \
            .gte("end_date", m1_start.isoformat()) \
            .lt("end_date", m1_end.isoformat()) \
            .eq("status", "Closed") \
            .in_("unit_id", active_unit_ids) \
            .execute()

        # NTVs: fetch all on active units, then filter in Python using the correct
        # effective vacancy date (same logic as supabase_kpi.py):
        #   - Active/MTM + NTV: use expected_moveout_date
        #   - Closed + NTV where NTV ≤ lease start_date: "cancelled renewal" → use expected_moveout_date
        #   - Closed + NTV where NTV is mid-lease: tenant stayed to natural end → use end_date
        ntv_all_resp = client.table("leases") \
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
            if m1_start.isoformat() <= eff < m1_end.isoformat():
                r["_eff"] = eff
                ntv_records.append(r)

        # Determine genuine vacates vs lease transitions (follow-on detection).
        # Same logic as supabase_kpi.py current-month computation.
        from datetime import timedelta as _td
        follow_on = 0
        genuine_vac_ids: set = set()
        for r in (exp_resp.data or []) + ntv_records:
            lid = r.get("id"); uid = r.get("unit_id")
            edate = r.get("_eff") or r.get("end_date") or r.get("expected_moveout_date")
            if not edate:
                ed = r.get("end_date"); emd = r.get("expected_moveout_date")
                edate = ed or emd
            if not (lid and uid and edate):
                genuine_vac_ids.add(lid); continue
            end_dt = _date.fromisoformat(edate)
            cutoff = (end_dt + _td(days=45)).isoformat()
            # Case 1: new lease within 45 days AND tenure > 180d (same tenant renewed)
            f = client.table("leases").select("id,start_date,move_in_date").eq("unit_id", uid) \
                .in_("status", ["Active", "Month-to-Month", "Pending"]) \
                .gt("start_date", edate).lte("start_date", cutoff).execute()
            if f.data:
                frow = f.data[0]
                fsd = frow.get("start_date"); fmi = frow.get("move_in_date")
                if fsd and fmi and (_date.fromisoformat(fsd) - _date.fromisoformat(fmi)).days > 180:
                    follow_on += 1; continue
            # Case 2: active lease with move_in before this end
            o = client.table("leases").select("id").eq("unit_id", uid) \
                .in_("status", ["Active", "Month-to-Month", "Pending"]) \
                .lt("move_in_date", edate).execute()
            if o.data:
                follow_on += 1
            else:
                genuine_vac_ids.add(lid)

        renewal_count  = len(renewals)
        total_eligible = renewal_count + follow_on + len(genuine_vac_ids)
        rate_pct = round((renewal_count + follow_on) / total_eligible * 100, 2) if total_eligible > 0 else None

        client.table("renewal_rate_monthly").upsert({
            "month_key":      month_key,
            "month_start":    m_start.isoformat(),
            "renewals":       renewal_count + follow_on,
            "expirations":    len(genuine_vac_ids),
            "ntv_count":      0,
            "total_eligible": total_eligible,
            "rate_pct":       rate_pct,
            "is_complete":    True,
        }, on_conflict="month_key").execute()

        logger.info(f"Renewal rate snapshot: {month_key} = {rate_pct}% ({renewal_count + follow_on}/{total_eligible})")
    except Exception as e:
        logger.error(f"Monthly renewal rate snapshot failed: {e}")


async def _get_kpis_cached() -> dict:
    """
    Return KPI data using a three-tier strategy:
      1. In-memory cache (15-min TTL) — fastest
      2. Supabase live query — primary data source (Rentvine syncs here automatically)
      3. SQLite snapshot — fallback if Supabase is unreachable
    """
    global _kpi_cache, _kpi_cache_time
    now = datetime.utcnow()

    if (
        _kpi_cache
        and _kpi_cache_time
        and (now - _kpi_cache_time).total_seconds() < _CACHE_TTL_MINUTES * 60
    ):
        return _kpi_cache

    # Primary: live data from Supabase
    data = await supabase_kpi.fetch_kpis(database_module=database)
    if data:
        _kpi_cache = data
        _kpi_cache_time = now
        return _kpi_cache

    # Fallback: last SQLite snapshot (populated by old sync.py flow)
    logger.warning("Supabase unavailable — falling back to SQLite KPI snapshot")
    db_data = kpi.load_kpis_from_db()
    if db_data:
        _kpi_cache = db_data
        _kpi_cache_time = now
        return _kpi_cache

    logger.error("No KPI data available — Supabase and SQLite both failed")
    return {}


def _filter_kpis_by_role(kpis: dict, user: dict) -> dict:
    """Strip KPI fields the user's role cannot see."""
    role = user.get("role", "property_manager")

    if role == "admin":
        return kpis

    # Operations: everything except narpm/financial details
    if role == "operations":
        return {k: v for k, v in kpis.items() if k not in ("narpm_metrics",)}

    # Property manager: filter to assigned properties
    assigned = user.get("assigned_property_ids")
    if role == "property_manager":
        result = {
            "rent_collected": kpis.get("rent_collected", {}),
            "occupancy": kpis.get("occupancy", {}),
            "renewal_rate": kpis.get("renewal_rate", {}),
            "speed_of_repair": kpis.get("speed_of_repair", {}),
            "at_risk_tenants": kpis.get("at_risk_tenants", []),
            "inspection_compliance": kpis.get("inspection_compliance", []),
            "refreshed_at": kpis.get("refreshed_at"),
        }
        return result

    if role == "leasing_agent":
        return {
            "occupancy": kpis.get("occupancy", {}),
            "days_on_market": kpis.get("days_on_market", {}),
            "renewal_rate": kpis.get("renewal_rate", {}),
            "vacancy_cost_clock": kpis.get("vacancy_cost_clock", []),
            "lease_expiry_calendar": kpis.get("lease_expiry_calendar", []),
            "expiry_pipeline": kpis.get("expiry_pipeline", []),
            "expiring_leases": kpis.get("expiring_leases", {}),
            "refreshed_at": kpis.get("refreshed_at"),
        }

    if role == "maintenance_coordinator":
        return {
            "speed_of_repair": kpis.get("speed_of_repair", {}),
            "inspection_compliance": kpis.get("inspection_compliance", []),
            "maintenance_satisfaction": kpis.get("maintenance_satisfaction"),
            "refreshed_at": kpis.get("refreshed_at"),
        }

    if role == "field_services":
        sor = kpis.get("speed_of_repair", {})
        return {
            "inspection_compliance": kpis.get("inspection_compliance", []),
            "speed_of_repair": {
                "open_count": sor.get("open_count", 0),
                "overdue_count": sor.get("overdue_count", 0),
                "avg_days_to_close": sor.get("avg_days_to_close"),
                "open_work_orders": sor.get("open_work_orders", []),
                "overdue_work_orders": sor.get("overdue_work_orders", []),
            },
            "refreshed_at": kpis.get("refreshed_at"),
        }

    return kpis


app = FastAPI(title="Dream Big PM Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3456", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth routes ────────────────────────────────────────────────────────────────

@app.get("/auth/login")
async def auth_login():
    url = auth.get_microsoft_auth_url()
    return RedirectResponse(url)


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = None, error: str = None):
    if error:
        return HTMLResponse(f"<h2>Login failed: {error}</h2>", status_code=400)
    if not code:
        return HTMLResponse("<h2>No authorization code received.</h2>", status_code=400)

    try:
        token_data = auth.exchange_code_for_token(code)
    except ValueError as e:
        return HTMLResponse(f"<h2>Access denied: {e}</h2>", status_code=403)
    except Exception as e:
        logger.error(f"Auth callback error: {e}")
        return HTMLResponse("<h2>Login error. Please try again.</h2>", status_code=500)

    # Get or create user in DB
    user = database.get_or_create_user(
        email=token_data["email"],
        display_name=token_data["name"],
    )
    database.update_user_last_login(user["id"])

    session_data = {
        "user_id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "display_name": user.get("display_name") or user["email"],
    }

    role_urls = {
        "admin":                    "/",
        "operations":               "/operations",
        "leasing_agent":            "/leasing",
        "field_services":           "/field",
        "property_manager":         "/pm",
        "maintenance_coordinator":  "/maintenance",
    }
    redirect_url = role_urls.get(user["role"], "/")

    cookie_value = auth.create_session_cookie(session_data)
    response = RedirectResponse(redirect_url)
    secure = os.getenv("HTTPS_ENABLED", "").lower() == "true"
    response.set_cookie(
        key=auth.COOKIE_NAME,
        value=cookie_value,
        httponly=True,
        max_age=auth.COOKIE_MAX_AGE,
        samesite="lax",
        secure=secure,
    )
    return response


@app.post("/auth/logout")
async def auth_logout():
    response = RedirectResponse("/auth/login", status_code=302)
    response.delete_cookie(auth.COOKIE_NAME)
    return response


@app.get("/auth/me")
async def auth_me(user: dict = Depends(auth.get_current_user)):
    return JSONResponse({
        "email": user.get("email"),
        "role": user.get("role"),
        "display_name": user.get("display_name"),
    })


# ── API routes ─────────────────────────────────────────────────────────────────

def _inject_qb_metrics(data: dict) -> dict:
    """Attach qb_metrics from the latest P&L upload (DB-based). Never raises."""
    try:
        import json as _json
        fin = database.get_latest_financial_upload()
        if fin and fin.get("metrics_json"):
            data["qb_metrics"] = _json.loads(fin["metrics_json"])
        else:
            data["qb_metrics"] = None
    except Exception as e:
        logger.warning(f"QB metrics (non-fatal): {e}")
        data["qb_metrics"] = None
    return data


@app.get("/api/kpis")
async def api_kpis(user: dict = Depends(auth.get_current_user)):
    data = await _get_kpis_cached()
    data = _inject_qb_metrics(dict(data))
    return JSONResponse(_filter_kpis_by_role(data, user))


@app.post("/api/refresh")
async def api_refresh(user: dict = Depends(auth.get_current_user)):
    global _kpi_cache, _kpi_cache_time
    _invalidate_churn_cache()
    data = await supabase_kpi.fetch_kpis(database_module=database)
    if data:
        _kpi_cache = data
        _kpi_cache_time = datetime.utcnow()
    database.clear_todays_briefings()
    result = dict(_kpi_cache or {})
    result = _inject_qb_metrics(result)
    return JSONResponse(_filter_kpis_by_role(result, user))


@app.get("/api/briefing")
async def api_briefing(request: Request, user: dict = Depends(auth.get_current_user)):
    role = user.get("role", "admin")
    # Always honor ?role= from the dashboard page — it controls data subset, not access
    override = request.query_params.get("role")
    if override:
        role = override
    from datetime import date as _date
    kpis = await _get_kpis_cached()
    text = await briefing.get_or_generate_briefing(role=role, kpi_data=kpis)
    principle = briefing._get_daily_principle(_date.today())
    return JSONResponse({"role": role, "text": text, "principle": principle})


@app.get("/api/alerts")
async def api_alerts(user: dict = Depends(auth.get_current_user)):
    alerts = database.get_active_alerts()
    return JSONResponse({"alerts": alerts, "count": len(alerts)})


@app.post("/api/alerts/{alert_id}/clear")
async def api_clear_alert(
    alert_id: int,
    user: dict = Depends(auth.get_current_user),
):
    database.clear_alert(alert_id, cleared_by=user.get("email", "unknown"))
    return JSONResponse({"cleared": True, "alert_id": alert_id})


@app.get("/api/renewals")
async def api_renewals(user: dict = Depends(auth.get_current_user)):
    rows = database.get_renewal_pipeline()
    return JSONResponse({"renewals": rows, "count": len(rows)})


@app.post("/api/renewals/{lease_id}/status")
async def api_renewal_status(
    lease_id: str,
    request: Request,
    user: dict = Depends(auth.get_current_user),
):
    body = await request.json()
    status = body.get("status")
    notes = body.get("notes")

    valid_statuses = ("not_started", "contacted", "in_negotiation", "signed", "lost")
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"status must be one of: {valid_statuses}")

    database.update_renewal_status(lease_id, status, notes)
    return JSONResponse({"updated": True, "lease_id": lease_id, "status": status})


@app.post("/api/manual-kpi")
async def api_manual_kpi(
    request: Request,
    user: dict = Depends(auth.get_current_user),
):
    if user.get("role") not in ("admin", "operations"):
        raise HTTPException(status_code=403, detail="Admin or operations role required")

    body = await request.json()
    metric_name = body.get("metric_name")
    value = body.get("value")
    notes = body.get("notes")

    if not metric_name or value is None:
        raise HTTPException(status_code=400, detail="metric_name and value required")

    database.set_manual_kpi(metric_name, float(value), notes)
    return JSONResponse({"saved": True, "metric_name": metric_name, "value": value})


@app.get("/api/history/{metric_name}")
async def api_history(
    metric_name: str,
    days: int = 90,
    user: dict = Depends(auth.get_current_user),
):
    rows = database.get_metric_history(metric_name, days=days)
    return JSONResponse({"metric_name": metric_name, "days": days, "history": rows})


@app.get("/api/drill/{section}")
async def api_drill(
    section: str,
    user: dict = Depends(auth.get_current_user),
):
    """Return underlying records for drill-down on any dashboard card."""
    data = await _get_kpis_cached()

    if section == "delinquency":
        rc = data.get("rent_collected", {})
        return JSONResponse({
            "section": "delinquency",
            "records": rc.get("delinquent_leases", []),
            "pct": rc.get("pct"),
            "collected_usd": rc.get("collected_usd"),
            "expected_usd": rc.get("expected_usd"),
        })

    if section == "work_orders":
        sor = data.get("speed_of_repair", {})
        return JSONResponse({
            "section": "work_orders",
            "records": sor.get("open_work_orders", []),
            "avg_days_to_close": sor.get("avg_days_to_close"),
            "open_count": sor.get("open_count"),
            "overdue_count": sor.get("overdue_count"),
        })

    if section == "overdue_work_orders":
        sor = data.get("speed_of_repair", {})
        return JSONResponse({
            "section": "overdue_work_orders",
            "records": sor.get("overdue_work_orders", []),
            "avg_days_to_close": sor.get("avg_days_to_close"),
            "open_count": sor.get("open_count"),
            "overdue_count": sor.get("overdue_count"),
        })

    if section == "vacant_units":
        return JSONResponse({
            "section": "vacant_units",
            "records": data.get("vacancy_cost_clock", []),
        })

    if section == "occupancy":
        occ = data.get("occupancy", {})
        return JSONResponse({
            "section": "occupancy",
            "pct": occ.get("pct"),
            "occupied": occ.get("occupied"),
            "total": occ.get("total"),
            "vacant_units": occ.get("vacant_units", []),
        })

    if section in ("renewals", "expiring_30", "expiring_60", "expiring_90"):
        # Use expiry_pipeline (12-month window) for drill-downs so 62-91 day cards
        # don't miss leases that fall just outside the 90-day renewal_pipeline cutoff.
        recs = list(data.get("expiry_pipeline", []) or data.get("renewal_rate", {}).get("pipeline", []) or [])
        recs = [dict(r) if not isinstance(r, dict) else r for r in recs]
        try:
            sqlite_map = {str(r["lease_id"]): r for r in database.get_renewal_pipeline()}
            for r in recs:
                lid = str(r.get("lease_id", ""))
                if lid in sqlite_map:
                    r["status"] = sqlite_map[lid].get("status", "not_started")
                    r["notes"]  = sqlite_map[lid].get("notes")
                r.setdefault("status", "not_started")
        except Exception as e:
            logger.warning(f"Expiry drill status merge failed: {e}")
        # Filter to the specific day window for each bucket
        if section != "renewals":
            from datetime import date as _date
            _today = _date.today()
            _ranges = {"expiring_30": (1, 31), "expiring_60": (32, 61), "expiring_90": (62, 91)}
            _lo, _hi = _ranges[section]
            def _in_range(r):
                d = r.get("lease_end_date", "")
                if not d:
                    return False
                try:
                    days = (_date.fromisoformat(d) - _today).days
                    return _lo <= days <= _hi
                except Exception:
                    return False
            recs = [r for r in recs if _in_range(r)]
        return JSONResponse({"section": section, "records": recs})

    if section == "rent_collected":
        rc = data.get("rent_collected", {})
        return JSONResponse({
            "section": "rent_collected",
            "pct": rc.get("pct"),
            "collected_usd": rc.get("collected_usd"),
            "expected_usd": rc.get("expected_usd"),
            "delinquent_leases": rc.get("delinquent_leases", []),
        })

    if section == "inspections":
        return JSONResponse({
            "section": "inspections",
            "records": data.get("inspection_compliance", []),
        })

    if section == "at_risk":
        return JSONResponse({
            "section": "at_risk",
            "records": data.get("at_risk_tenants", []),
        })

    if section == "owner_health":
        return JSONResponse({
            "section": "owner_health",
            "records": data.get("owner_health", []),
        })

    if section == "avg_tenancy":
        try:
            from backend.supabase_kpi import _get_client
            client = _get_client()
            detail_resp = client.rpc("get_avg_tenancy_details").execute()
            detail = detail_resp.data
            if isinstance(detail, list) and detail:
                detail = detail[0]
            records = detail.get("records", []) if isinstance(detail, dict) else []
        except Exception as e:
            logger.error(f"avg_tenancy drill failed: {e}")
            records = []
        return JSONResponse({
            "section": "avg_tenancy",
            "avg_months": data.get("avg_tenancy_months"),
            "active_count": data.get("avg_tenancy_active_count"),
            "closed_count": data.get("avg_tenancy_closed_count"),
            "records": records,
        })

    if section == "turn_time":
        try:
            from backend.supabase_kpi import _get_client
            client = _get_client()
            detail_resp = client.rpc("get_turn_time_details").execute()
            detail = detail_resp.data
            if isinstance(detail, list) and detail:
                detail = detail[0]
            records = detail.get("records", []) if isinstance(detail, dict) else []
        except Exception as e:
            logger.error(f"turn_time drill failed: {e}")
            records = []
        return JSONResponse({
            "section": "turn_time",
            "avg_days": data.get("avg_turn_days"),
            "records": records,
        })

    if section == "renewal_history":
        from datetime import date as _date, timedelta
        from collections import defaultdict

        monthly_chart, pipeline = [], []
        records = []
        renewed, total = 0, 0

        try:
            client = supabase_kpi._get_client()

            # Historical chart from Supabase snapshot table
            hist_resp = client.table("renewal_rate_monthly") \
                .select("month_key,month_start,renewals,expirations,ntv_count,total_eligible,rate_pct") \
                .order("month_key").execute()
            monthly_chart = hist_resp.data or []
            # Add month_label for the SVG chart tooltips/labels
            for row in monthly_chart:
                mk = row.get("month_key", "")
                if mk and not row.get("month_label"):
                    try:
                        row["month_label"] = _date.fromisoformat(mk + "-01").strftime("%b %Y")
                    except ValueError:
                        pass

            # Live current-month stats computed directly from Supabase leases
            today      = _date.today()
            m_start    = today.replace(day=1)
            m_end_mo   = m_start.month + 1 if m_start.month < 12 else 1
            m_end_yr   = m_start.year if m_start.month < 12 else m_start.year + 1
            m_end      = _date(m_end_yr, m_end_mo, 1)

            m1_mo      = m_start.month - 1 or 12
            m1_yr      = m_start.year if m_start.month > 1 else m_start.year - 1
            m1_start   = _date(m1_yr, m1_mo, 1)

            # Only count leases on active (managed) properties.
            active_prop_resp = client.table("properties").select("id").eq("is_active", True).execute()
            active_prop_ids  = [r["id"] for r in (active_prop_resp.data or [])]
            active_unit_resp = client.table("units").select("id").in_("property_id", active_prop_ids).execute()
            active_unit_ids  = [r["id"] for r in (active_unit_resp.data or [])]

            # Renewals this month: start_date in current month, (start_date - move_in_date) > 180 days
            ren_resp = client.table("leases") \
                .select("id,start_date,move_in_date,unit_id") \
                .gte("start_date", m_start.isoformat()) \
                .lt("start_date",  m_end.isoformat()) \
                .in_("status", ["Active", "Month-to-Month"]) \
                .in_("unit_id", active_unit_ids) \
                .execute()
            for r in (ren_resp.data or []):
                sd = r.get("start_date")
                mi = r.get("move_in_date")
                if sd and mi:
                    try:
                        if (_date.fromisoformat(sd) - _date.fromisoformat(mi)).days > 180:
                            renewed += 1
                    except ValueError:
                        pass

            # Vacates last month: closed leases with end_date in M-1
            vac_resp = client.table("leases").select("id,unit_id,end_date") \
                .gte("end_date", m1_start.isoformat()) \
                .lt("end_date",  m_start.isoformat()) \
                .eq("status", "Closed") \
                .in_("unit_id", active_unit_ids) \
                .execute()

            # NTVs: fetch all on active units, filter in Python using the correct
            # effective vacancy date (same logic as supabase_kpi.py):
            #   - Active/MTM + NTV: use expected_moveout_date
            #   - Closed + NTV where NTV ≤ lease start_date: "cancelled renewal" → use expected_moveout_date
            #   - Closed + NTV where NTV is mid-lease: tenant stayed to natural end → use end_date
            ntv_all_resp = client.table("leases") \
                .select("id,unit_id,expected_moveout_date,end_date,start_date,status") \
                .not_.is_("expected_moveout_date", "null") \
                .in_("unit_id", active_unit_ids) \
                .execute()
            ntv_records_hist = []
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
                    ntv_records_hist.append(r)

            # Determine genuine vacates vs lease-term transitions where tenant stayed.
            follow_on_renewed = 0
            genuine_vac_ids: set = set()
            for r in (vac_resp.data or []) + ntv_records_hist:
                lid  = r.get("id")
                uid  = r.get("unit_id")
                edate = r.get("_eff") or r.get("end_date") or r.get("expected_moveout_date")
                if not (lid and uid and edate):
                    genuine_vac_ids.add(lid)
                    continue
                cutoff = (_date.fromisoformat(edate) + timedelta(days=45)).isoformat()
                # Case 1: new lease within 45 days AND tenure > 180d (same tenant renewed)
                follow = client.table("leases").select("id,start_date,move_in_date") \
                    .eq("unit_id", uid) \
                    .in_("status", ["Active", "Month-to-Month", "Pending"]) \
                    .gt("start_date", edate) \
                    .lte("start_date", cutoff) \
                    .execute()
                if follow.data:
                    frow = follow.data[0]
                    fsd = frow.get("start_date"); fmi = frow.get("move_in_date")
                    if fsd and fmi and (_date.fromisoformat(fsd) - _date.fromisoformat(fmi)).days > 180:
                        follow_on_renewed += 1
                        continue
                # Case 2: active lease with move_in before this end
                overlap = client.table("leases").select("id") \
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

            # Always inject current month into the historical chart if it's missing
            try:
                curr_key = today.strftime("%Y-%m")
                if not any(m.get("month_key") == curr_key for m in monthly_chart):
                    monthly_chart.append({
                        "month_key": curr_key,
                        "month_label": today.strftime("%b %Y"),
                        "rate_pct": current_rate,
                        "renewals": renewed + follow_on_renewed,
                        "total_eligible": total,
                    })
                    monthly_chart.sort(key=lambda m: m.get("month_key", ""))
            except Exception:
                pass

            # Upcoming renewal pipeline — shows TOTAL renewals per month, both
            # already-signed and not yet signed, so the bars stay stable as
            # tenants renew. A lease is eligible when tenure > 180 days at
            # renewal_start. Priority: emd → ied → end_date.
            six_mo_iso   = (today + timedelta(days=180)).isoformat()
            lookback_iso = (today - timedelta(days=45)).isoformat()

            def _first_after(d: str) -> "_date":
                dt = _date.fromisoformat(d)
                return _date(dt.year + 1, 1, 1) if dt.month == 12 else _date(dt.year, dt.month + 1, 1)

            def _pipe_rs(row, min_dt):
                ed = row.get("end_date"); ied = row.get("increase_eligibility_date")
                emd = row.get("expected_moveout_date")
                rs = None
                if emd:
                    c = _first_after(emd)
                    if c >= min_dt and c.isoformat() <= six_mo_iso: rs = c
                if rs is None and ied:
                    c = _date.fromisoformat(ied).replace(day=1)
                    if c >= min_dt and c.isoformat() <= six_mo_iso: rs = c
                if rs is None and ed:
                    c = _first_after(ed)
                    if c >= min_dt and c.isoformat() <= six_mo_iso: rs = c
                return rs

            pipe_active = client.table("leases") \
                .select("end_date,increase_eligibility_date,expected_moveout_date,move_in_date,unit_id") \
                .in_("status", ["Active", "Month-to-Month", "Pending"]) \
                .in_("unit_id", active_unit_ids) \
                .execute()

            # Recently-closed leases — may have already renewed; include them if
            # the unit has an active follow-on lease (= renewal happened).
            pipe_closed = client.table("leases") \
                .select("end_date,increase_eligibility_date,expected_moveout_date,move_in_date,unit_id") \
                .eq("status", "Closed") \
                .gte("end_date", lookback_iso) \
                .lte("end_date", six_mo_iso) \
                .in_("unit_id", active_unit_ids) \
                .execute()

            active_units_now = {r["unit_id"] for r in (pipe_active.data or []) if r.get("unit_id")}
            counts: dict = defaultdict(int)
            seen_per_month: dict = defaultdict(set)

            for row in (pipe_active.data or []):
                uid = row.get("unit_id"); move_in = row.get("move_in_date")
                if not move_in: continue
                rs = _pipe_rs(row, today)
                if rs is None: continue
                if (rs - _date.fromisoformat(move_in)).days <= 180: continue
                mk = rs.strftime("%Y-%m")
                if uid in seen_per_month[mk]: continue
                seen_per_month[mk].add(uid); counts[mk] += 1

            for row in (pipe_closed.data or []):
                uid = row.get("unit_id"); move_in = row.get("move_in_date")
                if not uid or not move_in: continue
                if uid not in active_units_now: continue  # genuine vacate, not a renewal
                rs = _pipe_rs(row, today)
                if rs is None: continue
                if (rs - _date.fromisoformat(move_in)).days <= 180: continue
                mk = rs.strftime("%Y-%m")
                if uid in seen_per_month[mk]: continue
                seen_per_month[mk].add(uid); counts[mk] += 1

            pipeline = [
                {"month_key": k, "expirations": v,
                 "month_label": _date.fromisoformat(k + "-01").strftime("%b %Y")}
                for k, v in sorted(counts.items())
            ]
        except Exception as e:
            logger.error(f"renewal_history drill failed: {e}")

        return JSONResponse({
            "section":       "renewal_history",
            "records":       records,
            "total_count":   total,
            "renewed_count": renewed + follow_on_renewed,
            "monthly_chart": monthly_chart,
            "pipeline":      pipeline,
        })

    raise HTTPException(status_code=404, detail=f"Unknown drill section: {section}")


# ── Churn helpers ──────────────────────────────────────────────────────────────

async def _get_churn_cached() -> dict:
    """Return churn summary, using a 15-minute in-memory cache."""
    global _churn_cache, _churn_cache_time
    now = datetime.utcnow()
    if (
        _churn_cache
        and _churn_cache_time
        and (now - _churn_cache_time).total_seconds() < _CACHE_TTL_MINUTES * 60
    ):
        return _churn_cache

    connected = _sheets.is_sheets_connected()
    if not connected:
        return {"connected": False, "current_churn_pct": None, "history": []}

    rows    = _sheets.read_churn_sheet()
    summary = _sheets.compute_churn_summary(rows)

    # Prefer the sheet's own YTD summary over our computed values —
    # the sheet has nuance (reactive doors, etc.) we can't infer from events alone
    ytd = _sheets._read_ytd_summary_xlsx()
    if ytd:
        summary["current_adds"]       = ytd["adds"]
        summary["current_offboards"]  = ytd["offboards"]
        summary["current_churn_pct"]  = ytd["churn_pct"]

    result  = {"connected": True, **summary}

    _churn_cache      = result
    _churn_cache_time = now
    return result


def _invalidate_churn_cache():
    global _churn_cache, _churn_cache_time
    _churn_cache      = {}
    _churn_cache_time = None


# ── Churn routes ───────────────────────────────────────────────────────────────

@app.get("/api/churn")
async def api_churn(user: dict = Depends(auth.get_current_user)):
    data = await _get_churn_cached()
    return JSONResponse(data)


@app.post("/api/churn/event")
async def api_churn_event(
    request: Request,
    user: dict = Depends(auth.get_current_user),
):
    if user.get("role") not in ("admin", "operations"):
        raise HTTPException(status_code=403, detail="Admin or operations role required")

    body = await request.json()
    event_date    = body.get("event_date", "")
    property_name = body.get("property_name", "")
    event_type    = body.get("event_type", "")

    if not event_date or not property_name:
        raise HTTPException(status_code=400, detail="event_date and property_name are required")
    if event_type not in ("add", "offboard"):
        raise HTTPException(status_code=400, detail="event_type must be 'add' or 'offboard'")

    ok = _sheets.append_door_event(event_date, property_name, event_type)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to write to Google Sheet")

    _invalidate_churn_cache()
    return JSONResponse({"created": True})


# ── Financial P&L upload routes ────────────────────────────────────────────────

@app.post("/api/financials/upload")
async def api_financials_upload(
    user: dict = Depends(auth.get_current_user),
    file: UploadFile = File(...),
):
    """Upload a QuickBooks P&L PDF. Admin only. Parses and stores NARPM metrics."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    if not file_bytes[:4] == b"%PDF":
        raise HTTPException(status_code=400, detail="Invalid file format.")

    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB.")

    from backend import pl_parser
    parsed = pl_parser.parse_pl_pdf(file_bytes)
    if parsed.get("error"):
        return JSONResponse({"error": parsed["error"]}, status_code=400)

    door_count = _kpi_cache.get("occupancy", {}).get("total") or 119
    metrics    = pl_parser.compute_narpm_metrics(parsed, door_count)

    database.save_financial_upload(
        period=parsed["period"],
        parsed=parsed,
        metrics=metrics,
        door_count=door_count,
    )

    return JSONResponse({
        "connected":   True,
        "period":      parsed["period"],
        "uploaded_at": None,   # just uploaded; caller can re-fetch /api/financials
        "metrics":     metrics,
    })


@app.get("/api/financials/history")
async def api_financials_history(user: dict = Depends(auth.get_current_user)):
    """Return all P&L uploads, one per period (latest wins), sorted oldest→newest."""
    import json as _json
    rows = database.get_financial_history()
    months = []
    for row in rows:
        if row.get("metrics_json"):
            months.append({
                "period":      row["period"],
                "uploaded_at": row["uploaded_at"],
                "metrics":     _json.loads(row["metrics_json"]),
            })
    return JSONResponse({"months": months})


@app.get("/api/financials")
async def api_financials(user: dict = Depends(auth.get_current_user)):
    """Return the most recent P&L upload, or {connected:false} if none exists."""
    import json as _json
    fin = database.get_latest_financial_upload()
    if not fin or not fin.get("metrics_json"):
        return JSONResponse({"connected": False, "period": None, "metrics": None})

    return JSONResponse({
        "connected":   True,
        "period":      fin.get("period"),
        "uploaded_at": fin.get("uploaded_at"),
        "metrics":     _json.loads(fin["metrics_json"]),
    })


@app.get("/api/users")
async def api_users(user: dict = Depends(auth.get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    # Return users from DB (password-free)
    with database._connect() as conn:
        rows = conn.execute(
            "SELECT id, email, role, display_name, assigned_property_ids, is_active, last_login FROM users"
        ).fetchall()
    return JSONResponse({"users": [dict(r) for r in rows]})


@app.post("/api/users")
async def api_create_user(
    request: Request,
    user: dict = Depends(auth.get_current_user),
):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    body = await request.json()
    email = body.get("email", "").lower()
    role = body.get("role", "property_manager")
    display_name = body.get("display_name")
    assigned_ids = body.get("assigned_property_ids")

    if not email:
        raise HTTPException(status_code=400, detail="email required")

    import json as _json
    with database._connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO users (email, role, display_name, assigned_property_ids)
            VALUES (?, ?, ?, ?)
            """,
            (email, role, display_name, _json.dumps(assigned_ids) if assigned_ids else None),
        )

    new_user = database.get_user_by_email(email)
    return JSONResponse({"created": True, "user": new_user})


@app.post("/api/admin/sync-supabase")
async def api_sync_supabase(
    request: Request,
    user: dict = Depends(auth.get_current_user),
):
    """
    Trigger a full Rentvine → Supabase sync immediately.
    Admin-only. Returns a summary of what was synced.
    Pass ?dry_run=true to count records without writing.
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    dry_run = request.query_params.get("dry_run", "").lower() == "true"

    try:
        from backend import supabase_sync
        result = await supabase_sync.run_full_sync(dry_run=dry_run)
        # Clear the KPI cache so the next page load picks up fresh data
        global _kpi_cache, _kpi_cache_time
        _kpi_cache = {}
        _kpi_cache_time = None
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        logger.error(f"Manual Supabase sync failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Static frontend (must be last so /api/* routes take priority) ─────────────

_FRONTEND_DIR = _DASHBOARD_DIR / "frontend"

# Explicit routes for role dashboards (Starlette html=True doesn't strip .html from paths)
@app.get("/operations")
async def operations_page(request: Request):
    try:
        await auth.get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/auth/login")
    return FileResponse(_FRONTEND_DIR / "operations.html")

@app.get("/leasing")
async def leasing_page(request: Request):
    try:
        await auth.get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/auth/login")
    return FileResponse(_FRONTEND_DIR / "leasing.html")

@app.get("/field")
async def field_page(request: Request):
    try:
        await auth.get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/auth/login")
    return FileResponse(_FRONTEND_DIR / "field.html")

if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
else:
    @app.get("/")
    async def root():
        return HTMLResponse("<h2>Frontend not found. Build the frontend first.</h2>")
