"""Common date formatting utility for the Multi-Agent Procurement System."""
from datetime import datetime


def format_display_date(date_str: str) -> str:
    """Format any date string to DD-MM-YYYY HH:MM AM/PM for UI display.
    
    Accepts multiple input formats:
    - 2026-03-07 17:59:42
    - 2026-03-07T17:59:42
    - 2026-03-07
    - ISO format with timezone
    
    Returns formatted string like: 07-03-2026 05:59 PM
    If parsing fails, returns the original string unchanged.
    """
    if not date_str or not isinstance(date_str, str):
        return date_str or "N/A"

    date_str = date_str.strip()

    formats_to_try = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%b %d, %I:%M %p",
        "%d %b %Y %H:%M:%S",
    ]

    for fmt in formats_to_try:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%d-%m-%Y %I:%M %p")
        except (ValueError, TypeError):
            continue

    # Try ISO format parsing as last resort
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%d-%m-%Y %I:%M %p")
    except (ValueError, TypeError):
        pass

    return date_str
