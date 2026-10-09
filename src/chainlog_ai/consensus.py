"""Recognize a consensus client and the slot, epoch, and block it prints."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from chainlog_ai.execution import parse_execution_time

CONSENSUS_CLIENTS = ("lighthouse", "prysm", "teku", "nimbus", "lodestar")

_BANNERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("lighthouse", re.compile(r"\blighthouse\b", re.IGNORECASE)),
    ("lodestar", re.compile(r"\blodestar\b", re.IGNORECASE)),
    ("nimbus", re.compile(r"\bnimbus\b", re.IGNORECASE)),
    ("prysm", re.compile(r"\bprysm\b", re.IGNORECASE)),
    ("teku", re.compile(r"\bteku\b", re.IGNORECASE)),
)
_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
_MONTH_TIME = re.compile(
    r"(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"[-\s]+(?P<day>\d{1,2})[ T]"
    r"(?P<hms>\d{2}:\d{2}:\d{2})\.(?P<frac>\d+)",
    re.IGNORECASE,
)
_SLOT = re.compile(r"(?i)(?<![A-Za-z_])slot(?![A-Za-z_])\s*[:=]\s*(\d+)")
_EPOCH = re.compile(r"(?i)(?<![A-Za-z_])epoch(?![A-Za-z_])\s*[:=]\s*(\d+)")
_BLOCK = re.compile(
    r"(?i)(?<![A-Za-z_])(?:block_root|head_block|block_hash|block)(?![A-Za-z_])"
    r"\s*[:=]\s*(0x[0-9a-fA-F]+|\d+)"
)
def normalize_consensus_client(name: str) -> str:
    client = name.strip().lower()
    if client not in CONSENSUS_CLIENTS:
        from chainlog_ai.ingest import InputError

        raise InputError(f"unknown consensus client: {name}")
    return client


def detect_consensus_client(text: str) -> str | None:
    """Return the client named by the first banner in ``text``."""

    for line in text.splitlines():
        for client, pattern in _BANNERS:
            if pattern.search(line):
                return client
    return None


def parse_consensus_time(line: str, *, now: datetime) -> str | None:
    """Return the timestamp printed on ``line``, as UTC with a ``Z`` suffix."""

    parsed = parse_execution_time(line, now=now)
    if parsed is not None:
        return parsed
    return _month_time(line, now)


def consensus_fields(line: str) -> tuple[int | None, int | None, str | None]:
    """Return slot, epoch, and block when the line prints them."""

    slot, epoch, block = _json_fields(line)
    if slot is None:
        found = _SLOT.search(line)
        if found is not None:
            slot = int(found.group(1))
    if epoch is None:
        found = _EPOCH.search(line)
        if found is not None:
            epoch = int(found.group(1))
    if block is None:
        found = _BLOCK.search(line)
        if found is not None:
            block = found.group(1)
    return slot, epoch, block


def _json_fields(line: str) -> tuple[int | None, int | None, str | None]:
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None, None, None
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return None, None, None
    if not isinstance(value, dict):
        return None, None, None
    slot = _as_int(value.get("slot"))
    epoch = _as_int(value.get("epoch"))
    block: str | None = None
    for key in ("block_root", "head_block", "block_hash", "block"):
        if key in value and value[key] is not None:
            block = str(value[key])
            break
    return slot, epoch, block


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _month_time(line: str, now: datetime) -> str | None:
    match = _MONTH_TIME.search(line)
    if match is None:
        return None
    month = _MONTHS[match.group("mon").title()]
    day = int(match.group("day"))
    year = _year_for(month, day, now)
    try:
        clock = datetime.strptime(match.group("hms"), "%H:%M:%S").replace(
            year=year,
            month=month,
            day=day,
            microsecond=_microseconds(match.group("frac")),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    return _format(clock, len(match.group("frac")))


def _year_for(month: int, day: int, now: datetime) -> int:
    year = now.year
    try:
        candidate = datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return year
    if candidate - now > timedelta(days=1):
        return year - 1
    return year


def _microseconds(frac: str) -> int:
    return int((frac + "000000")[:6])


def _format(value: datetime, digits: int) -> str:
    base = value.strftime("%Y-%m-%dT%H:%M:%S")
    shown = min(digits, 6)
    return f"{base}.{value.microsecond:06d}"[: len(base) + 1 + shown] + "Z"
