"""Recognize an execution client and the timestamp it prints."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

EXECUTION_CLIENTS = ("geth", "nethermind", "erigon", "besu", "reth")

_BANNERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("nethermind", re.compile(r"nethermind", re.IGNORECASE)),
    ("erigon", re.compile(r"\berigon\b", re.IGNORECASE)),
    ("besu", re.compile(r"\bbesu\b", re.IGNORECASE)),
    ("reth", re.compile(r"\breth(?:_|:|\b)", re.IGNORECASE)),
    ("geth", re.compile(r"\bgeth\b", re.IGNORECASE)),
)
_BRACKET = re.compile(
    r"\[(?P<month>\d{2})-(?P<day>\d{2})\|(?P<hms>\d{2}:\d{2}:\d{2})\.(?P<frac>\d{3})\]"
)
_ISO = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})T(?P<hms>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?(?P<tz>Z|[+-]\d{2}:?\d{2})"
)
_CIVIL = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2}) (?P<hms>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?(?P<tz>Z|[+-]\d{2}:?\d{2})?"
)
_TIME_KEYS = ("t", "ts", "time", "timestamp", "Timestamp")


def normalize_execution_client(name: str) -> str:
    client = name.strip().lower()
    if client not in EXECUTION_CLIENTS:
        from chainlog_ai.ingest import InputError

        raise InputError(f"unknown execution client: {name}")
    return client


def detect_execution_client(text: str) -> str | None:
    """Return the client named by the first banner in ``text``."""

    for line in text.splitlines():
        for client, pattern in _BANNERS:
            if pattern.search(line):
                return client
    return None


def parse_execution_time(line: str, *, now: datetime) -> str | None:
    """Return the timestamp printed on ``line``, as UTC with a ``Z`` suffix."""

    try:
        return _parse_execution_time(line, now)
    except ValueError:
        return None


def _parse_execution_time(line: str, now: datetime) -> str | None:
    structured = _json_time(line)
    if structured is not None:
        return structured
    bracket = _BRACKET.search(line)
    if bracket is not None:
        return _from_bracket(bracket, now)
    iso = _ISO.search(line)
    if iso is not None:
        return _from_clock(iso)
    civil = _CIVIL.search(line)
    if civil is not None:
        return _from_clock(civil)
    return None


def _json_time(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    for key in _TIME_KEYS:
        stamp = value.get(key)
        if isinstance(stamp, str):
            parsed = parse_execution_time(stamp, now=datetime.now(timezone.utc))
            if parsed is not None:
                return parsed
    return None


def _from_bracket(match: re.Match[str], now: datetime) -> str:
    month = int(match.group("month"))
    day = int(match.group("day"))
    year = _year_for(month, day, now)
    frac = match.group("frac")
    clock = datetime.strptime(match.group("hms"), "%H:%M:%S").replace(
        year=year,
        month=month,
        day=day,
        microsecond=_microseconds(frac),
        tzinfo=timezone.utc,
    )
    return _format(clock, len(frac))


def _from_clock(match: re.Match[str]) -> str:
    frac = match.group("frac") or ""
    naive = datetime.strptime(
        f"{match.group('date')} {match.group('hms')}",
        "%Y-%m-%d %H:%M:%S",
    ).replace(microsecond=_microseconds(frac))
    tz = _zone(match.group("tz"))
    return _format(naive.replace(tzinfo=tz), len(frac))


def _year_for(month: int, day: int, now: datetime) -> int:
    year = now.year
    try:
        candidate = datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return year
    if candidate - now > timedelta(days=1):
        return year - 1
    return year


def _zone(text: str | None) -> timezone:
    if not text or text == "Z":
        return timezone.utc
    sign = 1 if text[0] == "+" else -1
    body = text[1:].replace(":", "")
    hours = int(body[:2])
    minutes = int(body[2:4]) if len(body) >= 4 else 0
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def _microseconds(frac: str) -> int:
    if not frac:
        return 0
    return int((frac + "000000")[:6])


def _format(value: datetime, digits: int) -> str:
    utc = value.astimezone(timezone.utc)
    base = utc.strftime("%Y-%m-%dT%H:%M:%S")
    if digits <= 0:
        return base + "Z"
    shown = min(digits, 6)
    return f"{base}.{utc.microsecond:06d}"[: len(base) + 1 + shown] + "Z"
