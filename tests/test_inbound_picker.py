import asyncio
import copy
from typing import Any

import httpx
import pytest

from keyholder import cli
from keyholder.backends.marzban import MarzbanBackend
from keyholder.rendering.profiles import apply_cdn_ech, normalize
from keyholder.rendering.renderers import URIRenderer, XrayRenderer
from scripts import management_bot
from scripts.admin import worker
from tests.support import AVAILABLE, GRPC, PBK
from tests.support import INBOUND_HOSTS as HOSTS


@pytest.fixture(autouse=True)
def operator_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEYHOLDER_ADMIN_KEY", "a" * 40)


USER: dict[str, Any] = {
    "username": "alice",
    "inbounds": {"vless": ["A"], "trojan": ["B"]},
    "proxies": {"vless": {"id": "keep-id"}, "trojan": {"password": "keep-secret"}},
    "data_limit": 123,
    "expire": 456,
}


def test_catalog_has_no_secrets_and_detects_concurrent_selection_change() -> None:
    original = worker.inbound_catalog(USER, AVAILABLE, HOSTS)
    assert "keep-secret" not in str(original) and "keep-id" not in str(original)
    assert [r["number"] for r in original["entries"]] == [1, 2, 3]
    updated = copy.deepcopy(USER)
    updated["inbounds"]["vless"] = ["C"]
    assert worker.inbound_catalog(updated, AVAILABLE, HOSTS)["revision"] != original["revision"]


@pytest.mark.parametrize("choice", [["C"], [], ["unknown"], ["C", "C"], "C"])
def test_picker_preserves_credentials_and_rejects_invalid_choices(
    monkeypatch: pytest.MonkeyPatch, choice: Any
) -> None:
    submitted = []
    monkeypatch.setattr(worker, "default_inbounds", lambda: {"inbound_tags": ["A"]})

    async def login(self: MarzbanBackend) -> None:
        self.token = "test"

    async def request(
        self: MarzbanBackend, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        if path == "/api/inbounds":
            return httpx.Response(200, json=AVAILABLE)
        if path == "/api/hosts":
            return httpx.Response(200, json=HOSTS)
        if method == "GET":
            return httpx.Response(200, json=copy.deepcopy(USER))
        submitted.append(kwargs["json"])
        return httpx.Response(200, json={**USER, **kwargs["json"]})

    monkeypatch.setenv("KEYHOLDER_ADMIN_KEY", "a" * 40)
    monkeypatch.setattr(MarzbanBackend, "login", login)
    monkeypatch.setattr(MarzbanBackend, "request", request)
    catalog = worker.inbound_catalog(USER, AVAILABLE, HOSTS)
    args = {"username": "alice", "selected_tags": choice, "revision": catalog["revision"]}
    if choice != ["C"]:
        with pytest.raises(worker.OperatorError, match="unique"):
            asyncio.run(worker.panel_operation("user-inbounds", args))
        assert submitted == []
        return
    result = asyncio.run(worker.panel_operation("user-inbounds", args))
    assert submitted == [{"inbounds": {"vless": ["C"], "trojan": []}}]
    assert result["data_limit"] == 123 and result["expire"] == 456
    with pytest.raises(worker.OperatorError, match="changed"):
        asyncio.run(worker.panel_operation("user-inbounds", {**args, "revision": "stale"}))
    assert len(submitted) == 1


def test_bot_picker_requires_confirmation_and_cancel_clears_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    catalog = worker.inbound_catalog(USER, AVAILABLE, HOSTS)

    def dispatch(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return catalog if "selected_tags" not in args else {"username": "alice"}

    monkeypatch.setattr(management_bot, "dispatch", dispatch)
    state: dict[str, Any] = {}
    assert "Reply /select" in management_bot.command("/inbounds alice", state)
    prompt = management_bot.command("/select 3", state)
    assert len(calls) == 1
    management_bot.command("/confirm " + prompt.rsplit(" ", 1)[1], state)
    assert calls[-1][1]["selected_tags"] == [catalog["entries"][2]["tag"]]
    assert "picker" not in state
    management_bot.command("/inbounds alice", state)
    management_bot.command("/cancel", state)
    with pytest.raises(ValueError, match="expired"):
        management_bot.command("/select 1", state)


def test_cli_selection_requires_confirmation_without_a_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = worker.inbound_catalog(USER, AVAILABLE, HOSTS)
    calls = []

    def request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(args[1])
        return {"ok": True, "result": catalog}

    monkeypatch.setattr(cli, "request", request)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["user", "inbounds", "alice", "--select", "1,2"]) == 1
    assert len(calls) == 1
    assert cli.main(["user", "inbounds", "alice", "--select", "1,2", "--confirm"]) == 0
    assert calls[-1]["args"]["selected_tags"] == [r["tag"] for r in catalog["entries"][:2]]


def test_grpc_reality_survives_both_renderers_without_vision_or_extra() -> None:
    link = GRPC.replace("security=tls", "security=reality").replace("pbk=invalid", "pbk=" + PBK)
    profile = normalize(link)
    assert profile is not None and profile.kind == "grpc_reality"
    assert profile.flow == "" and profile.security == "reality"
    assert URIRenderer().render([profile])
    assert "realitySettings" in XrayRenderer().render([profile])


def test_ech_fallback_is_limited_to_configured_families() -> None:
    profile = normalize(GRPC.replace("sni=tls.example", "sni=titan.example"))
    assert profile is not None
    assert len(apply_cdn_ech([profile], "test", ("titan.example",), True, ("grpc_cdn",))) == 2
    assert apply_cdn_ech([profile], "test", ("titan.example",), True, ()) == [profile]


def test_configured_plan_is_used_when_creating_a_user(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    monkeypatch.setenv("KEYHOLDER_ADMIN_KEY", "a" * 40)
    monkeypatch.setenv("KEYHOLDER_DEFAULT_INBOUND_TAGS", json.dumps(["A", "C"]))
    monkeypatch.setattr(worker, "customers", lambda: [])
    monkeypatch.setattr(worker, "api", lambda *args: {"created": True})
    monkeypatch.setattr(worker, "default_inbounds", lambda: {"inbound_tags": ["A", "C"]})
    submitted = []

    async def login(self: MarzbanBackend) -> None:
        self.token = "test"

    async def request(
        self: MarzbanBackend, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        if path == "/api/inbounds":
            return httpx.Response(200, json=AVAILABLE)
        submitted.append(kwargs["json"])
        return httpx.Response(200, json={"username": "alice"})

    monkeypatch.setattr(MarzbanBackend, "login", login)
    monkeypatch.setattr(MarzbanBackend, "request", request)
    args = {"username": "alice", "name": "Alice", "protocols": ["vless"], "quota_gb": 5, "days": 30}
    asyncio.run(worker.panel_operation("user-create", args))
    assert submitted[0]["inbounds"] == {"vless": ["A", "C"]}
    with pytest.raises(worker.OperatorError, match="match --protocols"):
        asyncio.run(worker.panel_operation("user-create", {**args, "protocols": ["trojan"]}))
    assert len(submitted) == 1
