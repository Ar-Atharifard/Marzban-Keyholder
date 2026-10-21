import os
import subprocess
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

import pytest

from keyholder import cli, personal


def test_masque_is_local_loopback_and_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "aether"
    binary.touch()
    state = tmp_path / "state"
    seen: list[str] = []

    def run(command: list[str], **kwargs: Any) -> CompletedProcess[str]:
        seen.extend(command)
        assert kwargs["cwd"] == state
        assert "AETHER_HTTP_PROXY" not in kwargs["env"]
        assert state.stat().st_mode & 0o777 == 0o700
        previous = os.umask(0o077)
        os.umask(previous)
        assert previous == 0o077
        return CompletedProcess(command, 0)

    monkeypatch.setenv("AETHER_HTTP_PROXY", "0.0.0.0:9999")
    monkeypatch.setattr(subprocess, "run", run)
    assert personal.run_masque(binary, state, 1819, False, False) == 0
    assert seen[seen.index("--bind") + 1] == "127.0.0.1:1819"
    assert "--h2" in seen and "--fragment" in seen and "-4" in seen
    assert "--wg" not in seen and "--http-proxy" not in seen
    seen.clear()
    assert personal.run_masque(binary, state, 1819, True, True) == 0
    assert "-6" in seen and "--no-fragment" in seen


def test_masque_invalid_port_or_missing_binary(tmp_path: Path) -> None:
    binary = tmp_path / "aether"
    with pytest.raises(ValueError, match="verified"):
        personal.run_masque(binary, tmp_path, 1819, False, False)
    binary.touch()
    with pytest.raises(ValueError, match="port"):
        personal.run_masque(binary, tmp_path, 22, False, False)


def test_masque_cli_has_documented_local_command() -> None:
    args = cli.parser().parse_args(["personal", "masque", "--ipv6", "--no-fragment"])
    assert args.operation == "personal-masque" and args.ipv6 and args.no_fragment
