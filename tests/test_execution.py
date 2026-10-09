from datetime import datetime, timezone
from pathlib import Path

import pytest

from chainlog_ai.case import load_case
from chainlog_ai.cli import main
from chainlog_ai.execution import detect_execution_client, parse_execution_time
from tests.test_ingest import case_id_from, run

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    user_home = tmp_path / "user-home"
    user_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: user_home))
    root = tmp_path / "chainlog-home"
    monkeypatch.setenv("CHAINLOG_AI_HOME", str(root))
    return root


def test_banner_sets_the_client_and_the_printed_time(home: Path) -> None:
    root = Path(__file__).parents[1] / "examples"
    expected = {
        "nethermind.log": ("nethermind", "2026-10-08T06:00:00.0012Z"),
        "erigon.log": ("erigon", "10-08T06:00:00.000Z"),
        "besu.log": ("besu", "2026-10-08T06:00:00.100Z"),
        "reth.log": ("reth", "2026-10-08T06:00:00.100000Z"),
    }
    for name, (client, stamp) in expected.items():
        code, stdout, stderr = run("ingest", "--execution", str(root / name))
        assert code == 0, stderr
        events = load_case(case_id_from(stdout)).events
        assert events[0].client == client
        assert events[0].time is not None and events[0].time.endswith(stamp)
        assert all(event.client == client and event.time for event in events)


def test_execution_client_flag_overrides_the_banner(home: Path, tmp_path: Path) -> None:
    path = tmp_path / "node.log"
    path.write_text(
        "INFO [10-08|06:12:00.001] Starting Geth on Ethereum mainnet\n",
        encoding="utf-8",
    )
    code, stdout, stderr = run(
        "ingest",
        "--execution",
        str(path),
        "--execution-client",
        "Erigon",
    )
    assert code == 0, stderr
    event = load_case(case_id_from(stdout)).events[0]
    assert event.client == "erigon"
    assert event.time is not None
    assert event.time.endswith("10-08T06:12:00.001Z")


def test_unrecognized_execution_log_keeps_its_timestamps(home: Path, tmp_path: Path) -> None:
    path = tmp_path / "other.log"
    path.write_text("2026-10-08T06:15:00Z node stalled\nstill a line\n", encoding="utf-8")
    code, stdout, _stderr = run("ingest", "--execution", str(path))
    assert code == 0
    events = load_case(case_id_from(stdout)).events
    assert [(event.client, event.time, event.excerpt) for event in events] == [
        (None, "2026-10-08T06:15:00Z", "2026-10-08T06:15:00Z node stalled"),
        (None, None, "still a line"),
    ]


def test_json_execution_line_uses_its_time_field(home: Path, tmp_path: Path) -> None:
    path = tmp_path / "geth.json"
    path.write_text(
        '{"t":"2026-10-08T06:12:00.123Z","msg":"Starting Geth"}\n',
        encoding="utf-8",
    )
    code, stdout, _stderr = run("ingest", "--execution", str(path))
    assert code == 0
    event = load_case(case_id_from(stdout)).events[0]
    assert event.client == "geth"
    assert event.time == "2026-10-08T06:12:00.123Z"


def test_unknown_execution_client_is_a_usage_error(home: Path, tmp_path: Path) -> None:
    path = tmp_path / "node.log"
    path.write_text("INFO [10-08|06:12:00.001] Starting Geth\n", encoding="utf-8")
    code, _stdout, stderr = run(
        "ingest",
        "--execution",
        str(path),
        "--execution-client",
        "parity",
    )
    assert code == 3
    assert "unknown execution client" in stderr
    code, _stdout, stderr = run("ingest", "--execution-client", "geth")
    assert code == 3
    assert "needs a preceding --execution file" in stderr


def test_parse_examples() -> None:
    assert detect_execution_client("INFO Starting Geth on Ethereum mainnet") == "geth"
    assert (
        parse_execution_time("INFO [12-31|23:59:59.010] late", now=datetime(2026, 1, 1, tzinfo=timezone.utc))
        == "2025-12-31T23:59:59.010Z"
    )
    assert parse_execution_time('{"ts":"2026-10-08T06:12:00.123456789Z"}', now=NOW) == (
        "2026-10-08T06:12:00.123456Z"
    )
