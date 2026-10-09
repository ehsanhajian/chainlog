import json
from pathlib import Path

import pytest

from chainlog_ai.case import load_case
from chainlog_ai.cli import main
from chainlog_ai.ingest import ingest
from chainlog_ai.redact import REDACTED, redact_excerpt

JWT = ".".join(
    [
        "eyJhbGciOiJub25lIn0",
        "eyJpYXQiOjE2OTY3MDAwMDB9",
        "bm9uY2Utbm9uY2Utbm9uY2U",
    ]
)
MNEMONIC = " ".join(["abandon"] * 11 + ["about"])
PRIVATE_KEY = "0x" + "11" * 32
JWT_SECRET = "0x" + "ab" * 32
BLOCK_HASH = "0x" + "cd" * 32
PUBKEY = "0x" + "ef" * 48
PEER_ID = "12D3KooWAbcdefghijkmnopqrstuvwxyz123456789"
API_TOKEN = "k" * 24
PASSWORD = "hunter2"


def test_client_line_jwt_and_mnemonic_are_marked() -> None:
    geth = (
        "WARN [10-08|06:14:01.102] Invalid JWT token"
        f'                       auth="Bearer {JWT}"'
    )
    lighthouse = (
        "Oct 08 06:00:01.220 INFO  Imported keystore"
        f"                        pubkey: {PUBKEY}, mnemonic: {MNEMONIC}"
    )

    redacted_geth = redact_excerpt(geth)
    redacted_lighthouse = redact_excerpt(lighthouse)

    assert JWT not in redacted_geth
    assert redacted_geth.count(REDACTED) == 1
    assert "Invalid JWT token" in redacted_geth
    assert MNEMONIC not in redacted_lighthouse
    assert PUBKEY in redacted_lighthouse
    assert f"mnemonic: {REDACTED}" in redacted_lighthouse


def test_private_key_password_and_api_token_are_marked() -> None:
    line = (
        "ERROR Insecure key"
        f"  privatekey={PRIVATE_KEY} hash={BLOCK_HASH}"
        f" password={PASSWORD} api-key={API_TOKEN} peer={PEER_ID}"
    )
    redacted = redact_excerpt(line)

    assert PRIVATE_KEY not in redacted
    assert PASSWORD not in redacted
    assert API_TOKEN not in redacted
    assert BLOCK_HASH in redacted
    assert PEER_ID in redacted
    assert redacted.count(REDACTED) == 3


def test_quoted_keystore_password_is_marked() -> None:
    line = 'ERROR Failed to decrypt keystore  keystore-password="correct horse battery staple"'
    assert redact_excerpt(line) == (
        f'ERROR Failed to decrypt keystore  keystore-password="{REDACTED}"'
    )


def test_lone_jwt_secret_line_is_marked() -> None:
    assert redact_excerpt(JWT_SECRET) == REDACTED
    assert redact_excerpt(JWT_SECRET[2:]) == REDACTED


def test_pubkey_peer_id_and_ordinary_line_stay() -> None:
    line = f"INFO Peer connected  peer={PEER_ID} pubkey={PUBKEY} hash={BLOCK_HASH}"
    assert redact_excerpt(line) == line
    ordinary = 'INFO [10-08|06:12:00.001] Imported new chain segment               number=21,234,560 err="invalid password"'
    assert redact_excerpt(ordinary) == ordinary
    assert redact_excerpt("abandon " * 11) == "abandon " * 11


def test_redaction_is_stable() -> None:
    line = f"password={PASSWORD} auth=Bearer {JWT}"
    assert redact_excerpt(redact_excerpt(line)) == redact_excerpt(line)


def test_ingest_stores_redacted_excerpts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    user_home = tmp_path / "user-home"
    user_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: user_home))
    monkeypatch.setenv("CHAINLOG_AI_HOME", str(tmp_path / "home"))
    log = tmp_path / "beacon.log"
    log.write_text(
        "\n".join(
            [
                f"WARN [10-08|06:14:01.102] Invalid JWT token auth=Bearer {JWT}",
                f"Oct 08 06:00:01.220 INFO Imported keystore pubkey: {PUBKEY} mnemonic: {MNEMONIC}",
                f"INFO Peer connected peer={PEER_ID} hash={BLOCK_HASH} privatekey={PRIVATE_KEY}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    events = tmp_path / "events.json"
    events.write_text(
        json.dumps(
            {
                "kind": "Event",
                "reason": "Failed",
                "message": f"mount failed password={PASSWORD}",
                "involvedObject": {"kind": "Pod", "name": "geth"},
            }
        ),
        encoding="utf-8",
    )

    case_id = ingest([("consensus", str(log)), ("kubernetes", str(events))])
    stored = (tmp_path / "home" / "cases" / case_id / "case.json").read_text(encoding="utf-8")

    assert JWT not in stored
    assert MNEMONIC not in stored
    assert PRIVATE_KEY not in stored
    assert PASSWORD not in stored
    assert PUBKEY in stored
    assert PEER_ID in stored
    assert BLOCK_HASH in stored
    assert REDACTED in stored
    assert any(event.excerpt == f"Failed: mount failed password={REDACTED}" for event in load_case(case_id).events)

    stdout_and_err = _run_why(case_id)
    assert JWT not in stdout_and_err
    assert MNEMONIC not in stdout_and_err
    assert PRIVATE_KEY not in stdout_and_err
    assert PASSWORD not in stdout_and_err


def _run_why(case_id: str) -> str:
    import contextlib
    import io

    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(["why", "--case", case_id])
    assert code == 1
    return stdout.getvalue() + stderr.getvalue()
