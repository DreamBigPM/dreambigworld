"""
rentvine.py — Async Rentvine REST API client.

All calls go through _fetch_all_pages() which handles pagination automatically.
Errors are caught and logged — callers receive empty lists/dicts rather than crashes.
"""

import base64
import os
import logging
from datetime import date
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

_API_KEY = None
_API_SECRET = None
_ACCOUNT = None
_BASE_URL = None


def _init():
    global _API_KEY, _API_SECRET, _ACCOUNT, _BASE_URL
    _API_KEY = os.getenv("RENTVINE_API_KEY", "")
    _API_SECRET = os.getenv("RENTVINE_API_SECRET", "")
    _ACCOUNT = os.getenv("RENTVINE_ACCOUNT", "dreambig")
    _BASE_URL = os.getenv("RENTVINE_BASE_URL", "https://api.rentvine.com/v1").rstrip("/")


def _headers() -> dict:
    if not _API_KEY:
        _init()
    token = base64.b64encode(f"{_API_KEY}:{_API_SECRET}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "X-Rentvine-Account": _ACCOUNT,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


async def _get(path: str, params: dict = None) -> dict:
    """Single GET request. Returns parsed JSON or empty dict on error."""
    if not _API_KEY:
        _init()
    url = f"{_BASE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=_headers(), params=params or {})
            if resp.status_code == 401:
                logger.error("Rentvine API: 401 Unauthorized — check RENTVINE_API_KEY and RENTVINE_API_SECRET")
                return {}
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        logger.warning(f"Rentvine API GET {path} failed: {e}")
        return {}
    except Exception as e:
        logger.warning(f"Rentvine API GET {path} unexpected error: {e}")
        return {}


async def _fetch_all_pages(path: str, params: dict = None) -> list:
    """Paginate through all pages and return combined list."""
    if not _API_KEY:
        _init()
    params = dict(params or {})
    params["pageSize"] = "100"
    records = []
    page = 1

    while True:
        params["page"] = str(page)
        data = await _get(path, params)

        if not data:
            break

        items = (
            data.get("data")
            or data.get("items")
            or data.get("results")
            or (data if isinstance(data, list) else [])
        )

        if not isinstance(items, list) or not items:
            break

        records.extend(items)

        total = data.get("total") or data.get("totalCount") or data.get("totalItems")
        if total and records and len(records) >= int(total):
            break

        page += 1
        if page > 50:
            logger.warning(f"Rentvine: hit 50-page safety limit on {path}")
            break

    return records


async def fetch_properties() -> list:
    return await _fetch_all_pages("/properties")


async def fetch_units(property_id: Optional[str] = None) -> list:
    params = {}
    if property_id:
        params["propertyId"] = str(property_id)
    return await _fetch_all_pages("/units", params)


async def fetch_leases(status: Optional[str] = None) -> list:
    params = {}
    if status:
        params["status"] = status
    return await _fetch_all_pages("/leases", params)


async def fetch_lease_tenants(lease_id: str) -> list:
    return await _fetch_all_pages(f"/leases/{lease_id}/tenants")


async def fetch_lease_charges(lease_id: str) -> list:
    return await _fetch_all_pages(f"/leases/{lease_id}/charges")


async def fetch_transactions(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list:
    params = {}
    if start_date:
        params["startDate"] = start_date
    if end_date:
        params["endDate"] = end_date
    return await _fetch_all_pages("/transactions", params)


async def fetch_lease_balance(lease_id: str) -> dict:
    return await _get(f"/leases/{lease_id}/balance")


async def fetch_work_orders(status: Optional[str] = None) -> list:
    params = {}
    if status:
        params["status"] = status
    return await _fetch_all_pages("/workOrders", params)


async def fetch_work_order_detail(work_order_id: str) -> dict:
    return await _get(f"/workOrders/{work_order_id}")


async def fetch_inspections(property_id: Optional[str] = None) -> list:
    params = {}
    if property_id:
        params["propertyId"] = str(property_id)
    return await _fetch_all_pages("/inspections", params)


async def fetch_owners() -> list:
    return await _fetch_all_pages("/owners")


async def fetch_renewals() -> list:
    return await _fetch_all_pages("/leaseRenewals")


async def fetch_bills(start_date: Optional[str] = None) -> list:
    params = {}
    if start_date:
        params["startDate"] = start_date
    return await _fetch_all_pages("/bills", params)
