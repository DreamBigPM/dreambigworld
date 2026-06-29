"""
briefing.py — AI morning briefing generator using Claude Haiku.

Generates role-specific plain-English briefings focused on what changed since yesterday.
Briefings are cached in SQLite — one per role per day.
"""

import os
import json
import logging
from datetime import date, timedelta

from backend import database

logger = logging.getLogger(__name__)

# Rotating Mon-Fri daily reminders — 5 core values + 20 first principles = 25 total (5-week cycle)
DAILY_PRINCIPLES = [
    {
        "title": "Live in The Truth",
        "body": (
            "Be forthright and transparent with Clients, Residents, and ourselves, "
            "regardless of how it might affect us or the company. "
            "Always do the Right Thing and deliver accurate, timely, solution-based information."
        ),
    },
    {
        "title": "Put the Client First, Always",
        "body": (
            "Our Investor Clients' financial interests come before our own. "
            "Their success is our primary objective — we celebrate their victories as if they were our own."
        ),
    },
    {
        "title": "Treat People Right",
        "body": (
            "Provide the best possible living environment for our Residents and strive to do the most we can for them. "
            "Happy, satisfied Residents communicate, cooperate, take care of the home, and pay timely rent."
        ),
    },
    {
        "title": "Have the Heart of a Teacher",
        "body": (
            "Educate and inform Clients, Residents, Vendors, and the public so they can make the best decisions for "
            "their families. Outstanding and frequent communication — sharing the Why, not just the What — creates "
            "loyalty and satisfaction."
        ),
    },
    {
        "title": "Own the Outcome",
        "body": (
            "It is our responsibility to perform our duties well every day, to innovate and improve, and to take "
            "all-out effort to find the best solution. Every one of our talented team members embraces their role "
            "and our passion to be of service and value."
        ),
    },
    {
        "title": "Property Management Is Business Management",
        "body": (
            "We manage businesses that happen to have properties as their primary assets. "
            "An Investor doesn't hire us to perform tasks — they hire us to produce outcomes: "
            "strategic pricing, qualified residents, protected assets."
        ),
    },
    {
        "title": "Their Money Is More Important Than Our Money",
        "body": (
            "We are financial stewards for our clients. We never recommend a repair, vendor, or action because "
            "it is more profitable for us. Full disclosure always — one self-serving recommendation destroys "
            "years of trust."
        ),
    },
    {
        "title": "Fix Fast Is Always Cheaper Than Fix Slow",
        "body": (
            "The longer a problem persists, the worse it gets and the more expensive it becomes. "
            "A small leak becomes water damage; a minor HVAC issue becomes a compressor replacement. "
            "Address maintenance issues immediately — delay always costs more."
        ),
    },
    {
        "title": "The Market Sets the Price",
        "body": (
            "Rent is determined by what qualified residents will pay — not what owners want or what Zillow says. "
            "Every week of vacancy chasing an unrealistic price costs real money the investor will never recoup."
        ),
    },
    {
        "title": "Residents Deserve Respect",
        "body": (
            "Happy residents are the primary driver of owner profitability — turnover destroys wealth, "
            "retention compounds it. Treat every maintenance request as if it were your own home."
        ),
    },
    {
        "title": "It's 'Residents,' Not 'Tenants'",
        "body": (
            "We provide Homes for the people in our community. The term 'Tenant' carries a dismissive connotation "
            "we do not accept. When people lease from us, they become Residents — and their space becomes their Home. "
            "That is sacred."
        ),
    },
    {
        "title": "It's 'Investor,' Not 'Owner'",
        "body": (
            "Language shapes how clients think about their properties. 'Investor' evokes strategy and long-term "
            "thinking; 'Owner' evokes emotional attachment and poor decisions. Use 'Investor' and 'investment "
            "property' in all communication."
        ),
    },
    {
        "title": "Retention Over Churn",
        "body": (
            "Every moveout means vacancy loss, make-ready costs, marketing expenses, and leasing effort. "
            "Our target is 80%+ lease renewal. Respond quickly, treat people fairly, and show residents "
            "you want them to stay."
        ),
    },
    {
        "title": "There Are No Shortcuts on Applicant Screening",
        "body": (
            "It is better to let a property sit vacant than to lease it to an unqualified resident. "
            "The pressure to fill a vacancy is real, but desperation leads to disaster. "
            "Every applicant goes through the full screening process — no exceptions."
        ),
    },
    {
        "title": "Processes Over Heroics",
        "body": (
            "Heroes burn out. Systems scale. Repeatable processes produce better long-term results than "
            "exceptional individual effort. Every team member owns their processes and is responsible for "
            "keeping documentation current."
        ),
    },
    {
        "title": "Truth Cures. Concealment Kills.",
        "body": (
            "Bad news does not improve with age. The moment a problem is identified, it is at its cheapest "
            "to solve. Lead with the Solution — don't just report fires, bring the extinguisher. "
            "A mistake handled with integrity is often more powerful than a mistake avoided."
        ),
    },
    {
        "title": "Informed Clients Are Better Clients",
        "body": (
            "Share industry knowledge freely through conversations and content. "
            "Educated clients make better decisions, have realistic expectations, and are easier to serve. "
            "The Why is more compelling than the What."
        ),
    },
    {
        "title": "Own the Terrain",
        "body": (
            "We anticipate problems and work to eliminate them before they escalate. "
            "We don't wait for residents to report a broken AC in August — we schedule annual maintenance. "
            "A failure to own the terrain means the terrain owns you."
        ),
    },
    {
        "title": "Lead from Where You Are",
        "body": (
            "You don't need a title to lead. If you see a problem, own it until it's resolved or handed off. "
            "'That's not my job' is not in our vocabulary. "
            "The person closest to the problem is often the best person to solve it."
        ),
    },
    {
        "title": "Good Is Better Than Great, but Right Is Better Than Fast",
        "body": (
            "Don't let perfectionism slow you down — but never let speed compromise accuracy. "
            "Always double-check names, numbers, lease terms, and rent amounts. "
            "If you misspell someone's name, you've lost credibility you may never get back."
        ),
    },
    {
        "title": "Accountability Flows Both Ways",
        "body": (
            "Managers hold team members accountable for results. Team members hold managers accountable for "
            "training, clarity, support, and resources. Accountability without support is blame; "
            "support without accountability is enabling."
        ),
    },
    {
        "title": "Keep It Simple",
        "body": (
            "Plain English is always preferred. Write for the person who just started, not the person who's "
            "been here five years. When you simplify, you are not dumbing it down — you are being of service "
            "by making sure the message is clear."
        ),
    },
    {
        "title": "Share Early and Often",
        "body": (
            "If a Client or Resident calls us first, we have already dropped the ball. "
            "Deliver updates proactively — don't wait until you have perfect information. "
            "Over-communicate until someone tells you to stop."
        ),
    },
    {
        "title": "A.I. Is Our Co-Pilot, Not Our Auto-Pilot",
        "body": (
            "AI tools help us work smarter and serve faster, but technology must be used sensibly, safely, and "
            "ethically. AI output requires human verification. We are accountable for every AI-assisted decision."
        ),
    },
    {
        "title": "Fair Housing Is Immutable",
        "body": (
            "Fair Housing compliance is not a policy — it is the floor. Every interaction must reflect fairness, "
            "equity, and professionalism with no exceptions. Consistent application of standards across all "
            "applicants and residents is required."
        ),
    },
]


def _get_daily_principle(today: date) -> dict:
    """Returns today's rotating principle (weekdays Mon-Fri only)."""
    if today.weekday() >= 5:
        return None
    return DAILY_PRINCIPLES[today.toordinal() % len(DAILY_PRINCIPLES)]

# ---------------------------------------------------------------------------
# Recurring meetings — add any standing meetings here.
# "day" is day of week: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
# ---------------------------------------------------------------------------
RECURRING_MEETINGS = [
    # {"day": 0, "title": "Staff Meeting", "time": "9:00 AM"},
    # {"day": 3, "title": "L10 Meeting", "time": "10:00 AM"},
]

# Observed company holidays — add as "YYYY-MM-DD" strings
COMPANY_HOLIDAYS: list[str] = [
    # "2026-07-04",
]


def _is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d.strftime("%Y-%m-%d") not in COMPANY_HOLIDAYS


def _prior_business_day(d: date) -> date:
    candidate = d - timedelta(days=1)
    while not _is_business_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


def _get_calendar_notes(today: date) -> list[str]:
    """Return calendar reminders relevant to today."""
    notes: list[str] = []

    # Timecard day: 1st and 15th of the month (or prior business day if weekend/holiday)
    for day_num in (1, 15):
        try:
            payroll_date = today.replace(day=day_num)
        except ValueError:
            continue
        if not _is_business_day(payroll_date):
            payroll_date = _prior_business_day(payroll_date)
        if today == payroll_date:
            notes.append("Timecard day — submit hours by end of day")

    # Recurring weekly meetings
    for meeting in RECURRING_MEETINGS:
        if today.weekday() == meeting.get("day"):
            time_str = f" at {meeting['time']}" if meeting.get("time") else ""
            notes.append(f"{meeting['title']}{time_str}")

    return notes


_ROLES = ["admin", "operations", "property_manager", "leasing_agent", "maintenance_coordinator", "field_services"]

_ROLE_DESCRIPTIONS = {
    "admin": "the company owner/administrator who oversees everything including financials",
    "operations": "the operations manager who oversees all day-to-day operations except financials",
    "property_manager": "a property manager responsible for specific assigned properties",
    "leasing_agent": "the leasing agent focused on vacancies, showings, and lease signings",
    "maintenance_coordinator": "the maintenance coordinator managing work orders and vendors",
    "field_services": "a field services team member doing on-site inspections and property visits",
}


def _slice_kpi_data(kpi_data: dict, role: str, assigned_property_ids: list = None) -> dict:
    """Return only the KPI fields relevant to this role."""
    if role == "admin":
        return kpi_data

    if role == "operations":
        return {k: v for k, v in kpi_data.items()
                if k not in ("narpm_metrics",)}

    if role == "property_manager":
        data = {
            "rent_collected": kpi_data.get("rent_collected", {}),
            "occupancy": kpi_data.get("occupancy", {}),
            "renewal_rate": kpi_data.get("renewal_rate", {}),
            "speed_of_repair": kpi_data.get("speed_of_repair", {}),
            "at_risk_tenants": kpi_data.get("at_risk_tenants", []),
            "inspection_compliance": kpi_data.get("inspection_compliance", []),
        }
        if assigned_property_ids:
            # Filter lists to only their assigned properties
            data["speed_of_repair"]["open_work_orders"] = [
                wo for wo in data["speed_of_repair"].get("open_work_orders", [])
                if wo.get("property_name") in assigned_property_ids
            ]
        return data

    if role == "leasing_agent":
        return {
            "occupancy": kpi_data.get("occupancy", {}),
            "days_on_market": kpi_data.get("days_on_market", {}),
            "renewal_rate": kpi_data.get("renewal_rate", {}),
            "vacancy_cost_clock": kpi_data.get("vacancy_cost_clock", []),
        }

    if role == "maintenance_coordinator":
        return {
            "speed_of_repair": kpi_data.get("speed_of_repair", {}),
            "inspection_compliance": kpi_data.get("inspection_compliance", []),
            "maintenance_satisfaction": kpi_data.get("maintenance_satisfaction"),
        }

    if role == "field_services":
        sor = kpi_data.get("speed_of_repair", {})
        return {
            "occupancy": kpi_data.get("occupancy", {}),
            "vacancy_cost_clock": kpi_data.get("vacancy_cost_clock", []),
            "inspection_compliance": kpi_data.get("inspection_compliance", []),
            "speed_of_repair": {
                "open_count": sor.get("open_count", 0),
                "overdue_count": sor.get("overdue_count", 0),
                "open_work_orders": sor.get("open_work_orders", []),
                "overdue_work_orders": sor.get("overdue_work_orders", []),
            },
        }

    return kpi_data


async def generate_briefing(
    role: str,
    kpi_data: dict,
    yesterday_data: dict,
    assigned_property_ids: list = None,
) -> str:
    """Call Claude Haiku to generate a role-specific morning briefing."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "Morning briefing unavailable — ANTHROPIC_API_KEY not configured."

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        role_desc = _ROLE_DESCRIPTIONS.get(role, role)
        today_slice = _slice_kpi_data(kpi_data, role, assigned_property_ids)
        yesterday_slice = _slice_kpi_data(yesterday_data, role, assigned_property_ids) if yesterday_data else {}

        today = date.today()
        principle = _get_daily_principle(today)
        calendar_notes = _get_calendar_notes(today)

        system_prompt = (
            f"You are a property management assistant writing a morning briefing for "
            f"{role_desc} at Dream Big Property Management (120 units, Inland Empire CA). "
            f"Format your response as follows:\n"
            f"Line 1: A single headline sentence summarizing the most important thing to act on today.\n"
            f"Lines 2+: 3–5 bullet points starting with '• ', each one specific — name the unit or "
            f"property, include the number (dollar amount, days, percentage). "
            f"Focus on what changed since yesterday or what needs action today. "
            f"Plain English. No sub-bullets. No section headers. "
            f"Always say 'resident' or 'residents' — never 'tenant' or 'tenants'. "
            f"Do not use asterisks or markdown bold anywhere in your response."
        )

        # Calendar reminders
        if calendar_notes:
            system_prompt += (
                f"\n\nAfter the operational bullets, add one bullet for each calendar reminder "
                f"below, formatted as '• [Calendar] <reminder>'. "
                f"Keep each to one plain sentence."
            )

        # Daily principle
        if principle:
            p_title = principle["title"]
            system_prompt += (
                f"\n\nEnd the briefing with one final bullet: "
                f"'• First Principle — {p_title}: ' followed by one sentence "
                f"connecting this principle to something actionable or relevant today. "
                f"Keep it to one sentence."
            )

        extras: list[str] = []
        if calendar_notes:
            extras.append("Calendar reminders for today:\n" + "\n".join(f"- {n}" for n in calendar_notes))
        if principle:
            extras.append(
                f"First Principle of the Day — {principle['title']}:\n{principle['body']}"
            )

        user_prompt = (
            f"Today's data:\n{json.dumps(today_slice, indent=2)}\n\n"
            f"Yesterday's data:\n{json.dumps(yesterday_slice, indent=2)}\n\n"
            + ("\n\n".join(extras) + "\n\n" if extras else "")
            + "Write the morning briefing."
        )

        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=700,
            messages=[{"role": "user", "content": user_prompt}],
            system=system_prompt,
        )

        return message.content[0].text.strip()

    except Exception as e:
        logger.error(f"Briefing generation failed for role={role}: {e}")
        return (
            "Morning briefing unavailable. Check the dashboard sections for current status."
        )


async def get_or_generate_briefing(role: str = "admin", kpi_data: dict = None) -> str:
    """Return today's briefing for the role, generating it if needed."""
    cached = database.get_todays_role_briefing(role)
    if cached:
        return cached

    if kpi_data is None:
        # Fall back to last snapshot from SQLite
        snapshots = database.get_kpi_snapshots(days=2)
        kpi_data = snapshots[-1] if snapshots else {}

    yesterday_snapshots = database.get_kpi_snapshots(days=2)
    yesterday_data = yesterday_snapshots[0] if len(yesterday_snapshots) >= 2 else {}

    text = await generate_briefing(role, kpi_data, yesterday_data)
    database.save_role_briefing(role, text)
    return text


async def generate_all_briefings(kpi_data: dict):
    """Generate briefings for all active roles. Called by the scheduler at 6:05am."""
    for role in _ROLES:
        try:
            existing = database.get_todays_role_briefing(role)
            if not existing:
                yesterday_snapshots = database.get_kpi_snapshots(days=2)
                yesterday_data = yesterday_snapshots[0] if len(yesterday_snapshots) >= 2 else {}
                text = await generate_briefing(role, kpi_data, yesterday_data)
                database.save_role_briefing(role, text)
                logger.info(f"Generated briefing for role={role}")
        except Exception as e:
            logger.error(f"Failed to generate briefing for role={role}: {e}")
