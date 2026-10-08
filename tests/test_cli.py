import subprocess
import sys

from chainlog import __version__


def test_package_version() -> None:
    assert __version__ == "0.1.0"


def test_cli_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "chainlog", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "chainlog 0.1.0"
