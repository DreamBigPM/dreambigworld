"""
quickbooks.py — QuickBooks Online OAuth + P&L parsing for Dream Big PM Dashboard.

Uses the Intuit OAuth 2.0 flow (PKCE not required for server-side).
Stores tokens in the Supabase oauth_tokens table.
Parses P&L line items to compute NARPM-style financial metrics:
  RPU  — Revenue Per Unit
  PPU  — Profit Per Unit
  DLER — Direct Labor Efficiency Ratio
  MLER — Management Labor Efficiency Ratio
  TLER — Total Labor Efficiency Ratio
  Expense Ratio

Environment variables (set in .env):
  INTUIT_CLIENT_ID
  INTUIT_CLIENT_SECRET
  INTUIT_REDIRECT_URI   (default: http://localhost:8000/auth/quickbooks/callback)
"""

import os
import logging
import time
from typing import Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

QB_AUTH_URL  = "https://appcenter.intuit.com/connect/oauth2"
QB_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QB_API_BASE  = "https://quickbooks.api.intuit.com"
QB_SCOPE     = "com.intuit.quickbooks.accounting"

# Edit these lists if your NARPM COA uses different account names
REVENUE_PATTERNS = [
    "management fee", "leasing fee", "maintenance admin fee",
    "maintenance coordination fee", "placement fee", "renewal fee",
    "late fee income", "management income",
]

DIRECT_LABOR_PATTERNS = [
    "payroll - field", "payroll - maintenance",
    "payroll - leasing", "direct labor", "field staff", "field payroll",
]

MGMT_LABOR_PATTERNS = [
    "payroll - management", "payroll - administrative",
    "payroll - admin", "management payroll", "owner compensation",
    "officer compensation", "management labor",
]


# ── Token storage (Supabase oauth_tokens table) ────────────────────────────────

def _get_supabase():
    """Return a Supabase client or None."""
    try:
        from backend.supabase_kpi import _get_client
        return _get_client()
    except Exception:
        return None


def _load_token() -> Optional[dict]:
    """Load the QuickBooks token record from Supabase."""
    client = _get_supabase()
    if client is None:
        return None
    try:
        resp = client.table("oauth_tokens").select("*").eq("service", "quickbooks").limit(1).execute()
        if resp.data:
            return resp.data[0]
    except Exception as e:
        logger.warning(f"QB _load_token error: {e}")
    return None


def _save_token(token_data: dict) -> None:
    """Upsert token record in Supabase (keyed by service='quickbooks')."""
    client = _get_supabase()
    if client is None:
        logger.warning("QB _save_token: no Supabase client")
        return
    try:
        payload = {
            "service":       "quickbooks",
            "realm_id":      token_data.get("realm_id"),
            "access_token":  token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "expires_at":    token_data.get("expires_at"),
            "updated_at":    "now()",
        }
        client.table("oauth_tokens").upsert(payload, on_conflict="service").execute()
    except Exception as e:
        logger.warning(f"QB _save_token error: {e}")


# ── OAuth helpers ──────────────────────────────────────────────────────────────

def _qb_redirect_uri() -> str:
    """Build the QuickBooks OAuth redirect URI, respecting APP_BASE_URL in production."""
    explicit = os.getenv("INTUIT_REDIRECT_URI", "")
    if explicit:
        return explicit
    base_url = os.getenv("APP_BASE_URL", "")
    if base_url:
        return f"{base_url}/auth/quickbooks/callback"
    return "http://localhost:8000/auth/quickbooks/callback"


def get_auth_url(state: str) -> str:
    """Build the Intuit OAuth authorization URL."""
    client_id     = os.getenv("INTUIT_CLIENT_ID", "")
    redirect_uri  = _qb_redirect_uri()
    params = {
        "client_id":     client_id,
        "scope":         QB_SCOPE,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "state":         state,
    }
    return f"{QB_AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str, realm_id: str) -> dict:
    """
    Exchange the authorization code for access + refresh tokens.
    Stores the result in Supabase and returns the token dict.
    """
    client_id     = os.getenv("INTUIT_CLIENT_ID", "")
    client_secret = os.getenv("INTUIT_CLIENT_SECRET", "")
    redirect_uri  = _qb_redirect_uri()

    async with httpx.AsyncClient() as http:
        resp = await http.post(
            QB_TOKEN_URL,
            data={
                "grant_type":   "authorization_code",
                "code":         code,
                "redirect_uri": redirect_uri,
            },
            auth=(client_id, client_secret),
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        tokens = resp.json()

    token_data = {
        "realm_id":      realm_id,
        "access_token":  tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
        "expires_at":    int(time.time()) + tokens.get("expires_in", 3600),
    }
    _save_token(token_data)
    logger.info(f"QB exchange_code: tokens stored for realm_id={realm_id}")
    return token_data


async def refresh_token_if_needed() -> Optional[dict]:
    """
    Return a valid token dict, refreshing if the access token is within
    5 minutes of expiry. Returns None if not connected or refresh fails.
    """
    stored = _load_token()
    if not stored:
        return None

    expires_at = stored.get("expires_at") or 0
    if time.time() < (expires_at - 300):
        # Still valid
        return stored

    # Need to refresh
    client_id     = os.getenv("INTUIT_CLIENT_ID", "")
    client_secret = os.getenv("INTUIT_CLIENT_SECRET", "")
    refresh_tok   = stored.get("refresh_token")
    if not refresh_tok:
        return None

    try:
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                QB_TOKEN_URL,
                data={
                    "grant_type":    "refresh_token",
                    "refresh_token": refresh_tok,
                },
                auth=(client_id, client_secret),
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            tokens = resp.json()

        new_data = {
            "realm_id":      stored.get("realm_id"),
            "access_token":  tokens["access_token"],
            "refresh_token": tokens.get("refresh_token", refresh_tok),
            "expires_at":    int(time.time()) + tokens.get("expires_in", 3600),
        }
        _save_token(new_data)
        logger.info("QB token refreshed successfully")
        return new_data
    except Exception as e:
        logger.error(f"QB token refresh failed: {e}")
        return None


def is_connected() -> bool:
    """Return True if QB credentials are configured and a token is stored."""
    if not os.getenv("INTUIT_CLIENT_ID") or not os.getenv("INTUIT_CLIENT_SECRET"):
        return False
    tok = _load_token()
    return bool(tok and tok.get("access_token"))


def get_connection_status() -> dict:
    """Return a dict describing the current QB connection state."""
    tok = _load_token()
    if not tok:
        return {"connected": False, "realm_id": None, "last_sync": None}
    return {
        "connected": bool(tok.get("access_token")),
        "realm_id":  tok.get("realm_id"),
        "last_sync": tok.get("updated_at"),
    }


# ── P&L fetch + parse ──────────────────────────────────────────────────────────

async def fetch_pl_report(period: str = "current_month") -> Optional[dict]:
    """
    Fetch the QuickBooks P&L (ProfitAndLoss) report for the given period.
    period options: 'current_month', 'last_month', 'this_year'
    Returns the raw QBO report dict, or None on failure.
    """
    token = await refresh_token_if_needed()
    if not token:
        return None

    realm_id     = token.get("realm_id")
    access_token = token.get("access_token")

    period_map = {
        "current_month": ("This Month-to-date", None),
        "last_month":    ("Last Month", None),
        "this_year":     ("This Fiscal Year-to-date", None),
    }
    date_macro, _ = period_map.get(period, ("This Month-to-date", None))

    url = (
        f"{QB_API_BASE}/v3/company/{realm_id}/reports/ProfitAndLoss"
        f"?date_macro={date_macro}&minorversion=65"
    )

    try:
        async with httpx.AsyncClient() as http:
            resp = await http.get(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept":        "application/json",
                },
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"fetch_pl_report failed: {e}")
        return None


def _flatten_rows(rows: list) -> list[dict]:
    """
    Recursively walk the QBO report row tree and return a flat list of
    leaf rows: { name: str, amount: float }.
    """
    flat = []
    for row in rows:
        row_type = row.get("type", "")
        if row_type == "Section":
            # Recurse into nested rows
            sub = row.get("Rows", {}).get("Row", [])
            flat.extend(_flatten_rows(sub))
        elif row_type == "Data":
            cells = row.get("ColData", [])
            if len(cells) >= 2:
                name   = str(cells[0].get("value", "")).strip()
                raw_v  = str(cells[1].get("value", "0")).replace(",", "")
                try:
                    amount = float(raw_v)
                except ValueError:
                    amount = 0.0
                flat.append({"name": name, "amount": amount})
    return flat


def _match(name: str, patterns: list[str]) -> bool:
    """Case-insensitive substring match of name against any pattern."""
    lower = name.lower()
    return any(p in lower for p in patterns)


def parse_narpm_metrics(pl_report: dict, door_count: int) -> dict:
    """
    Parse a QBO P&L report dict into NARPM financial metrics.
    Returns a dict with: rpu, ppu, dler, mler, tler, expense_ratio.
    All ratios are None if gross_revenue is 0 or None.
    """
    if not pl_report or not door_count:
        return _null_metrics()

    try:
        rows = pl_report.get("Rows", {}).get("Row", [])
        flat = _flatten_rows(rows)
    except Exception as e:
        logger.error(f"parse_narpm_metrics flatten failed: {e}")
        return _null_metrics()

    gross_revenue  = 0.0
    direct_labor   = 0.0
    mgmt_labor     = 0.0
    total_expenses = 0.0
    net_income     = 0.0

    for item in flat:
        name   = item["name"]
        amount = item["amount"]

        if _match(name, REVENUE_PATTERNS):
            gross_revenue += amount

        if _match(name, DIRECT_LABOR_PATTERNS):
            direct_labor += amount

        if _match(name, MGMT_LABOR_PATTERNS):
            mgmt_labor += amount

    # QBO P&L typically has a "Net Income" summary row
    for item in flat:
        if item["name"].lower() in ("net income", "net profit", "net earnings"):
            net_income = item["amount"]
            break

    # Total expenses = gross_revenue - net_income (standard accounting identity)
    total_expenses = gross_revenue - net_income

    if gross_revenue <= 0:
        return _null_metrics()

    rpu = round(gross_revenue / door_count, 2)
    ppu = round(net_income   / door_count, 2)
    dler         = round(direct_labor   / gross_revenue * 100, 2)
    mler         = round(mgmt_labor     / gross_revenue * 100, 2)
    tler         = round(dler + mler, 2)
    expense_ratio = round(total_expenses / gross_revenue * 100, 2)

    return {
        "rpu":           rpu,
        "ppu":           ppu,
        "dler":          dler,
        "mler":          mler,
        "tler":          tler,
        "expense_ratio": expense_ratio,
        "gross_revenue": round(gross_revenue, 2),
        "net_income":    round(net_income, 2),
        "door_count":    door_count,
    }


def _null_metrics() -> dict:
    return {
        "rpu":           None,
        "ppu":           None,
        "dler":          None,
        "mler":          None,
        "tler":          None,
        "expense_ratio": None,
        "gross_revenue": None,
        "net_income":    None,
        "door_count":    None,
    }
