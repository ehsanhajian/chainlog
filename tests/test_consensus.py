import contextlib
import io
from pathlib import Path

import pytest

from chainlog_ai.case import load_case
from chainlog_ai.cli import main
from chainlog_ai.consensus import consensus_fields


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    user_home = tmp_path / "user-home"
    user_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: user_home))
    root = tmp_path / "chainlog-home"
    monkeypatch.setenv("CHAINLOG_AI_HOME", str(root))
    return root


def run(*argv: str) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue()


def case_id_from(stdout: str) -> str:
    line = stdout.strip().splitlines()[0]
    assert line.startswith("case ")
    return line.removeprefix("case ")


def test_banner_sets_the_client_and_keeps_slot_epoch_block(home: Path) -> None:
    root = Path(__file__).parents[1] / "examples"
    expected = {
        "beacon.log": ("lighthouse", 10274304, 321072, "0xabababababababab"),
        "prysm.log": ("prysm", 10274304, 321072, "0xcdcdcdcdcdcdcdcd"),
        "teku.log": ("teku", 10274304, 321072, "0xefefefefefefefef"),
        "nimbus.log": ("nimbus", 10274304, 321072, None),
        "lodestar.log": ("lodestar", 10274304, 321072, "0x1111111111111111"),
    }
    for name, (client, slot, epoch, block) in expected.items():
        code, stdout, stderr = run("ingest", "--consensus", str(root / name))
        assert code == 0, stderr
        events = load_case(case_id_from(stdout)).events
        assert events[0].client == client
        assert events[0].time is not None and events[0].time.endswith("Z")
        matched = [
            event
            for event in events
            if event.slot == slot and event.epoch == epoch and event.block == block
        ]
        assert matched
        assert any(event.slot is None and event.epoch is None and event.block is None for event in events)


def test_consensus_client_flag_overrides_the_banner(home: Path, tmp_path: Path) -> None:
    path = tmp_path / "beacon.log"
    path.write_text(
        "Oct 08 06:12:00.102 INFO  Lighthouse started  slot: 10274304\n",
        encoding="utf-8",
    )
    code, stdout, stderr = run(
        "ingest",
        "--consensus",
        str(path),
        "--consensus-client",
        "Teku",
    )
    assert code == 0, stderr
    event = load_case(case_id_from(stdout)).events[0]
    assert event.client == "teku"
    assert event.slot == 10274304
    assert event.time is not None and event.time.endswith("10-08T06:12:00.102Z")


def test_line_without_slot_epoch_or_block_is_kept(home: Path, tmp_path: Path) -> None:
    path = tmp_path / "beacon.log"
    path.write_text("Oct 08 06:14:12.000 INFO  Peer count changed  peers: 64\n", encoding="utf-8")
    code, stdout, _stderr = run("ingest", "--consensus", str(path))
    assert code == 0
    event = load_case(case_id_from(stdout)).events[0]
    assert event.client is None
    assert event.slot is None
    assert event.epoch is None
    assert event.block is None
    assert event.excerpt.endswith("peers: 64")


def test_finalized_epoch_is_not_the_epoch() -> None:
    slot, epoch, block = consensus_fields(
        "slot: 10274304, epoch: 321072, finalized_epoch: 321070, block: 0xab"
    )
    assert (slot, epoch, block) == (10274304, 321072, "0xab")


def test_unknown_consensus_client_is_a_usage_error(home: Path, tmp_path: Path) -> None:
    path = tmp_path / "beacon.log"
    path.write_text("INFO Lighthouse started\n", encoding="utf-8")
    code, _stdout, stderr = run(
        "ingest",
        "--consensus",
        str(path),
        "--consensus-client",
        "grandine",
    )
    assert code == 3
    assert "unknown consensus client" in stderr
    code, _stdout, stderr = run("ingest", "--consensus-client", "lighthouse")
    assert code == 3
    assert "needs a preceding --consensus file" in stderr
