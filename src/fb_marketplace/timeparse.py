from __future__ import annotations

import re
from datetime import datetime, time, timedelta


_RELATIVE_UNITS = {
    "s": "seconds",
    "sec": "seconds",
    "secs": "seconds",
    "second": "seconds",
    "seconds": "seconds",
    "m": "minutes",
    "min": "minutes",
    "mins": "minutes",
    "minute": "minutes",
    "minutes": "minutes",
    "h": "hours",
    "hr": "hours",
    "hrs": "hours",
    "hour": "hours",
    "hours": "hours",
    "d": "days",
    "day": "days",
    "days": "days",
    "w": "weeks",
    "wk": "weeks",
    "wks": "weeks",
    "week": "weeks",
    "weeks": "weeks",
}


def parse_relative_timestamp(label: str | None, now: datetime | None = None) -> datetime | None:
    if not label:
        return None

    now = now or datetime.now().astimezone()
    cleaned = " ".join(label.replace("\u00b7", " ").split()).strip()
    lowered = cleaned.lower()

    if lowered in {"now", "just now"}:
        return now

    match = re.search(r"(\d+)\s*([a-z]+)", lowered)
    if match:
        value = int(match.group(1))
        unit = _RELATIVE_UNITS.get(match.group(2))
        if unit:
            return now - timedelta(**{unit: value})

    if lowered.startswith("yesterday"):
        parsed_time = _parse_time_suffix(cleaned)
        base_date = (now - timedelta(days=1)).date()
        if parsed_time is None:
            return datetime.combine(base_date, time.min, tzinfo=now.tzinfo)
        return datetime.combine(base_date, parsed_time, tzinfo=now.tzinfo)

    for fmt in (
        "%B %d at %I:%M %p",
        "%b %d at %I:%M %p",
        "%B %d, %Y at %I:%M %p",
        "%b %d, %Y at %I:%M %p",
    ):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            year = parsed.year if "%Y" in fmt else now.year
            return parsed.replace(year=year, tzinfo=now.tzinfo)
        except ValueError:
            continue

    weekday_match = re.match(
        r"^(monday|tuesday|wednesday|thursday|friday|saturday|sunday) at (.+)$",
        lowered,
    )
    if weekday_match:
        parsed_time = _parse_time_suffix(cleaned)
        if parsed_time is None:
            return None
        target_weekday = [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ].index(weekday_match.group(1))
        days_back = (now.weekday() - target_weekday) % 7
        candidate = now - timedelta(days=days_back)
        return datetime.combine(candidate.date(), parsed_time, tzinfo=now.tzinfo)

    return None


def age_seconds(timestamp: datetime | None, now: datetime | None = None) -> int | None:
    if timestamp is None:
        return None
    now = now or datetime.now().astimezone()
    delta = now - timestamp
    return max(int(delta.total_seconds()), 0)


def first_timestamp_in_text(text: str | None, now: datetime | None = None) -> tuple[str | None, datetime | None]:
    if not text:
        return None, None

    lines = [line.strip(" ,") for line in text.splitlines() if line.strip()]
    for candidate in reversed(lines):
        parsed = parse_relative_timestamp(candidate, now=now)
        if parsed is not None:
            return candidate, parsed

    inline_patterns = re.findall(
        r"(?:just now|now|yesterday(?: at [0-9: ]+[ap]m)?|\d+\s*[a-z]+)",
        text,
        flags=re.IGNORECASE,
    )
    for candidate in reversed(inline_patterns):
        parsed = parse_relative_timestamp(candidate, now=now)
        if parsed is not None:
            return candidate, parsed

    return None, None


def _parse_time_suffix(label: str) -> time | None:
    match = re.search(r"at\s+([0-9]{1,2}:[0-9]{2}\s*[APMapm]{2})", label)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1).upper(), "%I:%M %p").time()
    except ValueError:
        return None
