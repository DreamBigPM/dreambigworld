# Dream Big PM — Company KPI Dashboard
## Technical Specification

**Version:** 1.0  
**Author:** Oracle  
**Date:** 2026-06-26  
**Status:** Ready for Q to build  
**Replaces:** pmdash.io ($35/mo subscription)  
**Audience:** Brian Bean + staff (same login, same data for now)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Data Sources and Availability](#2-data-sources-and-availability)
3. [Database Schema](#3-database-schema-sqlite)
4. [KPI Computation Logic](#4-kpi-computation-logic)
5. [API Design](#5-api-design)
6. [AI Briefing Design](#6-ai-briefing-design)
7. [Alert Logic](#7-alert-logic)
8. [File Structure](#8-file-structure)
9. [Environment Variables](#9-environment-variables)
10. [Open Questions for Brian](#10-open-questions-for-brian)

---

## 1. Project Overview

### What This Is

A company-owned, browser-based operations dashboard for Dream Big Property Management. It displays live data from Rentvine, computes derived metrics (at-risk scores, vacancy cost, owner health), stores daily snapshots for trend lines, and generates a plain-English AI briefing each morning. It runs on a server Brian controls and opens in any browser — laptop at the desk, phone in the field.

### What It Replaces

pmdash.io — currently $35/month. This dashboard must cover everything pmdash.io does (issue counts, trend charts, target vs. actual for company KPIs, Aptly leasing metrics) plus everything it cannot: financial depth, drill-down to property and unit level, AI morning briefing, turnover economics, vacancy cost clock, tenant at-risk scoring, and owner health scores.

### The Three Non-Negotiables

1. **Every number drills down.** Portfolio → Property → Unit. No dead ends.
2. **Every metric shows direction.** Current value + 90-day sparkline. Not just what it is — whether it's getting better or worse.
3. **Every problem has a next step.** An alert names the unit, the vendor, the cost, and what to do.

### Current Baseline (pmdash.io, June 26, 2026)

| Metric | Current | Target | Status |
|---|---|---|---|
| Speed of Repair | 55 of 59 WOs overdue | ≤3 days | CRITICAL |
| Days on Market | ~120 days avg | ≤21 days | CRITICAL |
| Occupancy | 94.1% | ≥96% | RED |
| Rent Collected | ~93% (7% delinquency) | ≥98% | RED |
| Past due leases | 8 | 0 | CRITICAL |
| Vacant units | 7 | 0 | CRITICAL |
| Leases expiring 90d | 11 | — | Monitor |

---

## 2. Data Sources and Availability

### 2.1 Rentvine MCP — PRIMARY SOURCE (Already Connected)

All live operational data comes from Rentvine via MCP (Model Context Protocol — a direct connection that lets the app talk to Rentvine without a password every time). No additional setup required.

**Relevant MCP tools Q must use:**

| MCP Tool | Used For |
|---|---|
| `list_properties` | Property list, property IDs, address lookup |
| `list_property_units` | All units per property; total unit count |
| `list_leases` | Active leases, lease dates, rent amounts |
| `list_lease_tenants` | Who lives in each unit |
| `list_lease_charges` | Charges due per lease (denominator for rent collected %) |
| `list_transactions` | Payments received (numerator for rent collected %) |
| `get_lease_balance_due` | Outstanding balance per lease (delinquency) |
| `list_work_orders` | All open/closed work orders |
| `get_work_order` | Detail on one work order: vendor, status, open/close dates |
| `list_work_order_statuses` | Valid status values for filtering |
| `list_inspections` | Inspection records per property |
| `get_inspection` | Detail on a single inspection |
| `list_attachments` | Files attached to a property (used to detect uploaded inspection reports) |
| `list_owners` | Owner contact info and associated portfolios |
| `list_portfolios` | Portfolio groupings (ownership entities) |
| `get_portfolio` | Portfolio detail including owner linkage |
| `list_vendors` | Vendor list for maintenance alerts |
| `list_lease_renewals` | Renewal records |
| `get_lease_renewal` | Renewal detail (status, new terms) |
| `list_tenants` | Tenant contact info |
| `get_tenant` | Individual tenant detail |
| `list_bills` | Vendor invoices / make-ready costs (used in turnover cost calc) |
| `run_report` | For any aggregated financial data not available via individual endpoints |

**Data freshness:** Pull live on every page load. Every section shows a "Last updated: X minutes ago" timestamp. Manual refresh button triggers a new pull.

---

### 2.2 Aptly — LEASING FUNNEL DATA

**Status: API exists but does NOT have dedicated leasing funnel endpoints.**

Research finding: Aptly (getaptly.com) has a REST API authenticated via an `x-token` query parameter (company-wide token, enabled per board in Settings). The API exposes boards, cards, contacts, and tasks — but there are no dedicated endpoints for leads, showings, or showing completion rates. The API is a general-purpose card/board system; leasing funnel metrics (leads, showings) would require reading cards from a leasing board and parsing field values — which requires Brian to confirm how his Aptly boards are structured.

**Plan for launch:**

- Days on market and occupancy rate come from **Rentvine** (available at launch).
- Lead-to-showing conversion rate and showing completion rate come from **Aptly board cards** — these require a one-time mapping session with Brian to identify which board and which fields hold this data.
- ⚠️ OPEN: See Section 10, Question 1.

**Aptly API reference:**
- Base URL: `https://docs.getaptly.com` (API token passed as `?x-token=YOUR_TOKEN`)
- Board cards endpoint: `GET /api/board/{boardId}` — returns paginated cards (200/page)
- Board schema: `GET /api/schema/{boardId}` — returns field definitions for a board

---

### 2.3 Vendoroo — MAINTENANCE COORDINATION

**Status: No public API. No webhooks. No developer documentation found.**

Vendoroo syncs bidirectionally with Rentvine. All maintenance data (work orders, vendor assignments, status updates, completion dates) is accessible via the Rentvine MCP tools listed above.

**Vendor performance scorecard:** Omitted from this dashboard — Vendoroo handles this natively in its own interface.

**Maintenance satisfaction score (target ≥70):** Vendoroo collects tenant satisfaction ratings after maintenance is completed, but there is no API to retrieve this score programmatically.

- At launch: this KPI is a **manual entry field**. Brian enters the current satisfaction score (available inside Vendoroo) once a week — one number, one click.
- Phase 2: Contact Vendoroo support to ask about API or webhook access for satisfaction scores.

---

### 2.4 Google Business Profile — GOOGLE RATING KPI

**Current baseline:** 5.0 stars / 42 reviews (June 2026). Target: ≥4.8 stars. Currently well above target.

**API status:** Google Business Profile API is available but requires an OAuth 2.0 setup and a review/approval process from Google (typically 3–10 business days). As of 2026, Google split the GBP API into 5 separate sub-APIs.

**OAuth scope required:** `https://www.googleapis.com/auth/business.manage`

**API base URL:** `mybusinessaccountmanagement.googleapis.com/v1`

**To read review count and average rating:**
1. `GET https://mybusiness.googleapis.com/v4/accounts/{accountId}/locations` — list locations
2. `GET https://mybusiness.googleapis.com/v4/accounts/{accountId}/locations/{locationId}/reviews` — get review list and average rating

**Plan for launch:** Google rating is a **manual entry field** at launch. Brian updates it once per week — one field, one number, takes 10 seconds. The manual entry goes into the `manual_kpi_overrides` table. Google Business Profile API integration is Phase 2.

---

### 2.5 Rentcast — RENT VS. MARKET COMPARISON

**Status: Phase 2 feature only. Document here for when Q builds it.**

**Free plan limits:** 50 API requests per month. Brian is currently on free plan. Paid plan ($199/mo) required for portfolio-wide comparisons.

**Constraint (hard rule, never override):** Rentcast must only be called one property at a time, triggered manually by Brian clicking "Look up market rent for this unit." Automatic bulk fetching across the 120-unit portfolio is forbidden on the free plan — it would exhaust the monthly quota in one run.

**Endpoint for Phase 2:**
```
GET https://api.rentcast.io/v1/avm/rent/long-term
  ?address=123 Main St, Riverside, CA 92501
  &propertyType=Single Family
  &bedrooms=3
  &bathrooms=2
```
Authentication: `X-Api-Key: YOUR_RENTCAST_KEY` header.

Response includes: `rent` (estimated monthly rent), `rentRangeLow`, `rentRangeHigh`, and a list of comparable properties.

---

### 2.6 Zinspector — INSPECTION DATA

**Status: API exists but is not publicly documented.**

Zinspector's integrations page states: "Generate developer keys and access our RESTful endpoints." However, no public documentation or endpoint reference is available. Zinspector does have a confirmed two-way sync with Rentvine.

**Two-path strategy for inspection compliance:**

**Path A — Rentvine inspections (preferred at launch):**
Use `list_inspections` and `get_inspection` via Rentvine MCP. This returns inspection records logged directly in Rentvine. Q should filter by property, find the most recent completed inspection, and compute days since last inspection.

**Path B — Rentvine file attachments (fallback):**
If inspection records aren't in Rentvine's inspection module, use `list_attachments` filtered by property. Look for files with names containing "inspection" or with inspection-related mime types. Extract the upload date as a proxy for last inspection date.

⚠️ OPEN: See Section 10, Question 2.

---

## 3. Database Schema (SQLite)

SQLite database file: `db/dashboard.db` (gitignored — never committed).

All tables use `INTEGER PRIMARY KEY AUTOINCREMENT` for IDs unless noted. Dates stored as `TEXT` in ISO 8601 format (`YYYY-MM-DD`). Timestamps stored as `TEXT` in ISO 8601 datetime format (`YYYY-MM-DDTHH:MM:SS`).

---

### Table: `kpi_snapshots`

Daily snapshot of the 7 company KPIs. One row per day. Powers the 90-day trend sparklines.

```sql
CREATE TABLE kpi_snapshots (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date            TEXT NOT NULL UNIQUE,  -- 'YYYY-MM-DD'
    rent_collected_pct       REAL,    -- e.g. 97.3
    occupancy_pct            REAL,    -- e.g. 94.1
    avg_days_on_market       REAL,    -- e.g. 21.5
    renewal_rate_pct         REAL,    -- e.g. 88.0
    speed_of_repair_days     REAL,    -- e.g. 4.2
    maintenance_satisfaction REAL,    -- e.g. 72.0 (manual entry)
    google_rating            REAL,    -- e.g. 5.0 (manual entry)
    created_at               TEXT NOT NULL DEFAULT (datetime('now'))
);
```

---

### Table: `metric_history`

Daily snapshot of every dashboard metric — not just the 7 KPIs. Enables per-property trend lines and portfolio-wide history for any metric.

```sql
CREATE TABLE metric_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    record_date TEXT NOT NULL,       -- 'YYYY-MM-DD'
    metric_name TEXT NOT NULL,       -- e.g. 'occupancy_pct', 'open_work_orders', 'vacancy_cost_usd'
    value       REAL NOT NULL,
    property_id TEXT,                -- NULL = portfolio level; Rentvine property ID if property-specific
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(record_date, metric_name, property_id)
);
```

**Example metric_name values:**
- `occupancy_pct` (portfolio and per-property)
- `open_work_orders` (portfolio and per-property)
- `overdue_work_orders`
- `past_due_leases`
- `vacant_units`
- `vacancy_cost_usd`
- `avg_speed_of_repair_days`
- `delinquency_pct`
- `turnover_cost_avg_usd`

---

### Table: `alert_log`

Every alert that fires. Cleared once Brian resolves it.

```sql
CREATE TABLE alert_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type  TEXT NOT NULL,       -- e.g. 'VACANT_TOO_LONG', 'WORK_ORDER_OVERDUE'
    message     TEXT NOT NULL,       -- human-readable alert text
    property_id TEXT,                -- Rentvine property ID (NULL if portfolio-level)
    unit_id     TEXT,                -- Rentvine unit ID (NULL if not unit-specific)
    lease_id    TEXT,                -- Rentvine lease ID (NULL if not lease-specific)
    work_order_id TEXT,              -- Rentvine work order ID (NULL if not WO-specific)
    severity    TEXT NOT NULL DEFAULT 'WARN',  -- 'WARN' or 'CRITICAL'
    fired_at    TEXT NOT NULL DEFAULT (datetime('now')),
    cleared_at  TEXT,                -- NULL = still active
    cleared_by  TEXT                 -- 'brian' or system auto-clear
);
```

---

### Table: `threshold_config`

Configurable thresholds for every metric that triggers an alert. Brian can adjust these in the UI.

```sql
CREATE TABLE threshold_config (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name    TEXT NOT NULL UNIQUE,
    warning_value  REAL NOT NULL,
    critical_value REAL NOT NULL,
    direction      TEXT NOT NULL,  -- 'below' (bad if value drops below) or 'above' (bad if value rises above)
    unit           TEXT,           -- 'pct', 'days', 'usd', 'count', 'stars' — for display only
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**Default threshold values to seed on first run:**

```sql
INSERT INTO threshold_config (metric_name, warning_value, critical_value, direction, unit) VALUES
('rent_collected_pct',       93.0, 90.0, 'below', 'pct'),
('occupancy_pct',            91.0, 90.0, 'below', 'pct'),
('avg_days_on_market',       30.0, 45.0, 'above', 'days'),
('renewal_rate_pct',         80.0, 75.0, 'below', 'pct'),
('speed_of_repair_days',      7.0, 14.0, 'above', 'days'),
('maintenance_satisfaction', 60.0, 55.0, 'below', 'count'),
('google_rating',             4.5,  4.0, 'below', 'stars'),
('vacancy_days',             21.0, 30.0, 'above', 'days'),
('work_order_age_days',      14.0, 21.0, 'above', 'days'),
('delinquency_pct',           5.0, 10.0, 'above', 'pct');
```

---

### Table: `renewal_pipeline`

Tracks the renewal conversation status for every lease expiring in the next 90 days.

```sql
CREATE TABLE renewal_pipeline (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lease_id        TEXT NOT NULL UNIQUE,   -- Rentvine lease ID
    tenant_name     TEXT NOT NULL,
    unit_label      TEXT NOT NULL,          -- e.g. "14B"
    property_name   TEXT NOT NULL,
    lease_end_date  TEXT NOT NULL,          -- 'YYYY-MM-DD'
    monthly_rent    REAL NOT NULL,
    risk_score      INTEGER NOT NULL DEFAULT 1,  -- 1 (low) to 5 (high)
    status          TEXT NOT NULL DEFAULT 'not_started',
    -- status values: 'not_started', 'contacted', 'in_negotiation', 'signed', 'lost'
    notes           TEXT,
    last_updated    TEXT NOT NULL DEFAULT (datetime('now')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

---

### Table: `manual_kpi_overrides`

Stores KPI values that cannot be fetched automatically. Currently: Google rating and maintenance satisfaction score.

```sql
CREATE TABLE manual_kpi_overrides (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name TEXT NOT NULL,   -- 'google_rating', 'maintenance_satisfaction'
    value       REAL NOT NULL,
    notes       TEXT,            -- e.g. "42 reviews as of June 2026"
    entered_by  TEXT NOT NULL DEFAULT 'brian',
    entered_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

To read the current value of a manual KPI, query the most recent row for that `metric_name`.

---

## 4. KPI Computation Logic

All formulas are implemented in `backend/kpi.py`. Inputs come from Rentvine MCP calls assembled in `backend/rentvine.py`. All monetary values in USD.

---

### 4.1 Rent Collected %

**Definition:** What percentage of rent that was due this month has actually been collected.

```
rent_collected_pct = (sum of all payments received this month) 
                   / (sum of all charges due this month) 
                   × 100
```

**Implementation:**
- Numerator: `list_transactions` filtered to current calendar month, transaction type = payment/receipt
- Denominator: `list_lease_charges` for all active leases, filtered to charges due in current month
- Only include active leases (status = active)
- Exclude security deposits and one-time fees from denominator — recurring rent charges only

**Targets:** Green ≥98%, Yellow 93–97.9%, Red <93%

---

### 4.2 Occupancy Rate

**Definition:** Percentage of total units that have an active lease right now.

```
occupancy_pct = (count of units with an active lease) 
              / (total unit count across all properties) 
              × 100
```

**Implementation:**
- Active lease count: `list_leases` where status = active, count distinct `unit_id`
- Total units: `list_property_units` across all properties, count all units
- Do not exclude units marked as "offline" or "not available" unless Brian confirms those exist in his Rentvine data

**Targets:** Green ≥96%, Yellow 91–95.9%, Red <91%

---

### 4.3 Average Days on Market

**Definition:** For units leased during the current period, how many days did they sit vacant between becoming available and getting a signed lease?

```
avg_days_on_market = average(lease_start_date - vacancy_available_date) 
                     for all units leased in the last 30 days
```

**Implementation:**
- From `list_leases`: find leases where `lease_start_date` falls within the last 30 days
- The vacancy start date is the prior lease's `lease_end_date` + 1 day (or the unit's `available_date` if set in Rentvine)
- **RESOLVED:** Use prior lease `end_date` + 1 day as the vacancy start date. Brian confirmed this is the correct clock start. Move-out day = day the lease ends. DOM clock starts the following day.
- For currently vacant units: compute days since the prior lease ended and display individually on the Occupancy section

**Targets:** Green ≤21 days, Yellow 22–30 days, Red >30 days

---

### 4.4 Lease Renewal Rate

**Definition:** Of all leases that came up for renewal in the last 90 days, what percentage were renewed?

```
renewal_rate_pct = (count of leases renewed) 
                 / (count of leases renewed + count of leases that expired without renewal) 
                 × 100
```

**Implementation:**
- `list_lease_renewals` for leases with end dates in the last 90 days
- A lease counts as "renewed" if a renewal record exists with status = signed/executed
- A lease counts as "not renewed" if the lease ended and no renewal record exists (tenant moved out)
- Exclude leases that are still within the active window (haven't expired yet)

**Targets:** Green ≥90%, Yellow 80–89.9%, Red <80%

---

### 4.5 Speed of Repair

**Definition:** Average number of days from when a work order was opened to when it was closed, for work orders closed this month.

```
speed_of_repair_days = average(close_date - open_date) 
                       for work orders where close_date is in the current calendar month
```

**Implementation:**
- `list_work_orders` filtered to `status = closed` and `closed_date` in current month
- Compute days for each: `(closed_date - created_date)` in calendar days
- For the "overdue" count: `list_work_orders` where status = open AND `(today - created_date) > 3 days`
- Report both: average days to close (KPI) and count currently overdue (daily zero goal)

**Targets:** Green ≤3 days, Yellow 4–7 days, Red >7 days

---

### 4.6 Tenant At-Risk Score

**Definition:** A score from 0 to 100 estimating how likely a tenant is to go 30+ days late in the next 30 days. Score above 60 = flagged.

```
at_risk_score = (days_since_last_payment_factor × 0.40)
              + (payment_amount_factor × 0.30)
              + (consecutive_late_months_factor × 0.30)
```

**Factor calculations (each returns 0–100):**

```
days_since_last_payment_factor:
  - 0 days late:           0
  - 1–5 days late:        20
  - 6–10 days late:       50
  - 11–20 days late:      75
  - 21+ days late:       100

payment_amount_factor:
  - Paid in full:          0
  - Paid 95–99%:          15
  - Paid 80–94%:          40
  - Paid 50–79%:          70
  - Paid <50%:           100

consecutive_late_months_factor:
  - 0 late months:         0
  - 1 late month:         20
  - 2 late months:        50
  - 3+ late months:      100
```

**Data source:** `list_transactions` for the last 3 months per tenant, compared to `list_lease_charges` for expected amounts.

**Flag threshold:** Score ≥60 → appear in at-risk panel. Score ≥80 → CRITICAL badge.

---

### 4.7 True Turnover Cost

**Definition:** The full economic cost of a unit turning over — vacancy loss plus make-ready plus leasing costs.

```
true_turnover_cost = vacancy_loss + make_ready_cost + leasing_cost

vacancy_loss    = days_vacant × (monthly_rent / 30)
make_ready_cost = sum of all bills tagged to this unit during the vacancy period
leasing_cost    = (days_to_lease / 30) × estimated_staff_time_cost
                  -- staff time cost default: $500/month until Brian sets actual number
```

**Implementation:**
- For each unit that turned in the last 12 months: find prior lease end date, new lease start date
- `days_vacant` = new_lease_start - prior_lease_end
- `make_ready_cost` = sum of `list_bills` where property/unit matches and date falls in vacancy window
- `leasing_cost` is a flat estimate unless Brian provides actual data
- Report: average per unit, worst offender, breakdown by property

---

### 4.8 Owner Health Score

**Definition:** A score from 0 to 100 measuring the health of Brian's relationship with each property owner. Used to identify owners who need attention before they call to complain.

```
owner_health_score = 100 - deductions

Deductions:
  -30  if monthly owner report was not delivered last month
  -30  if owner distribution was not sent within 5 business days of month close
  -40  if any open work order on their property is > 30 days old
```

**Note:** Last-contact-date deduction removed. Brian confirmed owner contact tracking is a recurring task/reminder system, not a logged history. This is a Phase 2 "Owner Outreach" workflow that connects to this dashboard.

**Data source for deductions:**
- Reports: `list_attachments` for owner report files per portfolio — check for a report file in the prior calendar month
- Distributions: `list_transactions` filtered to owner distribution type, check date vs. month-close date
- Work orders: `list_work_orders` where property belongs to owner's portfolio and status = open and age > 30 days

**Score bands:** Green 80–100, Yellow 50–79, Red <50

---

### 4.9 Vacancy Cost Clock

**Definition:** Live running total of revenue being lost right now due to vacant units.

```
vacancy_cost_per_unit = days_vacant × (last_rent / 30)
                        -- "last_rent" = the rent charged on the most recent lease for this unit
                        -- if no prior lease, use market rate from Rentvine unit record
```

**Display:** Each vacant unit shows its own running clock. Portfolio total shown in the header of Section 2.

**Data source:** `list_property_units` to find vacant units (no active lease), `list_leases` (last lease) for rent amount, `today - prior_lease_end_date` for days vacant.

---

## 5. API Design

The Python backend (FastAPI) serves a JSON API on `localhost:8000` (or the server's port). The frontend fetches from this API. All endpoints return JSON.

All responses include a top-level `last_updated` field (ISO 8601 timestamp of when the Rentvine data was last pulled).

**Standard response envelope:**
```json
{
  "last_updated": "2026-06-26T06:00:00",
  "data": { ... }
}
```

**Standard error response:**
```json
{
  "error": "description of what went wrong",
  "code": 500
}
```

---

### `GET /api/summary`

Returns all 7 company KPIs with current values, targets, status (green/yellow/red), trend direction, and 90-day sparkline data.

**Response structure:**
```json
{
  "last_updated": "...",
  "data": {
    "rent_collected_pct":       { "value": 93.0, "target": 98.0, "status": "red",    "trend": "down", "sparkline": [98.1, 97.3, ...] },
    "occupancy_pct":            { "value": 94.1, "target": 96.0, "status": "yellow", "trend": "stable", "sparkline": [...] },
    "avg_days_on_market":       { "value": 120,  "target": 21,   "status": "red",    "trend": "up",   "sparkline": [...] },
    "renewal_rate_pct":         { "value": 88.0, "target": 90.0, "status": "yellow", "trend": "up",   "sparkline": [...] },
    "speed_of_repair_days":     { "value": 14.2, "target": 3.0,  "status": "red",    "trend": "down", "sparkline": [...] },
    "maintenance_satisfaction": { "value": 72.0, "target": 70.0, "status": "green",  "trend": "stable", "sparkline": [...], "source": "manual" },
    "google_rating":            { "value": 5.0,  "target": 4.8,  "status": "green",  "trend": "stable", "sparkline": [...], "source": "manual", "review_count": 42 }
  }
}
```

`sparkline` is an array of the last 90 daily values (oldest first). Missing days are `null`.

---

### `GET /api/briefing`

Returns today's AI-generated briefing text. If no briefing has been generated today, generates one on demand (may take 2–3 seconds).

**Response:**
```json
{
  "last_updated": "2026-06-26T06:00:00",
  "data": {
    "text": "Good morning, Brian. Two new work orders opened overnight...",
    "generated_at": "2026-06-26T06:00:12"
  }
}
```

---

### `GET /api/financials`

Financial command center data at portfolio level.

**Response:**
```json
{
  "last_updated": "...",
  "data": {
    "rent_collected_mtd_usd":    48200.00,
    "rent_expected_mtd_usd":     51800.00,
    "rent_collected_pct":        93.0,
    "outstanding_balance_usd":   3600.00,
    "estimated_net_income_usd":  41000.00,
    "month_over_month_change_pct": -2.1,
    "revenue_12mo": [
      { "month": "2025-07", "collected_usd": 50100.00 },
      ...
    ],
    "cash_flow_projection_30d": {
      "expected_in_usd":  52000.00,
      "known_expenses_usd": 8400.00,
      "projected_net_usd": 43600.00
    }
  }
}
```

---

### `GET /api/occupancy`

Occupancy rate, vacancy cost, expiring leases, and renewal pipeline.

**Response:**
```json
{
  "last_updated": "...",
  "data": {
    "occupancy_pct": 94.1,
    "total_units": 120,
    "occupied_units": 113,
    "vacant_units": 7,
    "total_vacancy_cost_daily_usd": 412.00,
    "vacant_unit_list": [
      {
        "unit_id": "...",
        "unit_label": "14B",
        "property_name": "Riverside Arms",
        "property_id": "...",
        "days_vacant": 47,
        "daily_cost_usd": 58.00,
        "total_loss_usd": 2726.00
      }
    ],
    "lease_expiration_buckets": {
      "0_30_days":   3,
      "31_60_days":  4,
      "61_90_days":  4,
      "91_180_days": 12
    },
    "renewal_pipeline": [
      {
        "lease_id": "...",
        "tenant_name": "Jane Smith",
        "unit_label": "14B",
        "property_name": "Riverside Arms",
        "lease_end_date": "2026-08-01",
        "monthly_rent": 1750.00,
        "risk_score": 4,
        "status": "not_started",
        "estimated_turnover_cost_usd": 4800.00,
        "last_updated": "..."
      }
    ]
  }
}
```

---

### `GET /api/delinquency`

Past-due tenants and at-risk tenant scores.

**Response:**
```json
{
  "last_updated": "...",
  "data": {
    "past_due_count": 8,
    "total_past_due_usd": 14200.00,
    "past_due_tenants": [
      {
        "lease_id": "...",
        "tenant_name": "John Doe",
        "unit_label": "22A",
        "property_name": "Corona Pines",
        "balance_usd": 1850.00,
        "days_late": 12
      }
    ],
    "at_risk_tenants": [
      {
        "lease_id": "...",
        "tenant_name": "Maria Garcia",
        "unit_label": "5C",
        "property_name": "Moreno Valley Commons",
        "at_risk_score": 72,
        "risk_flags": ["2 late months", "partial payment last month"]
      }
    ]
  }
}
```

---

### `GET /api/maintenance`

Work order summary, overdue counts, turn times, and property-level cost trends.

**Response:**
```json
{
  "last_updated": "...",
  "data": {
    "open_count": 59,
    "overdue_count": 55,
    "avg_age_days": 18.4,
    "avg_speed_of_repair_days": 14.2,
    "overdue_work_orders": [
      {
        "work_order_id": "...",
        "unit_label": "14B",
        "property_name": "Riverside Arms",
        "description": "HVAC not cooling",
        "vendor_name": "Torres HVAC",
        "vendor_phone": "951-555-0100",
        "days_open": 22,
        "status": "In Progress"
      }
    ],
    "properties_with_climbing_costs": [
      {
        "property_id": "...",
        "property_name": "Corona Pines",
        "spend_this_year_usd": 12400.00,
        "spend_last_year_usd": 4100.00,
        "change_pct": 202.4
      }
    ]
  }
}
```

---

### `GET /api/zero-goals`

The four daily-zero-goal counts.

**Response:**
```json
{
  "last_updated": "...",
  "data": {
    "past_due_leases":    { "count": 8,  "severity": "CRITICAL" },
    "open_work_orders":   { "count": 59, "severity": "CRITICAL" },
    "overdue_work_orders":{ "count": 55, "severity": "CRITICAL" },
    "vacant_units":       { "count": 7,  "severity": "CRITICAL", "total_daily_cost_usd": 412.00 }
  }
}
```

---

### `GET /api/blue-ocean`

At-risk tenants summary, true turnover cost analysis, and owner health scores.

**Response:**
```json
{
  "last_updated": "...",
  "data": {
    "top_at_risk_tenants": [ ... ],  // top 5 by at_risk_score, same structure as /api/delinquency
    "turnover_analysis": {
      "units_turned_12mo": 14,
      "avg_true_cost_usd": 5200.00,
      "worst_unit": { "unit_label": "8D", "property_name": "...", "cost_usd": 9400.00 },
      "by_property": [
        { "property_name": "Riverside Arms", "avg_cost_usd": 4800.00, "units_turned": 4 }
      ]
    },
    "owner_health_scores": [
      {
        "owner_name": "John Property LLC",
        "portfolio_name": "...",
        "score": 50,
        "status": "yellow",
        "deductions": ["No contact in 62 days", "WO open > 30 days on Riverside Arms"]
      }
    ]
  }
}
```

---

### `GET /api/property/{id}`

All metrics for one property. `{id}` is the Rentvine property ID.

**Response:**
```json
{
  "last_updated": "...",
  "data": {
    "property_id": "...",
    "property_name": "Riverside Arms",
    "property_address": "1234 Main St, Riverside, CA 92501",
    "owner_name": "John Property LLC",
    "last_owner_contact_date": "2026-05-15",
    "revenue_this_month_usd": 8400.00,
    "revenue_last_month_usd": 8750.00,
    "occupancy_pct": 90.0,
    "total_units": 10,
    "occupied_units": 9,
    "vacant_units": [{ "unit_label": "14B", "days_vacant": 47, "daily_cost_usd": 58.00 }],
    "expiring_leases": [{ "unit_label": "8A", "tenant_name": "...", "lease_end_date": "..." }],
    "open_work_orders": 12,
    "overdue_work_orders": 10,
    "maintenance_cost_12mo": [
      { "month": "2025-07", "cost_usd": 820.00 }, ...
    ],
    "at_risk_tenants": [ ... ],
    "last_inspection_date": "2025-11-15",
    "days_since_inspection": 223,
    "inspection_status": "due_soon"
  }
}
```

---

### `GET /api/inspections`

Inspection compliance for every property.

**Response:**
```json
{
  "last_updated": "...",
  "data": {
    "properties": [
      {
        "property_id": "...",
        "property_name": "Riverside Arms",
        "last_inspection_date": "2025-11-15",
        "days_since_inspection": 223,
        "status": "due_soon",   // 'current' (<305d), 'due_soon' (305-365d), 'overdue' (>365d)
        "rentvine_file_url": "..."  // link to the inspection file in Rentvine, if available
      }
    ]
  }
}
```

**Status thresholds:**
- `current`: fewer than 305 days since last inspection (more than 60 days until annual due)
- `due_soon`: 305–365 days (within 60 days of annual due date) → yellow flag
- `overdue`: more than 365 days → red flag

---

### `GET /api/alerts`

All active (uncleared) alerts, sorted by severity then fired_at descending.

**Response:**
```json
{
  "last_updated": "...",
  "data": {
    "alerts": [
      {
        "id": 42,
        "alert_type": "WORK_ORDER_OVERDUE",
        "message": "Unit 14B at Riverside Arms — HVAC overdue 22 days — vendor: Torres HVAC — tap to call 951-555-0100",
        "severity": "CRITICAL",
        "property_id": "...",
        "unit_id": "...",
        "work_order_id": "...",
        "fired_at": "2026-06-25T06:00:00"
      }
    ],
    "total_active": 47
  }
}
```

---

### `POST /api/alerts/{id}/clear`

Mark an alert as resolved.

**Request body:**
```json
{ "cleared_by": "brian" }
```

**Response:**
```json
{ "success": true, "alert_id": 42, "cleared_at": "2026-06-26T09:14:00" }
```

---

### `POST /api/renewal/{lease_id}/status`

Update the status of a lease in the renewal pipeline.

**Request body:**
```json
{
  "status": "in_negotiation",
  "notes": "Offered $50/mo increase, tenant wants to think about it"
}
```

Valid status values: `not_started`, `contacted`, `in_negotiation`, `signed`, `lost`

**Response:**
```json
{ "success": true, "lease_id": "...", "new_status": "in_negotiation" }
```

---

### `POST /api/manual-kpi`

Update a manually-entered KPI value. Used for Google rating and maintenance satisfaction score.

**Request body:**
```json
{
  "metric_name": "google_rating",
  "value": 5.0,
  "notes": "42 reviews as of June 26 2026"
}
```

Valid `metric_name` values: `google_rating`, `maintenance_satisfaction`

**Response:**
```json
{ "success": true, "metric_name": "google_rating", "value": 5.0, "entered_at": "..." }
```

---

### `GET /api/refresh`

Triggers a fresh pull from Rentvine MCP and returns updated summary data. This is what the "Refresh" button on the dashboard calls. May take 3–8 seconds depending on data volume.

**Response:**
```json
{
  "success": true,
  "refreshed_at": "2026-06-26T10:32:00",
  "data": { ... }  // same structure as /api/summary
}
```

---

## 6. AI Briefing Design

### Purpose

A plain-English paragraph written fresh each morning that tells Brian only what changed since yesterday — not what is always true. If 55 work orders are overdue every day, the briefing does not say "55 work orders are overdue." It says what's new, what worsened, and what improved.

### Schedule

Runs every day at 6:00am via the scheduler in `backend/scheduler.py`. The result is stored so the frontend can display it instantly without waiting for a generation call.

### Model

`claude-haiku-4-5-20251001` — fast, inexpensive, appropriate for a short daily summary.

### Max Tokens

200 output tokens. The briefing must be 2–4 sentences. If the model would go longer, the token limit cuts it off cleanly.

### Prompt Template

```
You write a morning briefing for Brian Bean, a property manager who manages 
120 rental units in the Inland Empire, California.

Here are yesterday's company KPIs:
- Rent collected: {yesterday.rent_collected_pct}%
- Occupancy: {yesterday.occupancy_pct}%
- Avg days on market: {yesterday.avg_days_on_market} days
- Renewal rate: {yesterday.renewal_rate_pct}%
- Speed of repair: {yesterday.speed_of_repair_days} days avg
- Maintenance satisfaction: {yesterday.maintenance_satisfaction}
- Google rating: {yesterday.google_rating} stars

Here are today's company KPIs:
- Rent collected: {today.rent_collected_pct}%
- Occupancy: {today.occupancy_pct}%
- Avg days on market: {today.avg_days_on_market} days
- Renewal rate: {today.renewal_rate_pct}%
- Speed of repair: {today.speed_of_repair_days} days avg
- Maintenance satisfaction: {today.maintenance_satisfaction}
- Google rating: {today.google_rating} stars

New alerts fired since yesterday:
{new_alerts_list}  -- one line each, or "None" if no new alerts

Alerts cleared since yesterday:
{cleared_alerts_list}  -- one line each, or "None" if no alerts were cleared

Write a 2-4 sentence morning briefing in plain English. 
- Start with "Good morning, Brian."
- Only mention things that CHANGED or are NEWLY urgent — not things that have been the same for days.
- If nothing changed, say so briefly and note one positive thing.
- Do not use bullet points, headers, or bold text — just sentences.
- Do not use jargon.
- Maximum 3 sentences.
```

### Input Construction

Built in `backend/briefing.py` by comparing:
1. Today's `kpi_snapshots` row (just written by the 6am scheduler)
2. Yesterday's `kpi_snapshots` row
3. `alert_log` rows where `fired_at` > yesterday's 6am run (new alerts)
4. `alert_log` rows where `cleared_at` > yesterday's 6am run (cleared alerts)

If today's snapshot does not yet exist (first run, or scheduler failed), generate it first, then run the briefing.

---

## 7. Alert Logic

All alerts are computed in `backend/alerts.py`. The alert checker runs:
- On every `/api/refresh` call
- At 6:00am daily (before the briefing runs)

Before firing a new alert, check if a matching active alert already exists in `alert_log` (same `alert_type` + same `unit_id` or `work_order_id`). Do not create duplicate active alerts.

Auto-clear: when the underlying condition is resolved (e.g., a work order closes), set `cleared_at = now()` and `cleared_by = 'system'`.

---

### Alert Definitions

#### `VACANT_TOO_LONG`
- **Trigger:** A unit has been vacant for more than 21 days
- **Severity:** CRITICAL
- **Message:** `"Unit {unit_label} at {property_name} has been vacant {days} days — costing ${daily_cost}/day (${total_loss} total loss so far)"`
- **Auto-clear:** When a new active lease is created for this unit in Rentvine

#### `LEASE_EXPIRING_NO_ACTION`
- **Trigger:** A lease expires in fewer than 30 days AND its `renewal_pipeline.status = 'not_started'`
- **Severity:** CRITICAL
- **Message:** `"Lease for {tenant_name} at {unit_label} ({property_name}) expires in {days} days — no renewal conversation started. Estimated turnover cost: ${estimated_cost}."`
- **Auto-clear:** When renewal pipeline status changes away from `not_started`

#### `WORK_ORDER_OVERDUE`
- **Trigger:** A work order has been open for more than 14 days
- **Severity:** CRITICAL
- **Message:** `"Unit {unit_label} at {property_name} — {work_order_description} — overdue {days_open} days — vendor: {vendor_name} — {vendor_phone}"`
- **Auto-clear:** When the work order status changes to closed in Rentvine

#### `RENT_BELOW_TARGET`
- **Trigger:** It is the 10th of the month or later AND rent collected % is below 95%
- **Severity:** WARN (becomes CRITICAL if below 90%)
- **Message (WARN):** `"Rent collection at {pct}% — ${amount_outstanding} still outstanding as of the 10th. {count} tenants past due."`
- **Message (CRITICAL):** `"CRITICAL: Rent collection at only {pct}% — ${amount_outstanding} uncollected. Immediate follow-up needed."`
- **Auto-clear:** When rent collected % rises above 98%

#### `KPI_MISSED`
- **Trigger:** Any of the 7 company KPIs crosses from yellow to red (i.e., crosses the `critical_value` threshold)
- **Severity:** CRITICAL
- **Message:** `"Company KPI alert: {kpi_display_name} is now {value} — below the critical threshold of {critical_value}. Target is {target}."`
- **Auto-clear:** When the KPI returns to yellow or green

#### `OWNER_NEGLECTED`
- **Trigger:** An owner's health score drops below 50 (red)
- **Severity:** WARN
- **Message:** `"{owner_name}'s owner health score is {score}/100. Issues: {deduction_reasons_list}"`
- **Auto-clear:** When the owner's health score rises above 50

#### `INSPECTION_OVERDUE`
- **Trigger:** More than 365 days since last inspection at a property
- **Severity:** CRITICAL
- **Message:** `"{property_name} — last inspection was {days} days ago ({last_date}). California compliance at risk."`
- **Auto-clear:** When a new inspection record is logged in Rentvine for this property

#### `HIGH_TENANT_RISK`
- **Trigger:** A tenant's at-risk score rises above 80
- **Severity:** WARN
- **Message:** `"{tenant_name} at {unit_label} ({property_name}) — at-risk score {score}/100. Flags: {risk_flags}"`
- **Auto-clear:** When the tenant's at-risk score drops below 60

---

## 8. File Structure

```
/Users/brianbean/CODE/dreambigworld/projects/dashboard/
├── SPEC.md                    ← this file
├── requirements.txt           ← Python dependencies
├── .env.example               ← template for required environment variables
│
├── backend/
│   ├── main.py                ← FastAPI app; defines all /api/* routes
│   ├── rentvine.py            ← Rentvine MCP data fetcher; all MCP calls live here
│   ├── kpi.py                 ← KPI computation functions (formulas from Section 4)
│   ├── alerts.py              ← Alert evaluation logic (definitions from Section 7)
│   ├── briefing.py            ← AI briefing generator; calls Claude API
│   ├── database.py            ← SQLite read/write operations; all SQL lives here
│   └── scheduler.py           ← Daily 6am snapshot job; calls kpi.py then briefing.py
│
├── frontend/
│   ├── index.html             ← Main dashboard (all sections, laptop-optimized)
│   ├── mobile.html            ← Mobile quick-view: 3 cards (zero goals, KPIs, top alert)
│   ├── property.html          ← Property scorecard (opened from any property name click)
│   ├── css/
│   │   └── dashboard.css      ← All styles; responsive breakpoints for 375px mobile
│   └── js/
│       ├── dashboard.js       ← Page logic: fetch API data, render sections, handle buttons
│       └── charts.js          ← Sparkline and chart rendering (vanilla JS, no framework)
│
└── db/
    └── dashboard.db           ← SQLite database (add to .gitignore — never commit)
```

**`.gitignore` additions needed:**
```
projects/dashboard/db/
projects/dashboard/.env
```

---

## 9. Environment Variables

Stored in `projects/dashboard/.env`. The `.env.example` file contains all keys with empty values and comments.

```bash
# Required at launch
ANTHROPIC_API_KEY=                  # Claude API key for AI briefing (claude-haiku-4-5)

# Email alerts — Microsoft 365 SMTP
ALERT_EMAIL_TO=brian@dreambigpm.com
ALERT_EMAIL_FROM=                   # The "from" address (likely same Microsoft 365 mailbox)
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USER=                          # Microsoft 365 login email
SMTP_PASSWORD=                      # Microsoft 365 app password (not regular password)

# Phase 2 — add these when ready, leave blank until then
RENTCAST_API_KEY=                   # Brian's existing Rentcast key (free plan, 50 req/mo)
GOOGLE_BUSINESS_CLIENT_ID=          # From Google Cloud Console after OAuth app is approved
GOOGLE_BUSINESS_CLIENT_SECRET=      # From Google Cloud Console
ZINSPECTOR_API_KEY=                 # If Zinspector developer key is obtained
APTLY_API_TOKEN=                    # From Aptly Settings → API (needed for Phase 2 leasing funnel)
```

---

## 10. Open Questions for Brian

These are the only items that could not be determined from research and require Brian's answer before Q can finish the build.

---

**Question 1 — Aptly leasing funnel data**

Aptly has an API, but it is a general-purpose card/board system — there are no dedicated endpoints for leads or showings. Aptly stores everything as "cards" on a "board." To pull leasing funnel metrics (lead-to-showing rate, showing completion rate), Q needs to know:
- Which Aptly board tracks your leads and showings?
- What are the field names for "lead came in," "showing scheduled," "showing completed," and "showing missed"?

If this is unknown or not tracked in Aptly, the leasing funnel metrics (leads, showings, conversion rate) launch as manual entry fields and are upgraded in Phase 2.

---

**Question 2 — Where do inspection records live? ✅ RESOLVED**

Use Rentvine's inspection module (`list_inspections` / `get_inspection`) as primary source — Path A. Brian confirmed PDFs arrive but are not reliable for automated tracking. The Rentvine inspection module is the source of truth. File attachments (`list_attachments`) serve as fallback only if the module has no data for a property.

---

**Question 3 — Vacancy listing date ✅ RESOLVED**

Use prior lease `end_date` + 1 day as the vacancy start. Brian confirmed the turn process is: lease ends → move-out inspection → make-ready → pre-move-in inspection → new lease. The clock starts at move-out (lease end date).

---

**Question 4 — Owner contact logging ✅ RESOLVED**

Owner contact tracking is a recurring task system, not a log. Removed last-contact-date from the Owner Health Score formula. Phase 2 will add an "Owner Outreach" workflow with scheduled reminders for proactive check-in calls.

---

---

## 11. Authentication (Microsoft 365 SSO)

### What This Does

Login to the dashboard is restricted to Dream Big PM staff only. Anyone who tries to sign in must use a @dreambigpm.com Microsoft 365 account. The system redirects them to Microsoft's login page, verifies they belong to the correct domain, then looks up their role in a local user table and issues a session. No username/password to manage — staff use the same Microsoft login they already use every day.

### How It Works

1. User visits the dashboard and clicks "Sign in with Microsoft"
2. Browser redirects to Microsoft's login page (Microsoft Entra ID / Azure AD)
3. User signs in with their @dreambigpm.com Microsoft account
4. Microsoft redirects back to `/auth/callback` with a short-lived authorization code
5. Backend exchanges the code for tokens (using client credentials stored in environment variables)
6. Backend extracts the email address from the token
7. If the email does not end in `@dreambigpm.com` — reject. Return 403. Do not issue a session.
8. If the domain is valid — look up the email in the `users` table
9. If no matching row exists — reject. Access is provisioned by an admin, not self-serve.
10. If the row exists and `is_active = 1` — issue a JWT session cookie (httponly, 8-hour expiry) and redirect to the dashboard
11. Record `last_login` timestamp on the user's row

### Required Environment Variables

```bash
MICROSOFT_CLIENT_ID=        # From Azure App Registration
MICROSOFT_CLIENT_SECRET=    # From Azure App Registration
MICROSOFT_TENANT_ID=        # Azure tenant ID for the @dreambigpm.com Microsoft 365 org
```

### OAuth Scopes

`openid`, `profile`, `email`

### New API Endpoints

| Method | Endpoint | What it does |
|---|---|---|
| `GET` | `/auth/login` | Redirects the browser to Microsoft's OAuth login page |
| `GET` | `/auth/callback` | Receives the authorization code from Microsoft, exchanges it for a token, validates domain, looks up user role, issues session cookie |
| `POST` | `/auth/logout` | Clears the session cookie |
| `GET` | `/auth/me` | Returns the current logged-in user's email, display name, and role |

### Session Format

JWT stored in an `httponly` cookie (inaccessible to JavaScript — protects against XSS attacks). 8-hour expiry. Contains: `email`, `role`, `assigned_property_ids`, `display_name`.

### New SQLite Table: `users`

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL, -- 'admin', 'operations', 'property_manager', 'leasing_agent', 'maintenance_coordinator', 'field_services'
    assigned_property_ids TEXT, -- JSON array of Rentvine property IDs; NULL = all properties
    display_name TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login TEXT
);
```

### Enforcement Rule

Every `/api/*` endpoint must check for a valid session cookie. If the cookie is missing, expired, or invalid — return HTTP 401 with:
```json
{ "error": "Not authenticated", "code": 401 }
```

The frontend redirects to the login page on any 401 response.

---

## 12. Role-Level Permissions (RLPs)

### What This Does

Different staff members see different parts of the dashboard. A leasing agent should not see financial data. A field services tech should not see delinquency reports. This section defines exactly what each role can see, and enforces it in the backend — not just the frontend.

### Permission Table

| Section | Admin | Operations | Property Manager | Leasing Agent | Maintenance Coordinator | Field Services |
|---|---|---|---|---|---|---|
| AI Daily Briefing | Full | Ops version | Their properties | Leasing version | Maintenance version | Field version |
| Company KPI Scorecard (all 7) | All 7 | 5 KPIs (no PPU, no LER) | Hidden | Hidden | Hidden | Hidden |
| Financial Command Center | Visible | Hidden | Hidden | Hidden | Hidden | Hidden |
| NARPM Metrics (RPU/PPU/LER) | Visible | Hidden | Hidden | Hidden | Hidden | Hidden |
| Daily Zero Goals | All 4 | All 4 | Their properties | Vacant units only | Work orders only | Hidden |
| Occupancy and Leasing | Visible | Visible | Their properties | Visible | Hidden | Hidden |
| Renewal Pipeline | Visible | Visible | Their properties | Visible | Hidden | Hidden |
| Delinquency | Visible | Visible | Their properties | Hidden | Hidden | Hidden |
| Maintenance Health | Visible | Visible | Their properties | Hidden | Visible | Visible |
| Blue Ocean Metrics | Visible | No financials | Hidden | Hidden | Hidden | Hidden |
| Property Scorecard | All properties | All properties | Their properties | Their properties | Their properties | Their properties |
| Inspection Compliance | Visible | Visible | Their properties | Hidden | Visible | Visible |
| Alerts Panel | All alerts | Ops alerts | Their properties | Leasing alerts | Maintenance alerts | Field alerts |

### What "Their Properties" Means

If a user's `assigned_property_ids` column is `NULL` — they can see all properties (same as Admin/Operations).

If `assigned_property_ids` contains a JSON array (e.g. `["rv_123", "rv_456"]`) — the backend filters every data query to return only those property IDs. The user cannot see data for any other property, even by guessing an API URL.

### Backend Enforcement Pattern

Every `/api/*` endpoint must follow this sequence:

1. Read the session cookie and verify it is valid and not expired
2. Extract `role` and `assigned_property_ids` from the session payload
3. If the requested data section is not permitted for this role — return HTTP 403:
   ```json
   { "error": "Access denied for your role", "code": 403 }
   ```
4. If the role is permitted but with property filtering — apply the `assigned_property_ids` filter to every Rentvine query and every SQLite query before returning data
5. Never send unfiltered data to the frontend and rely on the frontend to hide it — the API itself must filter

---

## 13. Role-Based AI Briefing

### What This Does

Each role gets a different morning briefing written by Claude. An admin sees everything. A leasing agent sees only leasing-relevant updates. The briefing is personalized — it pulls only the data slice relevant to that person's job, then writes a 4-sentence plain-English summary of what changed since yesterday for them specifically.

### Prompt Template

```
System: You are a property management assistant writing a morning briefing for a {role} at Dream Big Property Management. Be specific, name units and properties. Focus on what changed since yesterday. Maximum 4 sentences.

User: Here is today's data relevant to {role}:
{role_specific_data_json}

Yesterday's snapshot:
{yesterday_snapshot_json}

Write the morning briefing.
```

### What `role_specific_data_json` Includes Per Role

| Role | Data included |
|---|---|
| Admin | All KPIs, all alerts, all financial data, all properties |
| Operations | All KPIs except PPU and LER metrics, all operational alerts, all properties |
| Property Manager | Only their assigned properties — delinquency detail, work orders, expiring leases, at-risk tenant flags |
| Leasing Agent | Vacant units with DOM, renewal pipeline statuses, leasing funnel metrics (when available) |
| Maintenance Coordinator | All open and overdue work orders portfolio-wide, turn times, inspection compliance status |
| Field Services | Inspections due or overdue, work orders at their assigned properties, invoices pending review |

### Implementation Notes

- The 6am scheduler generates one briefing per role that has at least one active user
- Briefings are cached in the database (add a `role_briefings` table — one row per role per day)
- `GET /api/briefing` now accepts an optional `?role=` query param; defaults to the requesting user's role
- The model, token limit, and scheduling rules from Section 6 still apply

### New SQLite Table: `role_briefings`

```sql
CREATE TABLE role_briefings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    briefing_date TEXT NOT NULL,    -- 'YYYY-MM-DD'
    role          TEXT NOT NULL,    -- one of the 6 roles
    text          TEXT NOT NULL,    -- the generated briefing
    generated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(briefing_date, role)
);
```

---

## 14. QBOA Integration (QuickBooks Online Accountant)

### What This Does

The Financial Command Center and NARPM metrics (RPU, PPU, DLeR, MLer, TLeR) require actual financial data — revenue, expenses, and net income — that does not exist in Rentvine. This data comes from QuickBooks Online Accountant (QBOA), which is where Dream Big PM does its accounting. This section documents the connection.

### Required Environment Variables

```bash
INTUIT_CLIENT_ID=        # From Intuit Developer Portal app registration
INTUIT_CLIENT_SECRET=    # From Intuit Developer Portal
INTUIT_REALM_ID=         # The QuickBooks Company ID (visible in QBO URL)
INTUIT_REFRESH_TOKEN=    # Long-lived token stored after first authorization
```

### OAuth Flow

1. First-time setup only: admin visits `GET /auth/quickbooks` — redirects to Intuit's OAuth consent screen
2. Admin approves access
3. Intuit redirects to `GET /auth/quickbooks/callback` with an authorization code
4. Backend exchanges code for an access token + refresh token
5. Both tokens are stored in the `oauth_tokens` table
6. All future QBOA calls use the stored refresh token to get a fresh access token automatically

OAuth scope: `com.intuit.quickbooks.accounting`

### New SQLite Table: `oauth_tokens`

```sql
CREATE TABLE oauth_tokens (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    service       TEXT NOT NULL UNIQUE,   -- e.g. 'quickbooks'
    access_token  TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at    TEXT NOT NULL           -- ISO 8601 datetime; access tokens expire every 60 minutes
);
```

### Token Refresh Rule

Before every QBOA API call: check `expires_at`. If the access token is expired or within 5 minutes of expiry — call Intuit's token refresh endpoint first, update the `oauth_tokens` row, then proceed with the API call.

### New API Endpoints

| Method | Endpoint | What it does |
|---|---|---|
| `GET` | `/auth/quickbooks` | Redirects to Intuit OAuth consent (admin only) |
| `GET` | `/auth/quickbooks/callback` | Handles Intuit redirect, stores tokens |

### QBOA API Calls Needed

All calls use base URL: `https://quickbooks.api.intuit.com`

| Data needed | Endpoint | Used for |
|---|---|---|
| P&L report | `GET /v3/company/{realmId}/reports/ProfitAndLoss?summarize_column_by=Month` | Financial Command Center, PPU computation |
| Revenue total | Same P&L report — income section total | RPU, TLeR |
| Net income | Same P&L report — net income line | PPU |
| Direct labor costs | Same P&L report — filtered to account codes 6100–6199 | DLeR, TLeR |
| Management labor costs | Same P&L report — filtered to account codes 6400–6499 | MLer, TLeR |

### Labor Cost Account Tagging (Brian Must Do This in QBOA)

For the LER metrics to compute correctly, payroll expense accounts in QBOA must be assigned to the correct account code range:

- **Account codes 6100–6199 (Direct Labor):** Staff whose work is primarily client/property-facing — property managers, leasing agents, maintenance coordinators. These are staff who spend more than 50% of their time directly serving clients or properties.
- **Account codes 6400–6499 (Management Labor):** Staff whose work is primarily managing others or driving sales/marketing — office manager, Brian himself (owner-operator). These are staff who spend more than 50% of their time in management, administration, or business development.

Brian must categorize each payroll account in QBOA once. The dashboard formulas read these codes automatically thereafter.

---

## 15. New NARPM Metrics

### What This Does

These are additional performance metrics defined by NARPM (the National Association of Residential Property Managers) that Brian tracks against industry benchmarks. They require both Rentvine data (unit counts, lease history) and QBOA data (revenue, expenses). They live in the Company KPI Scorecard and NARPM Metrics section.

---

### RPU — Revenue Per Unit

**Plain English:** How much management revenue the company earns per door it manages.

```
RPU = Total PM Revenue (from QBOA P&L, income section, current month)
    / Occupied Units (from Rentvine, current count)
```

NARPM industry average: $291/door. Brian's current: $256.85 (a gap of approximately $4,050/month at 119 doors).

---

### PPU — Profit Per Unit

**Plain English:** How much profit the company keeps per door after all expenses.

```
PPU = Net PM Profit (from QBOA P&L, net income line)
    / Total Units Under Management (from Rentvine, all active units)
```

NARPM tracks two variants: PPU with maintenance included, and PPU with brokerage income separated. Compute both; display the combined figure by default.

---

### DLeR — Direct Labor Efficiency Ratio

**Plain English:** For every dollar of direct labor cost, how many dollars of revenue does the company generate? Higher is better.

```
DLeR = Total Revenue (QBOA income section)
     / Direct Labor Costs (QBOA account codes 6100–6199)
```

NARPM benchmark: 3.96. Industry average: 2.90.

---

### MLer — Management Labor Efficiency Ratio

**Plain English:** For every dollar spent on management and overhead labor, how much gross profit remains?

```
MLer = (Total Revenue - Direct Labor Costs)
     / Management Labor Costs (QBOA account codes 6400–6499)
```

NARPM optimal range: 4.0–8.0.

---

### TLeR — Total Labor Efficiency Ratio

**Plain English:** For every dollar spent on all labor combined, how many dollars of revenue does the company generate?

```
TLeR = Total Revenue
     / (Direct Labor Costs + Management Labor Costs)
```

NARPM range: 1.43–2.22.

---

### Average Tenancy Length

**Plain English:** On average, how long do tenants stay before moving out?

```
Avg Tenancy = 1 / Annual Tenant Churn Rate   (result in years)
```

Annual Tenant Churn Rate = tenants who moved out in the last 12 months / average occupied units over the same period.

Data source: `list_leases` in Rentvine — compare `lease_start_date` to `lease_end_date` for leases with a status indicating the tenant has moved out.

---

### Portfolio Churn Rate (Owner/Door Churn)

**Plain English:** What percentage of the portfolio turned over — doors added and lost — in a given period?

```
Portfolio Churn Rate = Doors Lost in Period
                     / Average Doors in Period
                     × 100
```

Historical data: Brian's tracker spreadsheet (132 doors added, 45 doors lost since March 2023). This history will be imported into a new SQLite table.

### New SQLite Table: `portfolio_history`

```sql
CREATE TABLE portfolio_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date    TEXT NOT NULL,
    doors_count   INTEGER NOT NULL,  -- total doors after this event
    change        INTEGER NOT NULL,  -- +1, -1, +3, etc.
    property_name TEXT,              -- e.g. "Candle Light", "Birchwood"
    reason        TEXT,              -- e.g. "new client", "owner selling", "failure to launch", "fired - maintenance"
    year          INTEGER NOT NULL,
    month         INTEGER NOT NULL
);
```

### Schema Additions to `kpi_snapshots`

Add two columns to the existing `kpi_snapshots` table:

```sql
ALTER TABLE kpi_snapshots ADD COLUMN portfolio_churn_rate REAL;
ALTER TABLE kpi_snapshots ADD COLUMN avg_tenancy_length_years REAL;
```

---

## 16. Drill-Down Requirement

### What This Does

Every number on every card is clickable. When a user clicks any metric, they see the underlying records that make up that number. There are no dead ends. This is a non-negotiable design rule for the entire dashboard.

### The Pattern

Click a number → a slide-out panel (or modal) opens showing a table of the individual records that compose the metric. The table is sortable. Each row links to the full record in Rentvine where applicable.

Drill-down views respect role permissions — a Property Manager clicking "Open Work Orders (59)" only sees work orders for their assigned properties, not all 59.

### Drill-Down Table by Card

| Card / Metric | Click reveals |
|---|---|
| Past Due Leases (8) | Table: tenant name, unit, property, balance owed, days late, last payment date |
| Open Work Orders (59) | Table: work order description, property, unit, assigned vendor, days open, status |
| Overdue Work Orders (55) | Same as above, filtered to overdue only, sorted by age (oldest first) |
| Vacant Units (7) | Table: unit, property, days vacant, daily cost, total revenue loss so far |
| Rent Collected (93%) | Table: property-by-property breakdown showing collected vs. expected, plus list of tenants with outstanding balance |
| Occupancy (94.1%) | Table: all properties with occupancy %, vacant units highlighted in red |
| Lease Renewals (88%) | Table: all expiring leases with tenant name, unit, expiry date, and current renewal status |
| Speed of Repair (14.2 days) | Table: all open work orders with age in days, plus recently closed work orders with time-to-close |
| RPU ($256.85) | Table: revenue breakdown by property for the current month |
| Owner Health Score | Expanded detail card per owner: score, reasons for deductions, last distribution date, open work orders |
| True Turnover Cost ($5,200) | Table: each unit that turned in the last 12 months with cost breakdown (vacancy loss, make-ready, leasing cost) |
| Inspection Compliance | Table: each property with last inspection date, days since inspection, and compliance status |
| Delinquency total | Table: same as Past Due Leases, plus at-risk tenant flags |
| Average Tenancy Length | Table: breakdown by property of avg tenancy; list of longest-tenured tenants |
| Portfolio Churn Rate | Table: all door events from `portfolio_history` for the selected period |

### Implementation Notes for Q

- Drill-down is triggered by wrapping every metric number in a `<button>` with a `data-drill="endpoint_name"` attribute
- `dashboard.js` intercepts the click, calls `/api/drill/{endpoint_name}`, and renders the result in a slide-out panel component
- Add new API endpoints under `/api/drill/` for each drill-down target:
  - `GET /api/drill/past_due_leases`
  - `GET /api/drill/open_work_orders`
  - `GET /api/drill/overdue_work_orders`
  - `GET /api/drill/vacant_units`
  - `GET /api/drill/rent_collected`
  - `GET /api/drill/occupancy`
  - `GET /api/drill/renewal_pipeline`
  - `GET /api/drill/speed_of_repair`
  - `GET /api/drill/rpu`
  - `GET /api/drill/owner_health/{owner_id}`
  - `GET /api/drill/turnover_cost`
  - `GET /api/drill/inspection_compliance`
- All `/api/drill/*` endpoints enforce the same session + role-filtering rules as all other `/api/*` endpoints

---

*End of specification. Q may begin implementation when Brian confirms this plan.*
