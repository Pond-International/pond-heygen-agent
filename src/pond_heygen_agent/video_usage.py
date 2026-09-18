"""Meter logical generated videos, independently of their delivery representations."""

from decimal import ROUND_CEILING, Decimal, InvalidOperation

POLICY = "video_seconds_v1"
PRICING_PLAN = {
    "name": "Video Seconds",
    "pricing_model": "pay_as_you_go",
    "amount_minor": 13,
    "usage_quantity": 1,
    "usage_unit": "other",
    "custom_usage_unit": "video_second",
    "description": "$0.13 per actual completed video second. Sum distinct outputs and "
    "round up once per run; alternate files and repeat polling are not charged again.",
}


class UsageError(ValueError):
    """A generated output cannot be safely measured; never guess its charge."""


def duration_seconds(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise UsageError("The completed video's actual duration is unavailable.")
    try:
        duration = Decimal(str(value))
    except InvalidOperation:
        raise UsageError("The completed video's actual duration is invalid.") from None
    if not duration.is_finite() or not 0 < duration <= 1_000_000_000:
        raise UsageError("The completed video's actual duration is invalid.")
    return duration


def _group(records):
    grouped = {}
    for record in records:
        key = record.get("key")
        if not isinstance(key, str) or not key:
            raise UsageError("The completed video has no stable output identity.")
        grouped.setdefault(key, []).append(record)
    return grouped


def usage_quantity(records):
    total = Decimal(0)
    for copies in _group(records).values():
        durations = {duration_seconds(record.get("duration")) for record in copies}
        if len(durations) != 1:
            raise UsageError("HeyGen returned conflicting durations for one video.")
        total += durations.pop()
    return int(total.to_integral_value(rounding=ROUND_CEILING))


async def resolve_usage(records, measure):
    resolved = []
    for key, copies in _group(records).items():
        durations = set()
        for record in copies:
            try:
                durations.add(duration_seconds(record.get("duration")))
            except UsageError:
                pass  # Missing/invalid provider metadata requires a media measurement.
        if len(durations) > 1:
            raise UsageError("HeyGen returned conflicting durations for one video.")
        if durations:
            duration = durations.pop()
        else:
            url = next((record.get("url") for record in copies if record.get("url")), None)
            if not measure or not url:
                raise UsageError("The completed video's actual duration could not be measured.")
            duration = duration_seconds(await measure(url))
        resolved.append({"key": key, "duration": duration})
    return usage_quantity(resolved)
