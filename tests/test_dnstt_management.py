import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from keyholder import cli
from keyholder.backends.marzban import MarzbanBackend
from scripts.admin import worker
from tests.conftest import ADMIN_KEY, PBK, UUID


@pytest.mark.parametrize("case", ["valid", "disabled", "unselected", "public", "plain", "no-key"])
def test_dnstt_export_follows_panel_and_never_exports_server_key(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    monkeypatch.setenv("KEYHOLDER_ADMIN_KEY", ADMIN_KEY)
    user = {
        "username": "alice",
        "status": "disabled" if case == "disabled" else "active",
        "inbounds": {"vless": [] if case == "unselected" else ["VLESS DNSTT"]},
        "proxies": {"vless": {"id": UUID, "flow": "xtls-rprx-vision"}},
    }
    core = {
        "inbounds": [
            {
                "tag": "VLESS DNSTT",
                "protocol": "vless",
                "listen": "0.0.0.0" if case == "public" else "127.0.0.1",
                "streamSettings": {
                    "security": "none" if case == "plain" else "reality",
                    "realitySettings": {
                        "publicKey": "" if case == "no-key" else PBK,
                        "privateKey": "NEVER-EXPORT-SERVER-KEY",
                        "serverNames": ["target.example"],
                        "shortIds": ["abcd"],
                    },
                },
            }
        ]
    }
    calls = []

    async def login(self: MarzbanBackend) -> None:
        self.token = "synthetic"

    async def request(
        self: MarzbanBackend, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        calls.append((method, path))
        return httpx.Response(200, json=core if path == "/api/core/config" else user)

    monkeypatch.setattr(MarzbanBackend, "login", login)
    monkeypatch.setattr(MarzbanBackend, "request", request)
    args = {
        "username": "alice",
        "dnstt": {
            "inbound_tag": "VLESS DNSTT",
            "domain": "t.example.com",
            "public_key": "a" * 64,
            "doh_url": "https://8.8.8.8/dns-query",
        },
    }
    if case != "valid":
        with pytest.raises(worker.OperatorError):
            asyncio.run(worker.panel_operation("user-dnstt", args))
    else:
        result = asyncio.run(worker.panel_operation("user-dnstt", args))
        assert result["profile_uri"].startswith(f"vless://{UUID}@127.0.0.1:7000?")
        assert "security=reality" in result["profile_uri"]
        assert "flow=xtls-rprx-vision" in result["profile_uri"]
        assert result["transport"]["domain"] == "t.example.com"
        assert "NEVER-EXPORT" not in json.dumps(result)
    assert all(method == "GET" for method, _ in calls)


def test_dnstt_cli_requires_private_file_and_refuses_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["user", "dnstt", "alice"])
    output = tmp_path / "alice.json"
    payload = {"profile_uri": "PRIVATE-USER-CREDENTIAL", "transport": {"domain": "t.example"}}
    monkeypatch.setattr(cli, "request", lambda *a, **kw: {"ok": True, "result": payload})
    assert cli.main(["user", "dnstt", "alice", "--save-link", str(output)]) == 0
    assert json.loads(output.read_text()) == payload
    assert output.stat().st_mode & 0o777 == 0o600
    assert "PRIVATE-USER-CREDENTIAL" not in capsys.readouterr().out
    assert cli.main(["user", "dnstt", "alice", "--save-link", str(output)]) == 1
    assert json.loads(output.read_text()) == payload
