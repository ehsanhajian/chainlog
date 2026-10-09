"""Read operator log files into a local case."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from chainlog_ai.builder import detect_builder_client, normalize_builder_client
from chainlog_ai.case import Event, append_events, open_case, save_case, validate_case_id
from chainlog_ai.consensus import (
    consensus_fields,
    detect_consensus_client,
    normalize_consensus_client,
    parse_consensus_time,
)
from chainlog_ai.execution import (
    detect_execution_client,
    normalize_execution_client,
    parse_execution_time,
)
from chainlog_ai.redact import redact_excerpt
from chainlog_ai.validator import detect_validator_client, normalize_validator_client

SOURCES = ("execution", "consensus", "validator", "builder", "kubernetes")


class InputError(Exception):
    """An input file could not be read."""


def ingest(inputs: list[tuple[str, ...]], case_id: str | None = None) -> str:
    """Read ``inputs`` and write them to a case. Return the case id."""

    if case_id is not None:
        validate_case_id(case_id)
    events: list[Event] = []
    for item in inputs:
        source, raw_path, client = _input(item)
        if source not in SOURCES:
            raise InputError(f"unknown source: {source}")
        events.extend(read_file(Path(raw_path), source, client=client))
    case = open_case(case_id)
    append_events(case, events)
    save_case(case)
    return case.id


def read_file(path: Path, source: str, client: str | None = None) -> list[Event]:
    file_path = path.expanduser()
    if not file_path.is_file():
        raise InputError(f"cannot read {path}: not a file")
    try:
        data = file_path.read_bytes()
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc.strerror}") from exc
    records = _records(data)
    named = _named_client(source, client, records)
    now = datetime.now(timezone.utc)
    stored_path = str(file_path.resolve())
    events: list[Event] = []
    for start, end, excerpt in records:
        when, slot, epoch, block = _line_fields(source, excerpt, now)
        events.append(
            Event(
                source=source,
                client=named,
                path=stored_path,
                byte_start=start,
                byte_end=end,
                excerpt=redact_excerpt(excerpt),
                time=when,
                slot=slot,
                epoch=epoch,
                block=block,
            )
        )
    return events


def _input(item: tuple[str, ...]) -> tuple[str, str, str | None]:
    source, raw_path = item[0], item[1]
    client = item[2] if len(item) > 2 else None
    return source, raw_path, client if isinstance(client, str) else None


def _named_client(
    source: str,
    client: str | None,
    records: list[tuple[int, int, str]],
) -> str | None:
    text = "\n".join(excerpt for _, _, excerpt in records)
    if source == "execution":
        if client is not None:
            return normalize_execution_client(client)
        return detect_execution_client(text)
    if source == "consensus":
        if client is not None:
            return normalize_consensus_client(client)
        return detect_consensus_client(text)
    if source == "validator":
        if client is not None:
            return normalize_validator_client(client)
        return detect_validator_client(text)
    if source == "builder":
        if client is not None:
            return normalize_builder_client(client)
        return detect_builder_client(text)
    return None


def _line_fields(
    source: str,
    excerpt: str,
    now: datetime,
) -> tuple[str | None, int | None, int | None, str | None]:
    if source == "execution":
        return parse_execution_time(excerpt, now=now), None, None, None
    if source == "consensus":
        slot, epoch, block = consensus_fields(excerpt)
        return parse_consensus_time(excerpt, now=now), slot, epoch, block
    if source in {"validator", "builder"}:
        return parse_consensus_time(excerpt, now=now), None, None, None
    return None, None, None, None


def _records(data: bytes) -> list[tuple[int, int, str]]:
    text = _decode_utf8(data)
    if text is not None:
        events = kubernetes_events(text)
        if events is not None:
            return [
                (*_byte_span(text, start, end), _event_excerpt(event))
                for event, start, end in events
            ]
    return _line_records(data)


def _decode_utf8(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _line_records(data: bytes) -> list[tuple[int, int, str]]:
    records: list[tuple[int, int, str]] = []
    start = 0
    for raw in data.splitlines(keepends=True):
        content = raw.rstrip(b"\r\n")
        end = start + len(content)
        if content.strip():
            records.append((start, end, content.decode("utf-8", errors="replace")))
        start += len(raw)
    return records


def _byte_span(text: str, start: int, end: int) -> tuple[int, int]:
    prefix = len(text[:start].encode("utf-8"))
    size = len(text[start:end].encode("utf-8"))
    return prefix, prefix + size


def _event_excerpt(event: dict[str, object]) -> str:
    reason = event.get("reason")
    message = event.get("message")
    if message is None:
        message = event.get("note")
    reason_text = reason if isinstance(reason, str) else ""
    message_text = message if isinstance(message, str) else ""
    if reason_text and message_text:
        return f"{reason_text}: {message_text}"
    if message_text or reason_text:
        return message_text or reason_text
    return json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def kubernetes_events(text: str) -> list[tuple[dict[str, object], int, int]] | None:
    """Return Kubernetes events and the character span of each object.

    ``None`` means this text is not a Kubernetes events document.
    An empty list means the document was an events list with no events.
    """

    index = _skip_ws(text, 0)
    if index >= len(text) or text[index] not in "{[":
        return None
    decoder = json.JSONDecoder()
    try:
        if text[index] == "[":
            items, end = _parse_array(text, index, decoder)
            if _skip_ws(text, end) != len(text):
                return None
            if items and all(_is_event(value) for value, _, _ in items):
                return [(value, start, stop) for value, start, stop in items]
            return None
        fields, item_spans, start, end = _parse_object(text, index, decoder)
        if _skip_ws(text, end) != len(text):
            return None
    except (ValueError, json.JSONDecodeError, IndexError):
        return None
    if fields.get("kind") == "EventList":
        if item_spans is None:
            return None
        return [(value, start, stop) for value, start, stop in item_spans if isinstance(value, dict)]
    if item_spans and all(_is_event(value) for value, _, _ in item_spans):
        return [(value, start, stop) for value, start, stop in item_spans]
    if _is_event(fields):
        return [(fields, start, end)]
    return None


def _is_event(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("kind") == "Event":
        return True
    message = value.get("message", value.get("note"))
    reason = value.get("reason")
    involved = value.get("involvedObject", value.get("regarding"))
    return involved is not None and (isinstance(message, str) or isinstance(reason, str))


def _skip_ws(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _parse_array(
    text: str, index: int, decoder: json.JSONDecoder
) -> tuple[list[tuple[dict[str, object], int, int]], int]:
    if text[index] != "[":
        raise ValueError("expected array")
    index += 1
    items: list[tuple[dict[str, object], int, int]] = []
    while True:
        index = _skip_ws(text, index)
        if index < len(text) and text[index] == "]":
            return items, index + 1
        start = index
        value, index = decoder.raw_decode(text, index)
        if isinstance(value, dict):
            items.append((value, start, index))
        else:
            raise ValueError("event item must be an object")
        index = _skip_ws(text, index)
        if index < len(text) and text[index] == ",":
            index += 1
            continue
        if index < len(text) and text[index] == "]":
            return items, index + 1
        raise ValueError("expected comma or end of array")


def _parse_object(
    text: str, index: int, decoder: json.JSONDecoder
) -> tuple[dict[str, object], list[tuple[dict[str, object], int, int]] | None, int, int]:
    if text[index] != "{":
        raise ValueError("expected object")
    start = index
    index += 1
    fields: dict[str, object] = {}
    item_spans: list[tuple[dict[str, object], int, int]] | None = None
    while True:
        index = _skip_ws(text, index)
        if index < len(text) and text[index] == "}":
            return fields, item_spans, start, index + 1
        key, index = decoder.raw_decode(text, index)
        if not isinstance(key, str):
            raise ValueError("object key must be a string")
        index = _skip_ws(text, index)
        if index >= len(text) or text[index] != ":":
            raise ValueError("expected colon")
        index = _skip_ws(text, index + 1)
        if key == "items" and index < len(text) and text[index] == "[":
            item_spans, index = _parse_array(text, index, decoder)
            fields["items"] = [value for value, _, _ in item_spans]
        else:
            fields[key], index = decoder.raw_decode(text, index)
        index = _skip_ws(text, index)
        if index < len(text) and text[index] == ",":
            index += 1
            continue
        if index < len(text) and text[index] == "}":
            return fields, item_spans, start, index + 1
        raise ValueError("expected comma or end of object")
