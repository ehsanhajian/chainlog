import json
import os
import threading
import time
from pathlib import Path

import pytest

from chainlog_ai.case import load_case
from chainlog_ai.cli import main
from chainlog_ai.ingest import ingest


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    user_home = tmp_path / "user-home"
    user_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: user_home))
    root = tmp_path / "chainlog-home"
    monkeypatch.setenv("CHAINLOG_AI_HOME", str(root))
    return root


def test_later_ingest_continues_from_the_stored_offset(home: Path, tmp_path: Path) -> None:
    execution = tmp_path / "geth.log"
    consensus = tmp_path / "beacon.log"
    execution.write_text("INFO Starting Geth\n", encoding="utf-8")
    consensus.write_text("INFO Lighthouse started\n", encoding="utf-8")
    ingest(
        [("execution", str(execution)), ("consensus", str(consensus))],
        case_id="grow",
    )
    case = load_case("grow")
    execution_key = str(execution.resolve())
    consensus_key = str(consensus.resolve())
    assert case.files[execution_key].offset == execution.stat().st_size
    assert case.files[consensus_key].offset == consensus.stat().st_size
    assert case.files[execution_key].offset != case.files[consensus_key].offset
    saved = case.files[execution_key].offset

    with execution.open("a", encoding="utf-8") as handle:
        handle.write("imported new chain segment\n")
    ingest([("execution", str(execution))], case_id="grow")
    case = load_case("grow")
    assert [event.excerpt for event in case.events] == [
        "INFO Starting Geth",
        "INFO Lighthouse started",
        "imported new chain segment",
    ]
    assert case.events[-1].byte_start == saved
    assert case.files[execution_key].offset == execution.stat().st_size


def test_follow_reads_new_lines_until_stopped(home: Path, tmp_path: Path) -> None:
    path = tmp_path / "geth.log"
    path.write_text("INFO Starting Geth\n", encoding="utf-8")
    stop = threading.Event()
    errors: list[BaseException] = []
    printed: list[str] = []

    def run() -> None:
        try:
            ingest(
                [("execution", str(path))],
                case_id="followcase",
                follow=True,
                should_stop=stop.is_set,
                pause=0.01,
                on_events=lambda events: printed.extend(event.excerpt for event in events),
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        _wait(lambda: len(load_case("followcase").events) == 1)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("imported new chain segment\n")
        _wait(lambda: len(load_case("followcase").events) == 2)
    finally:
        stop.set()
        thread.join(timeout=2)
    assert errors == []
    assert not thread.is_alive()
    assert [event.excerpt for event in load_case("followcase").events] == [
        "INFO Starting Geth",
        "imported new chain segment",
    ]
    assert printed == [
        "INFO Starting Geth",
        "imported new chain segment",
    ]


def test_follow_waits_for_a_partial_line(home: Path, tmp_path: Path) -> None:
    path = tmp_path / "geth.log"
    path.write_text("INFO Starting Geth", encoding="utf-8")
    stop = threading.Event()

    def run() -> None:
        ingest(
            [("execution", str(path))],
            case_id="partial",
            follow=True,
            should_stop=stop.is_set,
            pause=0.01,
        )

    thread = threading.Thread(target=run)
    thread.start()
    try:
        _wait(lambda: str(path.resolve()) in load_case("partial").files)
        assert load_case("partial").events == []
        path.write_text("INFO Starting Geth\nimported new chain segment\n", encoding="utf-8")
        _wait(lambda: len(load_case("partial").events) == 2)
    finally:
        stop.set()
        thread.join(timeout=2)
    assert [event.excerpt for event in load_case("partial").events] == [
        "INFO Starting Geth",
        "imported new chain segment",
    ]


def test_replaced_file_starts_over_and_notes_the_rotation(home: Path, tmp_path: Path) -> None:
    path = tmp_path / "geth.log"
    path.write_text("INFO Starting Geth\n", encoding="utf-8")
    ingest([("execution", str(path))], case_id="rotated")
    previous = path.stat().st_ino
    replacement = tmp_path / "replacement.log"
    replacement.write_text("after rotation\n", encoding="utf-8")
    os.replace(replacement, path)
    assert path.stat().st_ino != previous

    ingest([("execution", str(path))], case_id="rotated")
    case = load_case("rotated")
    assert [event.excerpt for event in case.events] == ["INFO Starting Geth", "after rotation"]
    assert [event.generation for event in case.events] == [0, 1]
    cursor = case.files[str(path.resolve())]
    assert cursor.inode == path.stat().st_ino
    assert cursor.generation == 1
    assert cursor.offset == path.stat().st_size
    assert len(cursor.rotations) == 1
    assert cursor.rotations[0].inode == previous
    assert cursor.rotations[0].time.endswith("Z")


def test_case_without_a_stored_offset_still_loads(home: Path) -> None:
    case_id = "oldcase"
    directory = home / "cases" / case_id
    directory.mkdir(parents=True)
    (directory / "case.json").write_text(
        json.dumps(
            {
                "id": case_id,
                "events": [
                    {
                        "source": "execution",
                        "client": None,
                        "path": "/tmp/geth.log",
                        "byte_start": 0,
                        "byte_end": 4,
                        "excerpt": "line",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    case = load_case(case_id)
    assert case.files == {}
    assert case.events[0].generation == 0
    assert case.events[0].excerpt == "line"


def test_follow_flag_prints_the_case_id(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "geth.log"
    path.write_text("INFO Starting Geth\n", encoding="utf-8")
    seen: dict[str, bool] = {}

    def fake_ingest(
        inputs: list[tuple[str, ...]],
        case_id: str | None = None,
        follow: bool = False,
        on_ready=None,
        on_events=None,
        **_kwargs: object,
    ) -> str:
        seen["follow"] = follow
        if on_ready is not None:
            on_ready("followcase")
        if on_events is not None:
            on_events([type("Line", (), {"excerpt": "imported new chain segment"})()])
        return "followcase"

    monkeypatch.setattr("chainlog_ai.cli.ingest", fake_ingest)
    import contextlib
    import io

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(["ingest", "--follow", "--execution", str(path)])
    assert code == 0
    assert seen["follow"] is True
    assert stdout.getvalue() == "case followcase\nimported new chain segment\n"


def _wait(predicate) -> None:
    deadline = time.time() + 2
    while time.time() < deadline:
        try:
            if predicate():
                return
        except Exception:
            pass
        time.sleep(0.01)
    raise AssertionError("timed out")
