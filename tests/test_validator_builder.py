import contextlib
import io
from pathlib import Path

import pytest

from chainlog_ai.case import load_case
from chainlog_ai.cli import main


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


def test_banner_names_the_validator_and_builder_client(home: Path) -> None:
    root = Path(__file__).parents[1] / "examples"
    expected = {
        "validator.log": ("validator", "lighthouse"),
        "prysm-validator.log": ("validator", "prysm"),
        "teku-validator.log": ("validator", "teku"),
        "nimbus-validator.log": ("validator", "nimbus"),
        "lodestar-validator.log": ("validator", "lodestar"),
        "web3signer.log": ("validator", "web3signer"),
        "mev-boost.log": ("builder", "mev-boost"),
    }
    for name, (source, client) in expected.items():
        flag = "--validator" if source == "validator" else "--builder"
        code, stdout, stderr = run("ingest", flag, str(root / name))
        assert code == 0, stderr
        events = load_case(case_id_from(stdout)).events
        assert events
        assert {event.source for event in events} == {source}
        assert {event.client for event in events} == {client}
        assert all(event.time is not None and event.time.endswith("Z") for event in events)


def test_web3signer_signing_and_doppelganger_stay_on_validator(home: Path) -> None:
    root = Path(__file__).parents[1] / "examples" / "web3signer.log"
    code, stdout, stderr = run("ingest", "--validator", str(root))
    assert code == 0, stderr
    events = load_case(case_id_from(stdout)).events
    excerpts = [event.excerpt for event in events]
    assert any("Failed to sign" in excerpt for excerpt in excerpts)
    assert any("Doppelganger" in excerpt for excerpt in excerpts)
    assert all(event.source == "validator" and event.client == "web3signer" for event in events)


def test_relay_and_builder_timeouts_stay_on_builder(home: Path) -> None:
    root = Path(__file__).parents[1] / "examples" / "mev-boost.log"
    code, stdout, stderr = run("ingest", "--builder", str(root))
    assert code == 0, stderr
    events = load_case(case_id_from(stdout)).events
    relay = [event for event in events if "relay" in event.excerpt]
    timeout = [event for event in events if "builder timeout" in event.excerpt]
    assert relay and timeout
    assert all(event.source == "builder" and event.client == "mev-boost" for event in relay + timeout)


def test_client_flag_overrides_the_banner(home: Path, tmp_path: Path) -> None:
    path = tmp_path / "validator.log"
    path.write_text(
        "Oct 08 06:12:00.180 INFO  Lighthouse validator client started\n",
        encoding="utf-8",
    )
    code, stdout, stderr = run(
        "ingest",
        "--validator",
        str(path),
        "--validator-client",
        "Prysm",
    )
    assert code == 0, stderr
    event = load_case(case_id_from(stdout)).events[0]
    assert event.client == "prysm"
    assert event.time is not None and event.time.endswith("10-08T06:12:00.180Z")

    builder = tmp_path / "boost.log"
    builder.write_text(
        'time="2026-10-08T06:14:01Z" level=warning msg="Starting MEV-Boost"\n',
        encoding="utf-8",
    )
    code, stdout, stderr = run(
        "ingest",
        "--builder",
        str(builder),
        "--builder-client",
        "mevboost",
    )
    assert code == 0, stderr
    assert load_case(case_id_from(stdout)).events[0].client == "mev-boost"


def test_line_without_a_banner_is_still_ingested(home: Path, tmp_path: Path) -> None:
    path = tmp_path / "validator.log"
    path.write_text("published attestation\n", encoding="utf-8")
    code, stdout, _stderr = run("ingest", "--validator", str(path))
    assert code == 0
    event = load_case(case_id_from(stdout)).events[0]
    assert event.source == "validator"
    assert event.client is None
    assert event.excerpt == "published attestation"


def test_unknown_client_is_a_usage_error(home: Path, tmp_path: Path) -> None:
    path = tmp_path / "validator.log"
    path.write_text("INFO Lighthouse validator client started\n", encoding="utf-8")
    code, _stdout, stderr = run(
        "ingest",
        "--validator",
        str(path),
        "--validator-client",
        "grandine",
    )
    assert code == 3
    assert "unknown validator client" in stderr
    code, _stdout, stderr = run("ingest", "--validator-client", "lighthouse")
    assert code == 3
    assert "needs a preceding --validator file" in stderr

    code, _stdout, stderr = run("ingest", "--builder-client", "mev-boost")
    assert code == 3
    assert "needs a preceding --builder file" in stderr
