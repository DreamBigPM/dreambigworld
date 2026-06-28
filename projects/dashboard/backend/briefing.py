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
        return {
            "inspection_compliance": kpi_data.get("inspection_compliance", []),
            "speed_of_repair": {
                "open_work_orders": kpi_data.get("speed_of_repair", {}).get("open_work_orders", []),
                "overdue_work_orders": kpi_data.get("speed_of_repair", {}).get("overdue_work_orders", []),
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

        system_prompt = (
            f"You are a property management assistant writing a morning briefing for "
            f"{role_desc} at Dream Big Property Management (120 units, Inland Empire CA). "
            f"Format your response as follows:\n"
            f"Line 1: A single headline sentence summarizing the most important thing to act on today.\n"
            f"Lines 2+: 3–5 bullet points starting with '• ', each one specific — name the unit or "
            f"property, include the number (dollar amount, days, percentage). "
            f"Focus on what changed since yesterday or what needs action today. "
            f"Plain English. No sub-bullets. No section headers."
        )

        user_prompt = (
            f"Today's data:\n{json.dumps(today_slice, indent=2)}\n\n"
            f"Yesterday's data:\n{json.dumps(yesterday_slice, indent=2)}\n\n"
            f"Write the morning briefing."
        )

        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
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
