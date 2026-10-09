"""Recognize an MEV-boost builder log."""

from __future__ import annotations

import re

BUILDER_CLIENTS = ("mev-boost",)

_BANNERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("mev-boost", re.compile(r"\bmev[-\s]?boost\b", re.IGNORECASE)),
)


def normalize_builder_client(name: str) -> str:
    client = name.strip().lower().replace(" ", "")
    if client == "mevboost":
        client = "mev-boost"
    if client not in BUILDER_CLIENTS:
        from chainlog_ai.ingest import InputError

        raise InputError(f"unknown builder client: {name}")
    return client


def detect_builder_client(text: str) -> str | None:
    """Return the client named by the first banner in ``text``."""

    for line in text.splitlines():
        for client, pattern in _BANNERS:
            if pattern.search(line):
                return client
    return None
