"""Shared helpers: errors, validation, time, money."""
import re
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from flask import request

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


class ApiError(Exception):
    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def not_found(what="Resource"):
    return ApiError(404, "not_found", f"{what} not found")


def conflict(message, details=None):
    return ApiError(409, "conflict", message, details)


def forbidden(message="Your role is not allowed to perform this action"):
    return ApiError(403, "forbidden", message)


def invalid(message, details=None):
    return ApiError(422, "validation_error", message, details)


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "invalid_body", "Request body must be a JSON object")
    return data


def validate(data, spec):
    """Validate `data` against `spec`; returns cleaned values (only keys that were
    supplied or have a default). Spec keys: type, required, default, min, max,
    min_len, max_len, min_items, max_items, choices, pattern."""
    if not isinstance(data, dict):
        raise ApiError(400, "invalid_body", "A JSON object is required")
    out, errors = {}, {}
    for name, rule in spec.items():
        typ = rule.get("type", str)
        if data.get(name) is None:
            if rule.get("required"):
                errors[name] = "is required"
            elif "default" in rule:
                out[name] = rule["default"]
            continue
        v = data[name]
        if typ is str:
            if not isinstance(v, str):
                errors[name] = "must be a string"
                continue
            v = v.strip()
            if rule.get("required") and not v:
                errors[name] = "must not be empty"
                continue
            if len(v) < rule.get("min_len", 0):
                errors[name] = f"must be at least {rule['min_len']} characters"
                continue
            if len(v) > rule.get("max_len", 10000):
                errors[name] = f"must be at most {rule['max_len']} characters"
                continue
            if "pattern" in rule and not rule["pattern"].match(v):
                errors[name] = "has an invalid format"
                continue
        elif typ is int:
            if isinstance(v, bool) or not isinstance(v, int):
                errors[name] = "must be an integer"
                continue
        elif typ is float:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                errors[name] = "must be a number"
                continue
            v = float(v)
        elif typ is bool:
            if not isinstance(v, bool):
                errors[name] = "must be true or false"
                continue
        elif typ is list:
            if not isinstance(v, list):
                errors[name] = "must be a list"
                continue
            if len(v) < rule.get("min_items", 0):
                errors[name] = f"must contain at least {rule['min_items']} entries"
                continue
            if len(v) > rule.get("max_items", 1000):
                errors[name] = f"must contain at most {rule['max_items']} entries"
                continue
        if typ in (int, float):
            if "min" in rule and v < rule["min"]:
                errors[name] = f"must be >= {rule['min']}"
                continue
            if "max" in rule and v > rule["max"]:
                errors[name] = f"must be <= {rule['max']}"
                continue
        if "choices" in rule and v not in rule["choices"]:
            errors[name] = "must be one of: " + ", ".join(map(str, rule["choices"]))
            continue
        out[name] = v
    if errors:
        raise invalid("Invalid input", errors)
    return out


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime(ISO_FMT)


def now_iso():
    return iso(now())


def parse_iso(value, field="datetime"):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise invalid("Invalid input", {field: "must be an ISO-8601 timestamp"})
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field="date"):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise invalid("Invalid input", {field: "must be YYYY-MM-DD"})


def local_day_bounds(day, offset_minutes, days=1):
    """UTC ISO bounds [start, end) for `days` local calendar days starting at `day`."""
    off = timedelta(minutes=offset_minutes)
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - off
    return iso(start), iso(start + timedelta(days=days))


def local_today(offset_minutes):
    return (now() + timedelta(minutes=offset_minutes)).date()


def to_local(iso_str, offset_minutes):
    return parse_iso(iso_str) + timedelta(minutes=offset_minutes)


def pct(amount, rate):
    """amount * rate% rounded half-up to an integer number of minor units."""
    value = Decimal(int(amount)) * Decimal(str(rate)) / Decimal(100)
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def page_args():
    try:
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        raise invalid("Invalid input", {"limit/offset": "must be integers"})
    if not 1 <= limit <= 200 or offset < 0:
        raise invalid("Invalid input", {"limit/offset": "limit must be 1-200 and offset >= 0"})
    return limit, offset
