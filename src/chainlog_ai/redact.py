"""Remove secrets from text before it is stored on a case."""

from __future__ import annotations

import re
from pathlib import Path

REDACTED = "[redacted]"

_MNEMONIC_LENGTHS = (24, 21, 18, 15, 12)
_MNEMONICS = tuple(
    (
        count,
        re.compile(
            rf"(?<![A-Za-z])([A-Za-z]+(?:[ \t]+[A-Za-z]+){{{count - 1}}})(?![A-Za-z])"
        ),
    )
    for count in _MNEMONIC_LENGTHS
)
_HEX64 = re.compile(r"(?:0x)?[0-9a-fA-F]{64}\Z")
_LONE_SECRET = re.compile(r"\s*(?:0x)?[0-9a-fA-F]{64}\s*\Z")
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
_BEARER = re.compile(r"(?i)(\bbearer\s+)([A-Za-z0-9\-._~+/]{20,}={0,2})")
_LABELED = re.compile(
    r"(?i)\b(?P<label>"
    r"private[\s_-]*key|keystore[\s_-]*password|jwt[\s_-]*secret|"
    r"priv[\s_-]*key|api[\s_-]*key|api[\s_-]*token|access[\s_-]*token|"
    r"passphrase|password|passwd|secret|token|jwt|key"
    r")\b(?P<sep>\s*[=:]\s*)"
    r"(?P<value>\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|[^\s,;]+)"
)
_PASSWORD_LABELS = frozenset({"password", "passphrase", "passwd", "keystorepassword"})
_TOKEN_LABELS = frozenset({"apikey", "apitoken", "accesstoken", "token"})
_PEER_ID = re.compile(r"(?:12D3Koo|16Uiu2HAm|Qm)[1-9A-HJ-NP-Za-km-z]{8,}")


def _load_bip39() -> frozenset[str]:
    path = Path(__file__).with_name("bip39_english.txt")
    words = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(words) != 2048:
        raise RuntimeError(f"BIP-39 English wordlist has {len(words)} words")
    return frozenset(words)


_BIP39 = _load_bip39()


def redact_excerpt(text: str) -> str:
    """Return ``text`` with each secret span replaced by ``[redacted]``."""

    if _LONE_SECRET.fullmatch(text):
        return REDACTED
    text = _redact_mnemonics(text)
    text = _JWT.sub(REDACTED, text)
    text = _BEARER.sub(_redact_bearer, text)
    return _LABELED.sub(_redact_labeled, text)


def _redact_mnemonics(text: str) -> str:
    for count, pattern in _MNEMONICS:
        text = pattern.sub(lambda match, count=count: _mnemonic_span(match, count), text)
    return text


def _mnemonic_span(match: re.Match[str], count: int) -> str:
    words = match.group(1).split()
    if len(words) == count and all(word.lower() in _BIP39 for word in words):
        return REDACTED
    return match.group(0)


def _redact_bearer(match: re.Match[str]) -> str:
    value = match.group(2)
    if _is_peer_id(value):
        return match.group(0)
    return f"{match.group(1)}{REDACTED}"


def _redact_labeled(match: re.Match[str]) -> str:
    raw = match.group("value")
    value = _unquote(raw)
    if not _value_is_secret(match.group("label"), value):
        return match.group(0)
    marked = f"{raw[0]}{REDACTED}{raw[-1]}" if _is_quoted(raw) else REDACTED
    return f"{match.group('label')}{match.group('sep')}{marked}"


def _value_is_secret(label: str, value: str) -> bool:
    if value in ("", REDACTED) or _is_peer_id(value) or _is_pubkey(value):
        return False
    if _normalize(label) in _PASSWORD_LABELS:
        return True
    if _HEX64.fullmatch(value) or _JWT.fullmatch(value):
        return True
    return _normalize(label) in _TOKEN_LABELS and len(value) >= 16


def _normalize(label: str) -> str:
    return re.sub(r"[\s_-]+", "", label.lower())


def _unquote(raw: str) -> str:
    if _is_quoted(raw):
        return raw[1:-1]
    return raw


def _is_quoted(raw: str) -> bool:
    return len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'"


def _is_peer_id(value: str) -> bool:
    return _PEER_ID.fullmatch(value) is not None


def _is_pubkey(value: str) -> bool:
    return re.fullmatch(r"0x[0-9a-fA-F]{96}", value) is not None
