"""
pl_parser.py — Parse a QuickBooks P&L PDF export to extract NARPM metrics.

DLER accounts (per Brian): 6319.01, 6325, 6339.01, 6339.02
MLER accounts (per Brian): 6410
TLER = DLER + MLER
"""

import re
import io
import logging

logger = logging.getLogger(__name__)

# Specific GL accounts that count toward each labor metric
DLER_ACCOUNTS = {"6319.01", "6325", "6339.01", "6339.02"}
MLER_ACCOUNTS = {"6410"}


def _parse_dollar(s: str) -> float:
    s = s.strip().replace(",", "").replace("$", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _fmt_dollar(v: float) -> str:
    return f"${v:,.2f}"


def parse_pl_pdf(file_bytes: bytes) -> dict:
    """
    Parse a QuickBooks P&L PDF export.

    Returns:
        {
          "period": "May 2026",
          "gross_revenue": 31444.00,
          "direct_labor": 7397.83,       # sum of DLER_ACCOUNTS only
          "mgmt_labor": 8000.00,          # sum of MLER_ACCOUNTS only
          "total_expenses": 38099.59,
          "net_income": -7301.04,
          "dler_items": [{"gl": "6319.01", "name": "...", "amount": 1618.75}, ...],
          "mler_items": [{"gl": "6410",    "name": "...", "amount": 8000.00}],
          "error": None
        }
    """
    try:
        import pdfplumber
    except ImportError:
        return {"error": "pdfplumber not installed — run: pip install pdfplumber"}

    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            lines = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    lines.extend(text.splitlines())
    except Exception as e:
        return {"error": f"Could not read PDF: {e}"}

    # Period from header (3rd non-blank line)
    period = "Unknown period"
    non_blank = [l.strip() for l in lines if l.strip()]
    if len(non_blank) >= 3:
        period = non_blank[2]

    gross_revenue  = None
    total_expenses = None
    net_income     = None
    dler_items     = []
    mler_items     = []

    # Regex to match a detail line: GL_NUMBER  Account Name  amount
    # e.g. "6319.01 Field Services Coordinator 1,618.75"
    detail_re = re.compile(
        r"^(\d{4}(?:\.\d{2})?)\s+(.+?)\s+([\d,]+\.\d{2})$"
    )

    for line in lines:
        stripped = line.strip()

        # Revenue total
        if re.match(r"Total for Income\s+\$", stripped):
            m = re.search(r"(-?\$[\d,]+\.\d{2})$", stripped)
            if m:
                gross_revenue = _parse_dollar(m.group(1))

        # Total expenses
        if re.match(r"Total for Expenses\s+\$", stripped):
            m = re.search(r"(-?\$[\d,]+\.\d{2})$", stripped)
            if m:
                total_expenses = _parse_dollar(m.group(1))

        # Net income (not "Net Operating Income")
        if re.match(r"Net Income\s+-?\$", stripped) and "Operating" not in stripped:
            m = re.search(r"(-?\$[\d,]+\.\d{2})$", stripped)
            if m:
                net_income = _parse_dollar(m.group(1))

        # Individual GL account lines
        dm = detail_re.match(stripped)
        if dm:
            gl, name, amt_str = dm.group(1), dm.group(2).strip(), dm.group(3)
            amount = _parse_dollar(amt_str)
            if gl in DLER_ACCOUNTS:
                # Avoid duplicates (pdfplumber sometimes repeats across page break)
                if not any(i["gl"] == gl for i in dler_items):
                    dler_items.append({"gl": gl, "name": name, "amount": amount})
            if gl in MLER_ACCOUNTS:
                if not any(i["gl"] == gl for i in mler_items):
                    mler_items.append({"gl": gl, "name": name, "amount": amount})

    direct_labor = round(sum(i["amount"] for i in dler_items), 2) if dler_items else None
    mgmt_labor   = round(sum(i["amount"] for i in mler_items), 2) if mler_items else None

    missing = [k for k, v in {
        "gross_revenue":  gross_revenue,
        "direct_labor":   direct_labor,
        "mgmt_labor":     mgmt_labor,
        "total_expenses": total_expenses,
        "net_income":     net_income,
    }.items() if v is None]

    if missing:
        return {
            "error": (
                f"Could not find: {', '.join(missing)}. "
                "Expected GL accounts: DLER=6319.01/6325/6339.01/6339.02, MLER=6410."
            )
        }

    return {
        "period":        period,
        "gross_revenue": gross_revenue,
        "direct_labor":  direct_labor,
        "mgmt_labor":    mgmt_labor,
        "total_expenses":total_expenses,
        "net_income":    net_income,
        "dler_items":    dler_items,
        "mler_items":    mler_items,
        "error":         None,
    }


def compute_narpm_metrics(parsed: dict, door_count: int) -> dict:
    """Compute NARPM metrics. Includes breakdown for drill-down display."""
    gr = parsed.get("gross_revenue") or 0
    if gr <= 0 or not door_count:
        return {k: None for k in ["rpu", "ppu", "dler", "mler", "tler", "expense_ratio", "breakdown"]}

    dl = parsed.get("direct_labor")   or 0
    ml = parsed.get("mgmt_labor")     or 0
    te = parsed.get("total_expenses") or 0
    ni = parsed.get("net_income")     or 0

    total_labor = dl + ml
    dler = round(gr / dl,           2) if dl > 0 else None
    mler = round(gr / ml,           2) if ml > 0 else None
    tler = round(gr / total_labor,  2) if total_labor > 0 else None

    return {
        "rpu":           round(gr / door_count, 2),
        "ppu":           round(ni / door_count, 2),
        "dler":          dler,
        "mler":          mler,
        "tler":          tler,
        "expense_ratio": round(te / gr * 100, 2),
        "breakdown": {
            "gross_revenue":  gr,
            "total_expenses": te,
            "net_income":     ni,
            "door_count":     door_count,
            "dler_items":     parsed.get("dler_items", []),
            "mler_items":     parsed.get("mler_items", []),
            "direct_labor":   dl,
            "mgmt_labor":     ml,
        },
    }
