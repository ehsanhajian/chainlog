"""Read a Kubernetes events document or a container log."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from chainlog_ai.builder import detect_builder_client
from chainlog_ai.consensus import detect_consensus_client, parse_consensus_time
from chainlog_ai.execution import detect_execution_client, parse_execution_time
from chainlog_ai.validator import detect_validator_client

PREVIOUS_SOURCE = "kubernetes-previous"

_FIELD_PATH = re.compile(r"spec\.(?:initContainers|containers)\{([^}]+)\}")
_CRI = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})) "
    r"(?:stdout|stderr) [FP] (?P<msg>.*)$"
)
_TIME_KEYS = ("lastTimestamp", "eventTime", "firstTimestamp")
_DETECTORS = (
    detect_execution_client,
    detect_consensus_client,
    detect_validator_client,
    detect_builder_client,
)


def pod_log_path(path: Path) -> dict[str, object] | None:
    """Read namespace, pod, container, and restart from a kubelet log path.

    The kubelet writes ``<namespace>_<pod>_<uid>/<container>/<restart>.log``.
    """

    if path.suffix != ".log" or not path.stem.isdigit():
        return None
    container = path.parent.name
    parts = path.parent.parent.name.split("_")
    if len(parts) < 3 or not container:
        return None
    namespace, pod, uid = parts[0], "_".join(parts[1:-1]), parts[-1]
    if not namespace or not pod or not uid:
        return None
    return {
        "namespace": namespace,
        "pod": pod,
        "container": container,
        "restart": int(path.stem),
    }


def event_place(event: dict[str, object]) -> tuple[str | None, str | None, str | None, str | None]:
    """Return pod, container, namespace, and reason from one Kubernetes event."""

    involved = event.get("involvedObject", event.get("regarding"))
    if not isinstance(involved, dict):
        involved = {}
    kind = _text(involved.get("kind"))
    name = _text(involved.get("name"))
    pod = name if kind in {None, "Pod"} else None
    namespace = _text(involved.get("namespace"))
    if namespace is None:
        metadata = event.get("metadata")
        if isinstance(metadata, dict):
            namespace = _text(metadata.get("namespace"))
    container = None
    field_path = involved.get("fieldPath")
    if isinstance(field_path, str):
        found = _FIELD_PATH.search(field_path)
        if found is not None:
            container = found.group(1)
    return pod, container, namespace, _text(event.get("reason"))


def event_time(event: dict[str, object], *, now: datetime) -> str | None:
    """Return the timestamp on a Kubernetes event, as UTC with a ``Z`` suffix."""

    for key in _TIME_KEYS:
        stamp = event.get(key)
        if isinstance(stamp, str):
            parsed = parse_execution_time(stamp, now=now)
            if parsed is not None:
                return parsed
    metadata = event.get("metadata")
    if isinstance(metadata, dict):
        stamp = metadata.get("creationTimestamp")
        if isinstance(stamp, str):
            return parse_execution_time(stamp, now=now)
    return None


def cri_message(line: str) -> tuple[str, int] | None:
    """Return the application message and its character offset in a CRI log line."""

    match = _CRI.match(line)
    if match is None:
        return None
    message = match.group("msg")
    if not message.strip():
        return None
    return message, match.start("msg")


def container_time(line: str, message: str, *, now: datetime) -> str | None:
    """Prefer the time the application printed, then the CRI timestamp."""

    parsed = parse_consensus_time(message, now=now)
    if parsed is not None:
        return parsed
    match = _CRI.match(line)
    if match is None:
        return None
    return parse_execution_time(match.group("time"), now=now)


def application_client(text: str) -> str | None:
    """Return the client named by the first banner in a container log."""

    for line in text.splitlines():
        for detect in _DETECTORS:
            found = detect(line)
            if found is not None:
                return found
    return None


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
