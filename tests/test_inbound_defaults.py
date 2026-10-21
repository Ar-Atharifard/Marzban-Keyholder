import asyncio
import copy
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from keyholder import cli
from keyholder.backends.marzban import MarzbanBackend
from keyholder.inbounds import select_tags
from scripts import management_bot
from scripts.admin import worker
from tests.test_api import HEADERS, create
from tests.test_inbound_picker import AVAILABLE, HOSTS


@pytest.fixture(autouse=True)
def operator_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEYHOLDER_ADMIN_KEY", "a" * 40)


URL = "/admin/backends/marzban-default/inbound-defaults"


def test_defaults_persist_without_affecting_existing_customer(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    app.state.settings.default_inbound_tags = ("A",)
    result = create(client)
    link = "/s/" + str(result["token"])
    original = client.get(link).content
    customer = result["customer"]
    assert client.get(URL).status_code == 401
    assert client.put(URL, json={"inbound_tags": ["B"]}).status_code == 401
    assert client.get(URL, headers=HEADERS).json()["source"] == "environment"
    response = client.put(URL, headers=HEADERS, json={"inbound_tags": ["B", "C"]})
    assert response.status_code == 200 and response.json()["source"] == "database"
    app.state.settings.default_inbound_tags = ("something-else",)
    assert client.get(URL, headers=HEADERS).json()["inbound_tags"] == ["B", "C"]
    assert client.get(link).content == original
    assert client.get("/admin/customers/" + str(customer["id"]), headers=HEADERS).json() == customer  # type: ignore[index]
    assert client.get(URL.replace("marzban-default", "unknown"), headers=HEADERS).status_code == 404


@pytest.mark.parametrize("tags", [[], ["A", "A"], [""], ["A\n"], [123], ["x" * 201]])
def test_defaults_reject_invalid_input(client: TestClient, tags: Any) -> None:
    assert client.put(URL, headers=HEADERS, json={"inbound_tags": tags}).status_code == 422


@pytest.mark.parametrize(
    "selection,expected",
    [("all", ["B", "A", "C"]), ("default", ["A"]), ("1,3", ["B", "C"]), (" 3, 2 ", ["C", "A"])],
)
def test_selection_grammar(selection: str, expected: list[str]) -> None:
    entries = worker.inbound_catalog(
        {"username": "", "inbounds": {}, "proxies": {}}, AVAILABLE, HOSTS
    )["entries"]
    assert select_tags(entries, selection, ["A"]) == expected


@pytest.mark.parametrize("selection", ["", "0", "99", "1,1", "all,1", "1,", "A"])
def test_invalid_selection(selection: str) -> None:
    with pytest.raises(ValueError):
        select_tags([{"tag": "A"}], selection, ["A"])


@pytest.fixture
def panel(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    submitted: list[dict[str, Any]] = []
    defaults = {"inbound_tags": ["A"], "source": "database"}
    monkeypatch.setenv("KEYHOLDER_ADMIN_KEY", "a" * 40)
    monkeypatch.setattr(worker, "customers", lambda: [])
    monkeypatch.setattr(worker, "default_inbounds", lambda: copy.deepcopy(defaults))

    def api(method: str, path: str, body: Any = None) -> Any:
        if method == "PUT":
            defaults.update(body)
            return copy.deepcopy(defaults)
        return {"created": True}

    async def login(self: MarzbanBackend) -> None:
        self.token = "test"

    async def request(
        self: MarzbanBackend, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        if path == "/api/inbounds":
            return httpx.Response(200, json=AVAILABLE)
        if path == "/api/hosts":
            return httpx.Response(200, json=HOSTS)
        assert method == "POST" and path == "/api/user"
        submitted.append(kwargs["json"])
        return httpx.Response(200, json={"username": "alice"})

    monkeypatch.setattr(worker, "api", api)
    monkeypatch.setattr(MarzbanBackend, "login", login)
    monkeypatch.setattr(MarzbanBackend, "request", request)
    return submitted


@pytest.mark.parametrize(
    "selection,expected",
    [
        (None, {"vless": ["A"]}),
        ("default", {"vless": ["A"]}),
        ("1,3", {"trojan": ["B"], "vless": ["C"]}),
        ("all", {"trojan": ["B"], "vless": ["A", "C"]}),
    ],
)
def test_create_derives_protocols(
    panel: list[dict[str, Any]], selection: str | None, expected: dict[str, list[str]]
) -> None:
    args = {"username": "alice", "name": "Alice", "quota_gb": 5, "days": 30, "inbounds": selection}
    asyncio.run(worker.panel_operation("user-create", args))
    assert panel[0]["inbounds"] == expected
    assert set(panel[0]["proxies"]) == set(expected)
    assert panel[0]["data_limit"] == 5 * 1024**3


def test_default_change_is_confirmed_and_applies_only_to_next_creation(
    panel: list[dict[str, Any]],
) -> None:
    catalog = asyncio.run(worker.panel_operation("user-defaults", {}))
    args = {"selected_tags": ["B", "C"], "revision": catalog["revision"]}
    with pytest.raises(worker.OperatorError, match="confirmation"):
        asyncio.run(worker.panel_operation("user-defaults", args))
    asyncio.run(worker.panel_operation("user-defaults", {**args, "confirmed": True}))
    with pytest.raises(worker.OperatorError, match="changed"):
        asyncio.run(worker.panel_operation("user-defaults", {**args, "confirmed": True}))
    assert panel == []
    asyncio.run(
        worker.panel_operation(
            "user-create", {"username": "alice", "name": "Alice", "quota_gb": 0, "days": 0}
        )
    )
    assert panel[0]["inbounds"] == {"trojan": ["B"], "vless": ["C"]}


@pytest.mark.parametrize("selection", ["99", "1,1", "", "default"])
def test_bad_choices_do_not_create_native_user(
    panel: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, selection: str
) -> None:
    monkeypatch.setattr(worker, "default_inbounds", lambda: {"inbound_tags": ["removed"]})
    with pytest.raises(worker.OperatorError):
        asyncio.run(
            worker.panel_operation(
                "user-create",
                {
                    "username": "alice",
                    "name": "Alice",
                    "quota_gb": 1,
                    "days": 1,
                    "inbounds": selection,
                },
            )
        )
    assert panel == []


def test_cli_listing_defaults_and_creation(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    catalog = worker.inbound_catalog(
        {"username": "", "inbounds": {}, "proxies": {}}, AVAILABLE, HOSTS
    )
    catalog["default_tags"] = ["A"]
    calls = []

    def request(host: str, payload: dict[str, Any], **kwargs: Any) -> Any:
        calls.append(payload)
        return {"result": catalog, "ok": True}

    monkeypatch.setattr(cli, "request", request)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["user", "inbounds"]) == 0
    assert len(calls) == 1
    assert cli.main(["user", "defaults", "--select", "all", "--confirm"]) == 0
    assert calls[-1]["args"]["selected_tags"] == ["B", "A", "C"]
    args = cli.parser().parse_args(
        ["user", "create", "alice", "--quota-gb", "5", "--days", "30", "--inbounds", "1,3"]
    )
    assert args.protocols is None and args.inbounds == "1,3"


def test_bot_lists_same_numbers_and_creates_using_inbounds(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = worker.inbound_catalog(
        {"username": "", "inbounds": {}, "proxies": {}}, AVAILABLE, HOSTS
    )
    calls = []

    def dispatch(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return catalog

    monkeypatch.setattr(management_bot, "dispatch", dispatch)
    assert "1. [ ] B" in management_bot.command("/inbounds", {})
    management_bot.command("/create alice quota=5 days=30 inbounds=1,3", {})
    assert calls[-1][1]["inbounds"] == "1,3" and "protocols" not in calls[-1][1]
