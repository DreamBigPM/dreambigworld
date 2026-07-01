"""
supabase_sync.py — Full Rentvine → Supabase data sync.

Pulls all properties, units, leases, and tenants from Rentvine's report API
and writes them to Supabase with correct foreign key associations.

Why this exists: the original TypeScript sync was getting 404s because it
was hitting the wrong Rentvine base URL. This Python version uses the same
auth pattern that already works in rentvine_mcp.py.

Run from the dashboard admin endpoint: POST /api/admin/sync-supabase
Or from the daily scheduler at 4:00 AM.

Order matters — must go: properties → units → leases → tenants
because each table's foreign key points to the previous.
"""

import json
import logging
import os
from datetime import date

import httpx

logger = logging.getLogger(__name__)

_REPORT_BASE = "https://dreambig.rentvine.com/api/manager/reports"

_LEASE_STATUS_MAP = {
    1: "Pending",
    2: "Active",
    3: "Month-to-Month",
    4: "Closed",
    5: "Eviction",
    6: "Closed",
    7: "Closed",
    8: "Closed",
}


def _rv_headers() -> dict:
    import base64
    key     = os.getenv("RENTVINE_API_KEY", "")
    secret  = os.getenv("RENTVINE_API_SECRET", "")
    account = os.getenv("RENTVINE_ACCOUNT", "dreambig")
    token   = base64.b64encode(f"{key}:{secret}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "X-Rentvine-Account": account,
        "Accept": "application/json",
    }


async def _fetch(route: str, columns: list, filters: list = None) -> list[dict]:
    query = {"displayColumns": columns}
    if filters:
        query["filters"] = filters
    params = {
        "exportTypeID": "1",
        "json": json.dumps(query),
        "orientation": "2",
        "showHeader": "true",
    }
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(
            f"{_REPORT_BASE}/{route}",
            headers=_rv_headers(),
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()
        return [r["data"] for r in data.get("rows", []) if r.get("data")]


def _int(val):
    if val is None:
        return None
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        return None


def _float(val):
    if val is None:
        return None
    s = str(val).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _str(val):
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _date(val):
    if not val:
        return None
    s = str(val).strip()
    if not s:
        return None
    from datetime import datetime
    for fmt in ("%B %d, %Y", "%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


async def run_full_sync(dry_run: bool = False) -> dict:
    """
    Sync all Rentvine data into Supabase.

    Set dry_run=True to fetch and count without writing anything.
    Returns a summary dict.
    """
    from backend.supabase_kpi import _get_client
    client = _get_client()
    today = date.today().isoformat()
    summary = {"date": today, "dry_run": dry_run, "errors": []}

    # ── 1. PROPERTIES ──────────────────────────────────────────────────────────

    logger.info("Sync: fetching properties from Rentvine (active + inactive)...")
    # Fetch ALL properties — no isActive filter — so offboarded/sold properties
    # still exist in Supabase with is_active=false, giving closed leases valid references.
    _prop_cols = [
        "propertyID", "portfolioID", "propertyAddress", "propertyCity",
        "propertyStateID", "propertyPostalCode", "county",
        "propertyName", "propertyTypeID",
        "unitCount", "yearBuilt", "reserveAmount", "maintenanceLimitAmount",
        "dateContractBegins", "dateContractEnds", "maintenanceNotes",
        "dateInsuranceExpires", "insuranceCompany", "insurancePolicyNumber",
        "contacts", "ownerEmails",
    ]
    prop_rows_active   = await _fetch("property", _prop_cols,
                                      [{"name": "isActive", "comparator": "booleanTrue"}])
    prop_rows_inactive = await _fetch("property", _prop_cols,
                                      [{"name": "isActive", "comparator": "booleanFalse"}])
    active_ids = {str(_int(p.get("propertyID"))) for p in prop_rows_active}
    prop_rows  = prop_rows_active + prop_rows_inactive
    logger.info(f"Sync: got {len(prop_rows_active)} active + {len(prop_rows_inactive)} inactive properties")

    prop_records = []
    for p in prop_rows:
        pid = _int(p.get("propertyID"))
        if not pid:
            continue
        prop_records.append({
            "rentvine_id":      str(pid),
            "address":          _str(p.get("propertyAddress")),
            "city":             _str(p.get("propertyCity")),
            "state":            _str(p.get("propertyStateID")),
            "zip":              _str(p.get("propertyPostalCode")),
            "name":             _str(p.get("propertyName")),
            "property_type":    _str(p.get("propertyTypeID")),
            "unit_count":       _int(p.get("unitCount")),
            "year_built":       _int(p.get("yearBuilt")),
            "reserve":          _float(p.get("reserveAmount")),
            "contract_start":   _date(p.get("dateContractBegins")),
            "contract_end":     _date(p.get("dateContractEnds")),
            "maintenance_notes":      _str(p.get("maintenanceNotes")),
            "portfolio_rentvine_id":  _str(_int(p.get("portfolioID"))),
            "owner_names":            _str(p.get("contacts")),
            "owner_emails":           _str(p.get("ownerEmails")),
            "maintenance_limit":      _float(p.get("maintenanceLimitAmount")),
            "insurance_expiry":       _date(p.get("dateInsuranceExpires")),
            "insurance_company":      _str(p.get("insuranceCompany")),
            "insurance_policy":       _str(p.get("insurancePolicyNumber")),
            "county":                 _str(p.get("county")),
            "is_active":              str(pid) in active_ids,
            "synced_at":              today,
        })

    summary["properties_fetched"] = len(prop_records)
    if not dry_run and prop_records:
        try:
            client.table("properties").upsert(prop_records, on_conflict="rentvine_id").execute()
            logger.info(f"Sync: upserted {len(prop_records)} properties")
            summary["properties_synced"] = len(prop_records)
        except Exception as e:
            logger.error(f"Sync: properties upsert failed: {e}")
            summary["errors"].append(f"properties: {e}")

    # Build property rentvine_id → UUID map for use in units
    prop_map: dict[str, str] = {}
    if not dry_run:
        try:
            resp = client.table("properties").select("id, rentvine_id").execute()
            prop_map = {r["rentvine_id"]: r["id"] for r in resp.data}
            logger.info(f"Sync: loaded {len(prop_map)} property ID mappings")
        except Exception as e:
            logger.error(f"Sync: failed to load property map: {e}")
            summary["errors"].append(f"property_map: {e}")

    # ── 2. UNITS ───────────────────────────────────────────────────────────────

    logger.info("Sync: fetching units from Rentvine...")
    unit_rows = await _fetch("unit", [
        "unitID", "propertyID", "unitName", "unitAddress",
        "beds", "fullBaths", "halfBaths", "size",
    ])
    logger.info(f"Sync: got {len(unit_rows)} units")

    unit_records = []
    seen_unit_ids: set = set()
    for u in unit_rows:
        uid = _int(u.get("unitID"))
        pid = _int(u.get("propertyID"))
        if not uid:
            continue
        uid_str = str(uid)
        if uid_str in seen_unit_ids:
            continue
        seen_unit_ids.add(uid_str)
        prop_uuid = prop_map.get(str(pid)) if pid else None
        record = {
            "rentvine_id":  uid_str,
            "unit_number":  _str(u.get("unitName")) or _str(u.get("unitAddress")),
            "bedrooms":     _float(u.get("beds")),
            "bathrooms":    _float(u.get("fullBaths")),
            "square_feet":  _float(u.get("size")),
            "synced_at":    today,
        }
        if prop_uuid:
            record["property_id"] = prop_uuid
        unit_records.append(record)

    summary["units_fetched"] = len(unit_records)
    if not dry_run and unit_records:
        try:
            client.table("units").upsert(unit_records, on_conflict="rentvine_id").execute()
            logger.info(f"Sync: upserted {len(unit_records)} units")
            summary["units_synced"] = len(unit_records)
        except Exception as e:
            logger.error(f"Sync: units upsert failed: {e}")
            summary["errors"].append(f"units: {e}")

    # Build unit rentvine_id → UUID map for use in leases
    unit_map: dict[str, str] = {}
    if not dry_run:
        try:
            resp = client.table("units").select("id, rentvine_id").execute()
            unit_map = {r["rentvine_id"]: r["id"] for r in resp.data}
            logger.info(f"Sync: loaded {len(unit_map)} unit ID mappings")
        except Exception as e:
            logger.error(f"Sync: failed to load unit map: {e}")
            summary["errors"].append(f"unit_map: {e}")

    # ── 3. LEASES — active/pending/MTM from rent-roll + all history from lease report ──

    logger.info("Sync: fetching active leases from rent-roll...")
    # leaseStatusID filter is silently ignored by the API — fetch all and filter client-side
    rr_rows = await _fetch("rent-roll", [
        "leaseID", "unitID", "propertyID", "leaseStatusID",
        "startDate", "endDate", "moveInDate", "expectedMoveOutDate",
        "increaseEligibilityDate", "noticeDate",
        "moveOutDate", "closedDate", "closedDescription", "moveOutReason",
        "moveOutUnitAvailabilityDate",
        "expectedMonthlyRentAmount", "marketRent",
        "balanceDue", "depositBalance", "lastPaymentDate", "lastPaymentAmount",
        "isPortalDisabled", "leaseType",
    ])

    # Also fetch ALL leases (including historical closed ones) from the lease report.
    # The rent-roll only returns active/current data; the lease report has full history.
    # Closed status IDs: 6 = Closed, 7 = Closed (sold/cancelled)
    logger.info("Sync: fetching full lease history from lease report...")
    hist_rows = await _fetch("lease", [
        "leaseID", "unitID", "propertyID", "leaseStatusID",
        "startDate", "endDate", "moveInDate", "expectedMoveOutDate",
        "increaseEligibilityDate", "noticeDate",
        "moveOutDate", "closedDate", "closedDescription", "moveOutReason",
        "moveOutUnitAvailabilityDate",
        "rentAmount", "marketRentAmount", "isPortalDisabled",
    ])

    # Merge: rent-roll rows first (they have expectedMonthlyRentAmount); lease report fills gaps
    seen_lease_ids: set = set()
    combined: list = []
    for l in rr_rows:
        lid = str(_int(l.get("leaseID")) or "")
        if lid and lid not in seen_lease_ids:
            seen_lease_ids.add(lid)
            l["_rent_amount"] = l.get("expectedMonthlyRentAmount")
            combined.append(l)
    for l in hist_rows:
        lid = str(_int(l.get("leaseID")) or "")
        if lid and lid not in seen_lease_ids:
            seen_lease_ids.add(lid)
            l["_rent_amount"] = l.get("rentAmount")
            combined.append(l)

    logger.info(f"Sync: {len(rr_rows)} rent-roll + {len(hist_rows)} lease report = {len(combined)} unique leases")

    lease_records = []
    for l in combined:
        lid = _int(l.get("leaseID"))
        uid = _int(l.get("unitID"))
        status_id = _int(l.get("leaseStatusID"))
        if not lid:
            continue
        # Skip junk end_dates far in the future for closed leases (data entry error in Rentvine)
        raw_end = _date(l.get("endDate"))
        if raw_end and raw_end > "2040-01-01" and status_id in (6, 7):
            raw_end = _date(l.get("moveOutDate")) or raw_end
        unit_uuid = unit_map.get(str(uid)) if uid else None
        record = {
            "rentvine_id":   str(lid),
            "start_date":    _date(l.get("startDate")),
            "end_date":      raw_end,
            "move_in_date":  _date(l.get("moveInDate")),
            "expected_moveout_date":    _date(l.get("expectedMoveOutDate")),
            "increase_eligibility_date": _date(l.get("increaseEligibilityDate")),
            "notice_date":         _date(l.get("noticeDate")),
            "move_out_date":       _date(l.get("moveOutDate")),
            "closed_date":         _date(l.get("closedDate")),
            "closed_reason":       _str(l.get("closedDescription")),
            "move_out_reason":     _str(l.get("moveOutReason")),
            "unit_available_date": _date(l.get("moveOutUnitAvailabilityDate")),
            "market_rent":         _float(l.get("marketRent") or l.get("marketRentAmount")),
            "balance_due":         _float(l.get("balanceDue")),
            "deposit_balance":     _float(l.get("depositBalance")),
            "last_payment_date":   _date(l.get("lastPaymentDate")),
            "last_payment_amount": _float(l.get("lastPaymentAmount")),
            "monthly_rent":  _float(l.get("_rent_amount")),
            "status":        _LEASE_STATUS_MAP.get(status_id, "Closed"),
            "portal_access": not bool(l.get("isPortalDisabled")),
            "synced_at":     today,
        }
        if unit_uuid:
            record["unit_id"] = unit_uuid
        lease_records.append(record)

    summary["leases_fetched"] = len(lease_records)
    if not dry_run and lease_records:
        try:
            client.table("leases").upsert(lease_records, on_conflict="rentvine_id").execute()
            logger.info(f"Sync: upserted {len(lease_records)} leases")
            summary["leases_synced"] = len(lease_records)
        except Exception as e:
            logger.error(f"Sync: leases upsert failed: {e}")
            summary["errors"].append(f"leases: {e}")

    # Build lease rentvine_id → UUID map for use in tenants
    lease_map: dict[str, str] = {}
    if not dry_run:
        try:
            resp = client.table("leases").select("id, rentvine_id").execute()
            lease_map = {r["rentvine_id"]: r["id"] for r in resp.data}
            logger.info(f"Sync: loaded {len(lease_map)} lease ID mappings")
        except Exception as e:
            logger.error(f"Sync: failed to load lease map: {e}")
            summary["errors"].append(f"lease_map: {e}")

    # ── 4. TENANTS (from tenant report — unlike lease-tenants, this has data) ──

    logger.info("Sync: fetching tenants from Rentvine...")
    # Tenant report uses contactID (not tenantID) and contactName (not firstName/lastName).
    # Only request safe fields — text_1 is a custom field that may contain SSNs; never sync it.
    tenant_rows = await _fetch("tenant", [
        "contactID", "leaseID", "contactName",
        "email", "phone", "leaseStatusID",
    ], [{"name": "leaseStatusID", "comparator": "in", "values": [1, 2, 3]}])
    logger.info(f"Sync: got {len(tenant_rows)} tenant rows")

    # leaseStatusID filter is silently ignored by Rentvine — tenants may appear for
    # multiple leases (old + renewed). Keep the row with the highest leaseID (most recent).
    best_by_contact: dict = {}  # cid_str → (lid, row)
    for t in tenant_rows:
        cid = _int(t.get("contactID"))
        lid = _int(t.get("leaseID")) or 0
        if not cid:
            continue
        cid_str = str(cid)
        if cid_str not in best_by_contact or lid > best_by_contact[cid_str][0]:
            best_by_contact[cid_str] = (lid, t)

    tenant_records = []
    for cid_str, (lid, t) in best_by_contact.items():
        status_id = _int(t.get("leaseStatusID"))

        # Split "FirstName LastName" → first_name, last_name
        full_name = _str(t.get("contactName")) or ""
        parts = full_name.split(" ", 1)
        first_name = parts[0] if parts else None
        last_name  = parts[1] if len(parts) > 1 else None

        lease_uuid = lease_map.get(str(lid)) if lid else None
        record = {
            "rentvine_id":  cid_str,
            "first_name":   first_name,
            "last_name":    last_name,
            "email":        _str(t.get("email")),
            "phone":        _str(t.get("phone")),
            "status":       _LEASE_STATUS_MAP.get(status_id, "Active"),
            "synced_at":    today,
        }
        if lease_uuid:
            record["lease_id"] = lease_uuid
        tenant_records.append(record)

    summary["tenants_fetched"] = len(tenant_records)
    if not dry_run and tenant_records:
        try:
            client.table("tenants").upsert(tenant_records, on_conflict="rentvine_id").execute()
            logger.info(f"Sync: upserted {len(tenant_records)} tenants")
            summary["tenants_synced"] = len(tenant_records)
        except Exception as e:
            logger.error(f"Sync: tenants upsert failed: {e}")
            summary["errors"].append(f"tenants: {e}")

    logger.info(f"Sync complete: {summary}")
    return summary
