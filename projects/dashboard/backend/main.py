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

from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend import database, kpi, briefing, auth

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
        _kpi_cache = await kpi.compute_all_kpis()
        _kpi_cache_time = datetime.utcnow()
        logger.info("Scheduled KPI refresh complete")
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


async def _get_kpis_cached() -> dict:
    """
    Return KPI data, using a three-tier strategy:
      1. In-memory cache (15-min TTL) — fastest
      2. raw_kpi_data in SQLite — populated by sync.py after each MCP fetch
      3. Live compute via Rentvine REST (fallback — currently returns 404s)
    """
    global _kpi_cache, _kpi_cache_time
    now = datetime.utcnow()

    if (
        _kpi_cache
        and _kpi_cache_time
        and (now - _kpi_cache_time).total_seconds() < _CACHE_TTL_MINUTES * 60
    ):
        return _kpi_cache

    # Try SQLite first (populated by sync.py from Rentvine MCP data)
    db_data = kpi.load_kpis_from_db()
    if db_data:
        _kpi_cache = db_data
        _kpi_cache_time = now
        return _kpi_cache

    # Fall back to live compute (requires working Rentvine REST API)
    _kpi_cache = await kpi.compute_all_kpis()
    _kpi_cache_time = now
    return _kpi_cache


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

    cookie_value = auth.create_session_cookie(session_data)
    response = RedirectResponse("/")
    response.set_cookie(
        key=auth.COOKIE_NAME,
        value=cookie_value,
        httponly=True,
        max_age=auth.COOKIE_MAX_AGE,
        samesite="lax",
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

@app.get("/api/kpis")
async def api_kpis(user: dict = Depends(auth.get_current_user)):
    data = await _get_kpis_cached()
    return JSONResponse(_filter_kpis_by_role(data, user))


@app.post("/api/refresh")
async def api_refresh(user: dict = Depends(auth.get_current_user)):
    global _kpi_cache, _kpi_cache_time
    _kpi_cache = await kpi.compute_all_kpis()
    _kpi_cache_time = datetime.utcnow()
    return JSONResponse(_filter_kpis_by_role(_kpi_cache, user))


@app.get("/api/briefing")
async def api_briefing(user: dict = Depends(auth.get_current_user)):
    role = user.get("role", "admin")
    kpis = await _get_kpis_cached()
    text = await briefing.get_or_generate_briefing(role=role, kpi_data=kpis)
    return JSONResponse({"role": role, "text": text})


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
        return JSONResponse({
            "section": "delinquency",
            "records": data.get("rent_collected", {}).get("delinquent_leases", []),
        })

    if section == "work_orders":
        return JSONResponse({
            "section": "work_orders",
            "records": data.get("speed_of_repair", {}).get("open_work_orders", []),
        })

    if section == "overdue_work_orders":
        return JSONResponse({
            "section": "overdue_work_orders",
            "records": data.get("speed_of_repair", {}).get("overdue_work_orders", []),
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

    if section == "renewals":
        return JSONResponse({
            "section": "renewals",
            "records": data.get("renewal_rate", {}).get("pipeline", []),
        })

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

    raise HTTPException(status_code=404, detail=f"Unknown drill section: {section}")


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


# ── Static frontend (must be last so /api/* routes take priority) ─────────────

_FRONTEND_DIR = _DASHBOARD_DIR / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
else:
    @app.get("/")
    async def root():
        return HTMLResponse("<h2>Frontend not found. Build the frontend first.</h2>")
