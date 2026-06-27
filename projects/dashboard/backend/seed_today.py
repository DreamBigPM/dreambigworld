"""
seed_today.py — One-time seed of the SQLite database with real Rentvine data
fetched via MCP on 2026-06-27.

Run once:  cd /Users/brianbean/CODE/dreambigworld/projects/dashboard
           python -m backend.seed_today

Data sources / confidence:
- open_work_orders: 52  (counted from 300 most recent WOs across 3 pages: 26+13+13 Open)
- overdue_work_orders: 48  (estimate: most HVAC batch WOs are 10-25 days old, all overdue)
- occupancy_pct: 94.1 / active_leases: 111  (118 total - 7 confirmed vacant per Rentvine Units view)
- vacant_units: 7  (confirmed from Rentvine Units view filtered by Active + Non-Revenue + Vacant)
- delinquent_count: 8  (MCP list_leases with has_overdue_balance=true — unchanged)
- rent_collected_pct: 93.0  (estimate — 8 delinquent/108 active, partial payments seen)
- avg_days_on_market: 120  (pmdash.io baseline — 6x the 21-day target)
- google_rating: 5.0  (confirmed baseline from plan — 5.0 stars / 42 reviews)
- total_units: 118  (120 - 2 offboarded: 7882 Angus Way + 6332 Brockton Ave)
- total_properties: 117  (119 - 2 offboarded)

Vacant units (2026-06-27) — confirmed from Rentvine Units view (Active + Non-Revenue + Vacant):
    1. 1493 Evergreen Ave, Beaumont — Vacant Pre-leased, new tenant July 1
    2. 26229 Cambria Ln, Loma Linda — Vacant Pre-leased, new tenant July 1
    3. 3605 E Delight Paseo #166, Ontario — Vacant
    4. 15982 Sand Hills Court, Moreno Valley — Vacant
    5. 1365 Stillman Ave, Redlands — Vacant (Apartment)
    6. 5971 Sunland Place, Riverside — Vacant
    7. 7963 Townsend Dr, Jurupa Valley — Vacant
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import database
from backend.sync import sync_snapshot

# ---------------------------------------------------------------------------
# Delinquent leases (from list_leases with has_overdue_balance=true, 2026-06-27)
# ---------------------------------------------------------------------------
DELINQUENT_LEASES = [
    {
        "lease_id": "130",
        "tenant_name": "Ivan Rios Orozco / Sarai Guzman",
        "unit": "509 West Lorraine Place, Rialto, CA",
        "property": "509 W Lorraine Pl, Rialto",
        "balance": 0,  # partial payments seen in June, credit applied
        "days_late": 27,
        "last_payment_date": "2026-06-13",
    },
    {
        "lease_id": "67",
        "tenant_name": "Raquel Romero",
        "unit": "8821 Holly Lane, Riverside, CA",
        "property": "8821 Holly Lane, Riverside",
        "balance": 0,
        "days_late": 27,
        "last_payment_date": "2026-06-24",
    },
    {
        "lease_id": "190",
        "tenant_name": "Hosanna Jackson",
        "unit": "12365 Marquette Ct, Moreno Valley, CA",
        "property": "12365 Marquette Ct, Moreno Valley",
        "balance": 0,
        "days_late": 27,
        "last_payment_date": "",
    },
    {
        "lease_id": "148",
        "tenant_name": "Beatriz Diaz / Enrique Diaz",
        "unit": "1210 Clay Street, Redlands, CA",
        "property": "1210 Clay Street, Redlands",
        "balance": 0,
        "days_late": 27,
        "last_payment_date": "",
    },
    {
        "lease_id": "146",
        "tenant_name": "Susana De La Rosa / Robert Diaz",
        "unit": "1208 Clay Street, Redlands, CA",
        "property": "1208 Clay Street, Redlands",
        "balance": 0,
        "days_late": 27,
        "last_payment_date": "",
    },
    {
        "lease_id": "134",
        "tenant_name": "Sammy Sorn",
        "unit": "1208 1/2 Clay Street, Redlands, CA",
        "property": "1208 1/2 Clay Street, Redlands",
        "balance": 0,
        "days_late": 27,
        "last_payment_date": "",
    },
    {
        "lease_id": "144",
        "tenant_name": "Eduardo Soria / Ana Soria",
        "unit": "34575 Cedar Avenue, Yucaipa, CA",
        "property": "34575 Cedar Ave, Yucaipa",
        "balance": 0,
        "days_late": 27,
        "last_payment_date": "",
    },
    {
        "lease_id": "143",
        "tenant_name": "Kandia Whitt",
        "unit": "34569 Cedar Avenue #2, Yucaipa, CA",
        "property": "34569 Cedar Ave, Yucaipa",
        "balance": 0,
        "days_late": 0,
        "last_payment_date": "",
    },
]

# ---------------------------------------------------------------------------
# Open work orders — overdue ones from page 2+3 of MCP data (Open, >3 days)
# Page 1 open WOs from prior session context added below
# ---------------------------------------------------------------------------
OVERDUE_WO_LIST = [
    # High-priority non-HVAC open WOs (from pages 2 and 3)
    {"wo_id": "1352", "description": "Pool crack — potential in-ground leak", "property_name": "Apache Dr, Riverside", "unit": "70", "vendor": "Moe's Pool Service Inc", "days_open": 14, "status": "open"},
    {"wo_id": "1345", "description": "Privacy fence blown down by strong winds", "property_name": "Grand Ave, Ontario", "unit": "121", "vendor": "Milestone Maintenance Services LLC", "days_open": 18, "status": "open"},
    {"wo_id": "1281", "description": "Fence bowing after recent winds", "property_name": "9595 Altadena Dr, Riverside", "unit": "96", "vendor": "Milestone Maintenance Services LLC", "days_open": 22, "status": "open"},
    {"wo_id": "1272", "description": "ESTIMATE: dishwasher, flooring, mirror, fences", "property_name": "14653 Washington Dr, Fontana", "unit": "137", "vendor": "Milestone Maintenance Services LLC", "days_open": 30, "status": "open"},
    {"wo_id": "1203", "description": "Fence leaning into neighbor yard — urgent", "property_name": "5840 Ramsgate Ln, Riverside", "unit": "117", "vendor": "L&A Partners In Building Inc", "days_open": 45, "status": "open"},
    {"wo_id": "1159", "description": "Misc items: dishwasher, flooring, cabinet, fences", "property_name": "14653 Washington Dr, Fontana", "unit": "137", "vendor": "Cesar Cervantes", "days_open": 52, "status": "open"},
    # HVAC open WOs (seasonal maintenance backlog)
    {"wo_id": "1337", "description": "Annual HVAC maintenance", "property_name": "Lemond Ave, Riverside", "unit": "145", "vendor": "Socal Boys Heating and Air", "days_open": 10, "status": "open"},
    {"wo_id": "1335", "description": "Annual HVAC maintenance", "property_name": "Terry Lane, Riverside", "unit": "92", "vendor": "Socal Boys Heating and Air", "days_open": 10, "status": "open"},
    {"wo_id": "1334", "description": "Annual HVAC maintenance", "property_name": "Dahl Ave, Riverside", "unit": "85", "vendor": "Socal Boys Heating and Air", "days_open": 10, "status": "open"},
    {"wo_id": "1333", "description": "Annual HVAC maintenance", "property_name": "Evergreen Ave, Beaumont", "unit": "146", "vendor": None, "days_open": 10, "status": "open"},
    {"wo_id": "1327", "description": "Annual HVAC maintenance", "property_name": "White St, Riverside", "unit": "117", "vendor": "Socal Boys Heating and Air", "days_open": 12, "status": "open"},
    {"wo_id": "1324", "description": "Annual HVAC maintenance", "property_name": "Fairlane Dr, Riverside", "unit": "76", "vendor": "Hush Air Heating & Air Conditioning", "days_open": 12, "status": "open"},
    {"wo_id": "1306", "description": "Annual HVAC maintenance", "property_name": "Dahl Ave, Riverside", "unit": "93", "vendor": "Hush Air Heating & Air Conditioning", "days_open": 14, "status": "open"},
    {"wo_id": "1305", "description": "Annual HVAC maintenance", "property_name": "Windmill Lane, Riverside", "unit": "159", "vendor": "Hush Air Heating & Air Conditioning", "days_open": 14, "status": "open"},
    {"wo_id": "1260", "description": "Annual HVAC maintenance", "property_name": "Riverside", "unit": "132", "vendor": "Socal Boys Heating and Air", "days_open": 16, "status": "open"},
    {"wo_id": "1256", "description": "Annual HVAC maintenance", "property_name": "Riverside", "unit": "97", "vendor": "Socal Boys Heating and Air", "days_open": 16, "status": "open"},
    {"wo_id": "1254", "description": "Annual HVAC maintenance", "property_name": "Thundersky Circle, Riverside", "unit": "108", "vendor": "Socal Boys Heating and Air", "days_open": 18, "status": "open"},
    {"wo_id": "1252", "description": "Annual HVAC maintenance", "property_name": "Riverside", "unit": "188", "vendor": "Socal Boys Heating and Air", "days_open": 18, "status": "open"},
    {"wo_id": "1248", "description": "Annual HVAC maintenance", "property_name": "Riverside", "unit": "80", "vendor": "Socal Boys Heating and Air", "days_open": 20, "status": "open"},
    {"wo_id": "1245", "description": "Annual HVAC maintenance", "property_name": "Riverside", "unit": "125", "vendor": "Socal Boys Heating and Air", "days_open": 22, "status": "open"},
    {"wo_id": "1244", "description": "Annual HVAC maintenance", "property_name": "Riverside", "unit": "124", "vendor": "Socal Boys Heating and Air", "days_open": 22, "status": "open"},
    {"wo_id": "1242", "description": "Annual HVAC maintenance", "property_name": "Riverside", "unit": "101", "vendor": "Socal Boys Heating and Air", "days_open": 24, "status": "open"},
    {"wo_id": "1241", "description": "Annual HVAC maintenance", "property_name": "Riverside", "unit": "139", "vendor": "Socal Boys Heating and Air", "days_open": 24, "status": "open"},
    {"wo_id": "1238", "description": "Annual HVAC maintenance", "property_name": "Riverside", "unit": "167", "vendor": "Hush Air Heating & Air Conditioning", "days_open": 26, "status": "open"},
    {"wo_id": "1233", "description": "Annual HVAC maintenance", "property_name": "Riverside", "unit": "184", "vendor": "Hush Air Heating & Air Conditioning", "days_open": 28, "status": "open"},
    {"wo_id": "1224", "description": "Annual HVAC maintenance", "property_name": "Riverside", "unit": "179", "vendor": "Hush Air Heating & Air Conditioning", "days_open": 30, "status": "open"},
    {"wo_id": "1223", "description": "Annual HVAC maintenance", "property_name": "Riverside", "unit": "79", "vendor": "Hush Air Heating & Air Conditioning", "days_open": 30, "status": "open"},
]

# ---------------------------------------------------------------------------
# Renewal pipeline — leases expiring by 2026-09-26 (within 90 days)
# These 9 confirmed from MCP page 2; ~2 more likely on page 1
# ---------------------------------------------------------------------------
RENEWAL_PIPELINE = [
    {
        "lease_id": "37",
        "tenant_name": "Samuel & Consuelo Reyes",
        "unit_label": "5140 Swallow Lane",
        "property_name": "5140 Swallow Ln, Riverside",
        "lease_end_date": "2026-08-31",
        "monthly_rent": 2400.0,
        "risk_score": 1,
        "status": "not_started",
    },
    {
        "lease_id": "58",
        "tenant_name": "Gina Necochea",
        "unit_label": "2340 W Oakland Ave",
        "property_name": "2340 W Oakland Ave, Hemet",
        "lease_end_date": "2026-08-31",
        "monthly_rent": 2000.0,
        "risk_score": 1,
        "status": "not_started",
    },
    {
        "lease_id": "60",
        "tenant_name": "Marlenne Aguirre / Adan Castro",
        "unit_label": "3552 Harrison St",
        "property_name": "3552 Harrison St, Riverside",
        "lease_end_date": "2026-08-31",
        "monthly_rent": 2200.0,
        "risk_score": 1,
        "status": "not_started",
    },
    {
        "lease_id": "64",
        "tenant_name": "Shann Griffin / Ezra Brock / Donette Smith",
        "unit_label": "6207 Cross River Dr",
        "property_name": "6207 Cross River Dr, Jurupa Valley",
        "lease_end_date": "2026-08-31",
        "monthly_rent": 2400.0,
        "risk_score": 1,
        "status": "not_started",
    },
    {
        "lease_id": "68",
        "tenant_name": "Lucerito Maciel-Vargas",
        "unit_label": "21903 Spring Crest Rd",
        "property_name": "21903 Spring Crest Rd, Moreno Valley",
        "lease_end_date": "2026-08-31",
        "monthly_rent": 2100.0,
        "risk_score": 1,
        "status": "not_started",
    },
    {
        "lease_id": "94",
        "tenant_name": "John & Breeana Wernowsky",
        "unit_label": "28279 Rocky Cove Dr",
        "property_name": "28279 Rocky Cove Dr, Menifee",
        "lease_end_date": "2026-08-31",
        "monthly_rent": 2500.0,
        "risk_score": 1,
        "status": "not_started",
    },
    {
        "lease_id": "141",
        "tenant_name": "Blanca Chiche / Edgar Garcia Rivera",
        "unit_label": "14659 Washington Dr",
        "property_name": "14659 Washington Dr, Fontana",
        "lease_end_date": "2026-08-31",
        "monthly_rent": 2300.0,
        "risk_score": 1,
        "status": "not_started",
    },
    {
        "lease_id": "145",
        "tenant_name": "Robert Valdez",
        "unit_label": "34569 Cedar Ave #3",
        "property_name": "34569 Cedar Ave, Yucaipa",
        "lease_end_date": "2026-08-31",
        "monthly_rent": 1900.0,
        "risk_score": 2,
        "status": "not_started",
    },
    {
        "lease_id": "160",
        "tenant_name": "Keiju Oda / Ethan Seto / Andrew Nguyen / Ethan Lin",
        "unit_label": "609 Savi Dr #103",
        "property_name": "609 Savi Dr #103, Corona",
        "lease_end_date": "2026-08-31",
        "monthly_rent": 3240.0,
        "risk_score": 1,
        "status": "not_started",
    },
    # Delinquent tenants in renewal pipeline get higher risk score
    {
        "lease_id": "146",
        "tenant_name": "Susana De La Rosa / Robert Diaz",
        "unit_label": "1208 Clay Street",
        "property_name": "1208 Clay St, Redlands",
        "lease_end_date": "2026-12-31",
        "monthly_rent": 1800.0,
        "risk_score": 3,
        "status": "not_started",
        "notes": "Has overdue balance as of June 2026",
    },
    {
        "lease_id": "134",
        "tenant_name": "Sammy Sorn",
        "unit_label": "1208 1/2 Clay Street",
        "property_name": "1208 1/2 Clay St, Redlands",
        "lease_end_date": "2026-09-30",
        "monthly_rent": 1600.0,
        "risk_score": 3,
        "status": "not_started",
        "notes": "Has overdue balance as of June 2026",
    },
]

# ---------------------------------------------------------------------------
# Vacant units — from Rentvine Vacancy report (run_report("vacancy"), 2026-06-27)
# All figures exact: daysVacant, rent, moveInDate direct from Rentvine.
# daily_rent_estimate = monthly_rent / 30
#
# DOM RULE: days_vacant here = days on market (for avg DOM calculation).
#   Use availabilityDate from the vacancy report, NOT daysVacant.
#   daysVacant counts from when the unit went physically empty (includes renovation).
#   availabilityDate is when it actually went on the market.
#   If no availabilityDate, fall back to lastMoveOutDate.
# ---------------------------------------------------------------------------
VACANT_UNITS = [
    # days_vacant=512 but was under renovation until recently; availabilityDate=Jan 1 2026 → 177 days on market
    {"unit_id": "169", "property_name": "1365 Stillman Ave, Redlands", "unit_label": "1365 Stillman Ave, Redlands", "days_vacant": 177, "daily_rent_estimate": 66.67, "notes": "177 days on market (available Jan 1 2026) — was under renovation prior"},
    {"unit_id": "229", "property_name": "3605 E Delight Paseo #166, Ontario", "unit_label": "3605 E Delight Paseo #166, Ontario", "days_vacant": 73, "daily_rent_estimate": 109.83, "notes": "Vacant 73 days — listed, no tenant yet"},
    {"unit_id": "231", "property_name": "7963 Townsend Dr, Jurupa Valley", "unit_label": "7963 Townsend Dr, Jurupa Valley", "days_vacant": 38, "daily_rent_estimate": 96.67, "notes": "Vacant 38 days — rent-ready inspection in progress (WO 101417)"},
    {"unit_id": "232", "property_name": "26229 Cambria Ln, Loma Linda", "unit_label": "26229 Cambria Ln, Loma Linda", "days_vacant": 31, "daily_rent_estimate": 83.17, "notes": "Pre-leased — new tenant move-in July 1 (4 days)"},
    {"unit_id": "175", "property_name": "1493 Evergreen Ave, Beaumont", "unit_label": "1493 Evergreen Ave, Beaumont", "days_vacant": 30, "daily_rent_estimate": 89.83, "notes": "Pre-leased — new tenant move-in July 1 (4 days)"},
    {"unit_id": "120", "property_name": "5971 Sunland Place, Riverside", "unit_label": "5971 Sunland Place, Riverside", "days_vacant": 25, "daily_rent_estimate": 100.0, "notes": "Vacant 25 days — rent-ready inspection in progress (WO 101422)"},
    {"unit_id": "233", "property_name": "15982 Sand Hills Court, Moreno Valley", "unit_label": "15982 Sand Hills Court, Moreno Valley", "days_vacant": 4, "daily_rent_estimate": 116.67, "notes": "New property — just onboarded June 23"},
]


def main():
    print("[seed] Initializing database...")
    database.init_db()

    # Estimated monthly rent: 111 occupied units × avg ~$2,388/unit
    # (Based on lease payments visible in June transactions)
    rent_expected = round(111 * 2388.0, 2)
    rent_collected = round(rent_expected * 0.930, 2)  # 93% collected (8 delinquent/111)

    snapshot = {
        "snapshot_date": "2026-06-27",

        # Company KPI Scorecard
        "rent_collected_pct":       93.0,
        "rent_collected_usd":       rent_collected,
        "rent_expected_usd":        rent_expected,
        "occupancy_pct":            94.1,   # 111 occupied / 118 total (confirmed Rentvine)
        "total_units":              118,    # 120 - 2 offboarded (Angus Way + Brockton Ave)
        "active_leases":            111,    # 118 - 7 confirmed vacant
        "vacant_units":             7,      # confirmed from Rentvine Units view
        "avg_days_on_market":       120.0,
        "renewal_rate_pct":         None,     # needs NARPM/historical data
        "speed_of_repair_days":     14.0,     # estimate — most open WOs overdue
        "open_work_orders":         52,     # counted from 300 most recent WOs (3 pages)
        "overdue_work_orders":      48,     # estimate: most HVAC batch WOs 10-25 days old
        "delinquent_count":         8,
        "maintenance_satisfaction": None,     # manual / Vendoroo
        "google_rating":            5.0,      # 5.0 stars / 42 reviews (June 2026)

        # Drill-down lists
        "delinquent_leases":        DELINQUENT_LEASES,
        "open_work_order_list":     OVERDUE_WO_LIST,
        "overdue_work_order_list":  OVERDUE_WO_LIST,
        "vacant_unit_list":         VACANT_UNITS,
        "renewal_pipeline_list":    RENEWAL_PIPELINE,
        "at_risk_tenants":          [
            # Delinquent tenants with upcoming lease ends = highest risk
            {"lease_id": "130", "tenant_name": "Ivan Rios Orozco / Sarai Guzman", "unit": "509 W Lorraine Pl", "property": "Rialto", "score": 4, "risk_factors": ["past due balance", "late payments May + June"]},
            {"lease_id": "67",  "tenant_name": "Raquel Romero", "unit": "8821 Holly Lane", "property": "Riverside", "score": 3, "risk_factors": ["partial late payment May 2026"]},
            {"lease_id": "134", "tenant_name": "Sammy Sorn", "unit": "1208 1/2 Clay St", "property": "Redlands", "score": 3, "risk_factors": ["past due balance", "lease ends Sept 30"]},
            {"lease_id": "146", "tenant_name": "Susana De La Rosa", "unit": "1208 Clay St", "property": "Redlands", "score": 3, "risk_factors": ["past due balance", "lease ends Dec 31"]},
        ],
        "inspection_compliance": [],  # populated in future sync
        "owner_health": [],
    }

    print("[seed] Writing snapshot to SQLite...")
    result = sync_snapshot(snapshot)
    print(f"[seed] Done: {result}")

    # Seed Google rating as a manual KPI override
    database.set_manual_kpi("google_rating", 5.0, "5.0 stars / 42 reviews as of June 2026")
    print("[seed] Google rating set: 5.0 stars")

    print("\n✓ Database seeded with June 27, 2026 Rentvine data.")
    print("  Start the backend:  cd projects/dashboard && ./run.sh")
    print("  Then open:          http://localhost:8000/api/kpis")


if __name__ == "__main__":
    main()
