"""Recognize a validator client or Web3Signer."""

from __future__ import annotations

import re

VALIDATOR_CLIENTS = ("lighthouse", "prysm", "teku", "nimbus", "lodestar", "web3signer")

_BANNERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("web3signer", re.compile(r"\bweb3\s*signer\b", re.IGNORECASE)),
    ("lighthouse", re.compile(r"\blighthouse\b", re.IGNORECASE)),
    ("lodestar", re.compile(r"\blodestar\b", re.IGNORECASE)),
    ("nimbus", re.compile(r"\bnimbus\b", re.IGNORECASE)),
    ("prysm", re.compile(r"\bprysm\b", re.IGNORECASE)),
    ("teku", re.compile(r"\bteku\b", re.IGNORECASE)),
)


def normalize_validator_client(name: str) -> str:
    client = name.strip().lower().replace(" ", "")
    if client not in VALIDATOR_CLIENTS:
        from chainlog_ai.ingest import InputError

        raise InputError(f"unknown validator client: {name}")
    return client


def detect_validator_client(text: str) -> str | None:
    """Return the client named by the first banner in ``text``."""

    for line in text.splitlines():
        for client, pattern in _BANNERS:
            if pattern.search(line):
                return client
    return None
