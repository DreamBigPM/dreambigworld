"""
rentvine_mcp.py — Rentvine report data for the dashboard.

Uses the Rentvine web app's internal report API to pull live charge data.
The MCP text output is capped at 25 records; this endpoint returns all rows.
"""

import base64
import json
import logging
import os
from collections import defaultdict
from datetime import date

import httpx

logger = logging.getLogger(__name__)

_REPORT_BASE = "https://dreambig.rentvine.com/api/manager/reports"

_DISPLAY_COLUMNS = [
    "datePosted", "dateDue", "leaseID", "tenants", "unitAddress",
    "unitCity", "unitStateID", "portfolioName",
    "amountDue", "amount", "amountPaid", "description", "accountName"
]


def _rent_still_due_query(lease_status_id: int) -> str:
    # leaseStatusID in/notIn are silently ignored by the API — must query one status at a time.
    # Called twice: once for Active (2), once for Pending (1, covers move-ins with deposits due).
    return json.dumps({
        "displayColumns": _DISPLAY_COLUMNS,
        "filters": [
            {"name": "datePosted", "comparator": "onOrBeforeDateToday"},
            {"name": "isVoided", "comparator": "equals", "value": False},
            {"name": "amountDue", "comparator": "greaterThan", "value": 0},
            {"name": "leaseStatusID", "comparator": "equals", "value": lease_status_id},
        ],
    })


def _headers() -> dict:
    key = os.getenv("RENTVINE_API_KEY", "")
    secret = os.getenv("RENTVINE_API_SECRET", "")
    account = os.getenv("RENTVINE_ACCOUNT", "dreambig")
    token = base64.b64encode(f"{key}:{secret}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "X-Rentvine-Account": account,
        "Accept": "application/json",
    }


async def _run_report(route: str, query_json: str) -> list[dict]:
    """Call the Rentvine report export API and return the rows list."""
    url = f"{_REPORT_BASE}/{route}"
    params = {"exportTypeID": "1", "json": query_json, "orientation": "2", "showHeader": "true"}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers=_headers(), params=params)
        resp.raise_for_status()
        data = resp.json()
        return [r["data"] for r in data.get("rows", []) if r.get("data")]


async def fetch_rent_still_due() -> list[dict]:
    """
    Pull unpaid charges from the last 90 days for all active leases.
    Groups by lease and returns one row per lease sorted by balance desc.

    Each record: {lease_id, tenant_name, unit, property, balance,
                  rent_due, fees_due, days_late}
    """
    try:
        import asyncio as _asyncio
        active_rows, pending_rows = await _asyncio.gather(
            _run_report("lease-charges", _rent_still_due_query(2)),
            _run_report("lease-charges", _rent_still_due_query(1)),
        )
        rows = active_rows + pending_rows
    except Exception as e:
        logger.error(f"fetch_rent_still_due failed: {e}")
        return []

    if not rows:
        return []

    today = date.today()
    first_of_month = today.replace(day=1)
    days_late_default = (today - first_of_month).days

    # Group by leaseID
    by_lease: dict = defaultdict(lambda: {
        "lease_id": None, "tenant_name": "", "unit": "", "property": "",
        "balance": 0.0, "rent_due": 0.0, "fees_due": 0.0,
        "earliest_date": None,
    })

    for r in rows:
        lid = str(r.get("leaseID", ""))
        d = by_lease[lid]
        d["lease_id"] = lid
        d["tenant_name"] = r.get("tenants", "")
        d["unit"] = r.get("unitAddress", "")
        d["property"] = (
            f"{r.get('unitAddress','')} {r.get('unitCity','')} {r.get('unitStateID','')}"
        ).strip()

        amount_due = float(r.get("amountDue") or 0)
        d["balance"] += amount_due

        account = (r.get("accountName") or "").lower()
        desc = (r.get("description") or "").lower()
        if "rent" in account or "rent" in desc:
            d["rent_due"] += amount_due
        else:
            d["fees_due"] += amount_due

        due = r.get("dateDue") or r.get("datePosted") or ""
        if due and (d["earliest_date"] is None or due < d["earliest_date"]):
            d["earliest_date"] = due

    result = []
    for data in sorted(by_lease.values(), key=lambda x: -x["balance"]):
        # days_late = days since earliest unpaid charge
        days_late = days_late_default
        if data["earliest_date"]:
            try:
                charge_date = date.fromisoformat(data["earliest_date"])
                days_late = (today - charge_date).days
            except ValueError:
                pass

        result.append({
            "lease_id": data["lease_id"],
            "tenant_name": data["tenant_name"],
            "unit": data["unit"],
            "property": data["property"],
            "balance": round(data["balance"], 2),
            "rent_due": round(data["rent_due"], 2),
            "fees_due": round(data["fees_due"], 2),
            "days_late": days_late,
            "last_payment_date": None,
        })

    return result


async def fetch_renewal_calendar() -> dict:
    """
    Pull all active AND month-to-month leases from Rentvine.

    Uses increaseEligibilityDate as the renewal target date — when Brian must
    decide to renew or not. lease_date_2 (Renewal Start Date) is set by Brian
    when he writes a new renewal contract.

    Calendar groups upcoming renewals by increaseEligibilityDate month.
    Historical rate: of leases whose eligibility date passed in last 12 months,
    how many have lease_date_2 set?

    Returns:
      calendar:        [{month_start, month_label, count, total_new_rent}] sorted
      records:         all individual lease records with renewal data
      needs_renewal:   leases with eligibility date within 90 days, no lease_date_2
      history:         leases with eligibility date in past 12 months + renewed flag
      history_total:   count of history rows
      history_renewed: count where lease_date_2 was set
      history_rate:    renewal rate % (history_renewed / history_total * 100)
    """
    from datetime import date as _date, timedelta
    from collections import defaultdict
    import asyncio as _asyncio

    cols = [
        "leaseID", "tenants", "unitAddress", "unitCity", "propertyName",
        "increaseEligibilityDate", "endDate", "leaseStatusID",
        "lease_date_2", "lease_date_3", "lease_numeric_1",
        "expectedMonthlyRentAmount",
    ]

    try:
        active_rows, mtm_rows = await _asyncio.gather(
            _run_report("rent-roll", json.dumps({
                "displayColumns": cols,
                "filters": [{"name": "leaseStatusID", "comparator": "equals", "value": 2}],
            })),
            _run_report("rent-roll", json.dumps({
                "displayColumns": cols,
                "filters": [{"name": "leaseStatusID", "comparator": "equals", "value": 3}],
            })),
        )
        rows = active_rows + mtm_rows
    except Exception as e:
        logger.error(f"fetch_renewal_calendar failed: {e}")
        return {}

    today = _date.today()
    ninety_days = today + timedelta(days=90)
    twelve_months_ago = today - timedelta(days=365)

    records = []
    needs_renewal = []
    history = []
    by_month: dict = defaultdict(lambda: {"count": 0, "total_new_rent": 0.0})

    for r in rows:
        renewal_start    = r.get("lease_date_2") or ""
        renewal_end      = r.get("lease_date_3") or ""
        renewal_rent_raw = str(r.get("lease_numeric_1") or "0").replace("$", "").replace(",", "").strip()
        current_rent_raw = str(r.get("expectedMonthlyRentAmount") or "0").replace("$", "").replace(",", "").strip()
        elig_date_raw    = r.get("increaseEligibilityDate") or ""
        end_date_raw     = r.get("endDate") or ""
        status_id        = int(r.get("leaseStatusID") or 0)

        try:
            renewal_rent = float(renewal_rent_raw)
        except ValueError:
            renewal_rent = 0.0
        try:
            current_rent = float(current_rent_raw)
        except ValueError:
            current_rent = 0.0

        # increaseEligibilityDate is the renewal target; fall back to endDate for
        # fixed-term leases that don't have it set
        target_raw = elig_date_raw or end_date_raw

        record = {
            "lease_id":      str(r.get("leaseID", "")),
            "tenant_name":   r.get("tenants", ""),
            "unit_label":    r.get("unitAddress", ""),
            "property_name": r.get("propertyName", r.get("unitAddress", "")),
            "current_rent":  current_rent,
            "renewal_start": renewal_start,
            "renewal_end":   renewal_end,
            "renewal_rent":  renewal_rent,
            "end_date":      end_date_raw,
            "elig_date":     elig_date_raw,
            "target_date":   target_raw,
            "status_id":     status_id,
        }

        if target_raw:
            try:
                target_date = _date.fromisoformat(target_raw[:10])
                ym_key      = target_date.strftime("%Y-%m")
                month_label = target_date.strftime("%b %Y")
                month_start = target_date.replace(day=1).isoformat()
                record["month_start"] = month_start
                record["month_label"] = month_label

                # Calendar: upcoming eligibility dates grouped by month
                if target_date >= today:
                    by_month[ym_key]["month_start"]    = month_start
                    by_month[ym_key]["month_label"]    = month_label
                    by_month[ym_key]["count"]         += 1
                    by_month[ym_key]["total_new_rent"] += renewal_rent

                # Needs renewal: eligibility within 90 days, no renewal written
                if today <= target_date <= ninety_days and not renewal_start:
                    needs_renewal.append(record)

                # Historical: eligibility date was in past 12 months
                if twelve_months_ago <= target_date < today:
                    record["renewed"] = bool(renewal_start)
                    history.append(record)

            except (ValueError, TypeError):
                pass

        records.append(record)

    calendar = sorted(
        [{"month_start": v["month_start"], "month_label": v["month_label"],
          "count": v["count"], "total_new_rent": round(v["total_new_rent"], 2)}
         for v in by_month.values() if "month_start" in v],
        key=lambda x: x["month_start"]
    )

    hist_total   = len(history)
    hist_renewed = sum(1 for h in history if h.get("renewed"))
    hist_rate    = round(hist_renewed / hist_total * 100, 1) if hist_total > 0 else None

    return {
        "calendar":        calendar,
        "records":         records,
        "needs_renewal":   needs_renewal,
        "history":         history,
        "history_total":   hist_total,
        "history_renewed": hist_renewed,
        "history_rate":    hist_rate,
    }


async def fetch_monthly_rent_roll() -> dict:
    """
    Pull total expected and collected rent for the current month from Rentvine.
    Returns {expected_usd, collected_usd, pct, charge_count}

    Uses the lease-charges report filtered to current month charges, regardless
    of payment status — so this reflects the true $300k/month portfolio total,
    not just what delinquent tenants owe.
    """
    from datetime import date as _date
    today = _date.today()
    first_of_month = today.replace(day=1).isoformat()

    query = json.dumps({
        "displayColumns": [
            "datePosted", "leaseID", "leaseStatusID",
            "amount", "amountPaid", "amountDue",
            "isVoided", "accountName",
        ],
        "filters": [
            {"name": "datePosted", "comparator": "onOrBeforeDateToday"},
            {"name": "isVoided", "comparator": "equals", "value": False},
            {"name": "leaseStatusID", "comparator": "equals", "value": 2},
        ],
    })

    try:
        rows = await _run_report("lease-charges", query)
    except Exception as e:
        logger.error(f"fetch_monthly_rent_roll failed: {e}")
        return {}

    expected = 0.0
    collected = 0.0
    charge_count = 0

    for r in rows:
        posted = str(r.get("datePosted") or "")
        if not posted.startswith(today.strftime("%Y-%m")):
            continue
        amount = float(r.get("amount") or 0)
        paid = float(r.get("amountPaid") or 0)
        expected += amount
        collected += paid
        charge_count += 1

    if expected == 0:
        return {}

    return {
        "expected_usd": round(expected, 2),
        "collected_usd": round(collected, 2),
        "pct": round(collected / expected * 100, 1),
        "charge_count": charge_count,
    }


async def fetch_vacancy() -> list[dict]:
    """
    Pull live vacancy data from Rentvine vacancy report.
    Returns one record per truly-vacant unit, sorted by revenue lost desc.

    Each record: {unit_id, unit_label, property_name, days_vacant,
                  daily_cost, total_loss, move_in_date, days_until_occupied}
    """
    try:
        query = json.dumps({
            "displayColumns": [
                "unitID", "unitAddress", "unitCity", "unitStateID", "unitPostalCode",
                "propertyName", "rent", "daysVacant", "daysUntilOccupied",
                "moveInDate", "lastMoveOutDate", "availabilityDate",
            ],
        })
        rows = await _run_report("vacancy", query)
    except Exception as e:
        logger.error(f"fetch_vacancy failed: {e}")
        return []

    result = []
    for r in rows:
        rent_str = str(r.get("rent") or "0").replace("$", "").replace(",", "").strip()
        try:
            monthly_rent = float(rent_str)
        except ValueError:
            monthly_rent = 0.0

        days_vacant = int(r.get("daysVacant") or 0)
        # Use availabilityDate when it predates the full daysVacant span — prevents
        # inflated counts for newly-onboarded properties that were vacant before management started.
        avail_raw = r.get("availabilityDate") or ""
        if avail_raw:
            try:
                from datetime import date as _date
                avail_date = _date.fromisoformat(avail_raw)
                avail_days = (_date.today() - avail_date).days
                if 0 < avail_days < days_vacant:
                    days_vacant = avail_days
            except (ValueError, TypeError):
                pass
        days_until = r.get("daysUntilOccupied")
        try:
            days_until_occupied = int(days_until) if days_until else None
        except (ValueError, TypeError):
            days_until_occupied = None

        daily_cost = round(monthly_rent / 30, 2) if monthly_rent > 0 else 0.0
        total_loss = round(daily_cost * days_vacant, 2)

        city = r.get("unitCity", "")
        state = r.get("unitStateID", "")
        postal = r.get("unitPostalCode", "")
        addr = r.get("unitAddress", "")
        prop_name = r.get("propertyName", addr)
        full_address = f"{addr}, {city}, {state} {postal}".strip(", ")

        result.append({
            "unit_id": str(r.get("unitID", "")),
            "unit_label": addr,
            "property_name": full_address,
            "days_vacant": days_vacant,
            "daily_cost": daily_cost,
            "total_loss": total_loss,
            "move_in_date": r.get("moveInDate") or None,
            "days_until_occupied": days_until_occupied,
            "monthly_rent": monthly_rent,
        })

    result.sort(key=lambda x: -x["total_loss"])
    return result
