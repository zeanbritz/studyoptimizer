"""Shared study-duration handling for onboarding and the Subjects page."""

WEEKDAYS = (
    ("monday", "Monday"),
    ("tuesday", "Tuesday"),
    ("wednesday", "Wednesday"),
    ("thursday", "Thursday"),
    ("friday", "Friday"),
    ("saturday", "Saturday"),
    ("sunday", "Sunday"),
)


def availability_days(record=None, posted=None):
    """Return picker-ready values without changing any saved availability."""
    result = []
    for key, label in WEEKDAYS:
        if posted is None:
            enabled = bool(getattr(record, f"{key}_enabled", False))
            value = getattr(record, f"{key}_time", "") or ""
        else:
            enabled = posted.get(f"{key}_enabled") == "1"
            value = posted.get(f"{key}_time", "") or ""
        try:
            hours, minutes = (int(part) for part in value.split(":"))
        except (TypeError, ValueError):
            hours, minutes = None, None
        result.append({
            "key": key,
            "label": label,
            "enabled": enabled,
            "time": value,
            "hours": hours,
            "minutes": minutes,
        })
    return result


def parse_availability(post):
    """Validate the same HH:MM values submitted by both time pickers."""
    values = {}
    errors = {}
    total_minutes = 0
    for key, label in WEEKDAYS:
        enabled = post.get(f"{key}_enabled") == "1"
        raw_time = (post.get(f"{key}_time") or "").strip()
        if not enabled:
            values[key] = (False, "")
            continue
        try:
            hours_text, minutes_text = raw_time.split(":")
            if not (hours_text.isdigit() and minutes_text.isdigit()):
                raise ValueError
            hours, minutes = int(hours_text), int(minutes_text)
            if not (0 <= hours <= 24 and 0 <= minutes <= 59):
                raise ValueError
            if (hours == 24 and minutes) or (hours == 0 and minutes == 0):
                raise ValueError
        except ValueError:
            errors[key] = f"Choose a study duration for {label}."
            continue
        values[key] = (True, f"{hours:02d}:{minutes:02d}")
        total_minutes += hours * 60 + minutes
    return values, errors, total_minutes
