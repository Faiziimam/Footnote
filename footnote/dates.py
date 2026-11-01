"""Dates in plain words: 'tomorrow', 'next friday', 'in 3 days', 'dec 12', '2026-12-01'."""
import datetime as dt
import re

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def parse(text, today=None):
    """-> ISO date string, or None if not understood."""
    t = (text or "").strip().lower().strip(".,")
    today = today or dt.date.today()
    if not t:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        try:
            return dt.date(*map(int, m.groups())).isoformat()
        except ValueError:
            return None
    if t == "today":
        return today.isoformat()
    if t == "tomorrow":
        return (today + dt.timedelta(days=1)).isoformat()
    if t in ("end of week", "this week", "eow"):
        return (today + dt.timedelta(days=(4 - today.weekday()) % 7)).isoformat()
    if t in ("next week",):
        return (today + dt.timedelta(days=7 - today.weekday() + 4)).isoformat()
    if t in ("end of month", "eom"):
        nxt = (today.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        return (nxt - dt.timedelta(days=1)).isoformat()
    m = re.fullmatch(r"in (\d+)\s*(day|days|week|weeks|month|months)", t)
    if m:
        n = int(m.group(1)) * {"d": 1, "w": 7, "m": 30}[m.group(2)[0]]
        return (today + dt.timedelta(days=n)).isoformat()
    m = re.fullmatch(r"(next |this |on )?(" + "|".join(DAYS) + r"|" + "|".join(d[:3] for d in DAYS) + ")", t)
    if m:
        want = next(i for i, d in enumerate(DAYS) if d.startswith(m.group(2)[:3]))
        if (m.group(1) or "").strip() == "next":          # 'next friday' = the Friday of NEXT week
            return (today + dt.timedelta(days=(6 - today.weekday()) + 1 + want)).isoformat()
        return (today + dt.timedelta(days=(want - today.weekday()) % 7 or 7)).isoformat()
    m = re.fullmatch(r"(?:(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3})[a-z]*|([a-z]{3})[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?)(?:,?\s+(\d{4}))?", t)
    if m:
        day = int(m.group(1) or m.group(4)); mon = (m.group(2) or m.group(3))[:3]
        if mon in MONTHS:
            year = int(m.group(5) or today.year)
            try:
                d = dt.date(year, MONTHS.index(mon) + 1, day)
            except ValueError:
                return None
            if not m.group(5) and d < today - dt.timedelta(days=180):
                d = d.replace(year=year + 1)
            return d.isoformat()
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
        except ValueError:
            return None
    return None


def parse_estimate(text):
    """'3d' '2 days' '5' '1w' '4h' -> days as a number (hours/8, weeks*5), or None."""
    m = re.fullmatch(r"~?\s*(\d+(?:\.\d+)?)\s*(d|day|days|w|wk|week|weeks|h|hr|hrs|hour|hours|pt|pts|points)?", (text or "").strip().lower())
    if not m:
        return None
    n, u = float(m.group(1)), (m.group(2) or "d")
    n = n * 5 if u.startswith("w") else n / 8 if u.startswith("h") else n
    return int(n) if n == int(n) else round(n, 2)
