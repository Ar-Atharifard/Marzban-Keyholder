import copy
from typing import Any

import pytest
from pydantic import SecretStr

from keyholder import cli
from keyholder.config import Settings
from keyholder.inbounds import profile_label, profile_summary
from keyholder.rendering.inbound_preview import host_profiles
from scripts import management_bot
from scripts.admin import worker


@pytest.fixture
def settings() -> Settings:
    return Settings(
        admin_key=SecretStr("a" * 40),
        allowed_cdn_hosts=("cdn.example",),
        cdn_ech_config="cloudflare-ech.com+https://1.1.1.1/dns-query",
        cdn_tls_compatibility=True,
        cdn_ech_kinds=("grpc_cdn",),
        cdn_ech_full_catalog=("marzban-default/OWNER",),
        fragmentation_accounts=("marzban-default/OWNER",),
    )


@pytest.mark.parametrize(
    "protocol,network,security,address,expected",
    [
        ("vless", "tcp", "reality", "{SERVER_IP}", ["Base", "Base | FRAG"]),
        ("vless", "tcp", "reality", "[2001:db8::1]", ["Base"]),
        ("vless", "grpc", "reality", "gate.example", ["Base"]),
        ("vless", "xhttp", "reality", "gate.example", ["Base"]),
        ("vless", "grpc", "tls", "cdn.example", ["Base", "Base | ECH FALLBACK", "Base | FRAG"]),
        ("vless", "xhttp", "tls", "cdn.example", ["Base", "Base | ECH FALLBACK"]),
        ("trojan", "grpc", "tls", "cdn.example", ["Base", "Base | ECH FALLBACK"]),
        ("trojan", "xhttp", "tls", "cdn.example", ["Base", "Base | ECH FALLBACK"]),
        ("trojan", "tcp", "reality", "[2001:db8::1]", ["Base"]),
        ("vmess", "httpupgrade", "tls", "cdn.example", ["Base", "Base | ECH FALLBACK"]),
    ],
)
def test_preview_uses_delivery_variants(
    settings: Settings,
    protocol: str,
    network: str,
    security: str,
    address: str,
    expected: list[str],
) -> None:
    assert (
        host_profiles(
            {"protocol": protocol, "network": network, "tls": security},
            {"remark": "Base", "address": address, "sni": "cdn.example"},
            settings,
            "marzban-default/OWNER",
        )
        == expected
    )


def test_default_preview_does_not_inherit_owner_exceptions(settings: Settings) -> None:
    inbound = {"protocol": "vless", "network": "xhttp", "tls": "none"}
    host = {"remark": "Stream", "address": "cdn.example", "security": "tls"}
    assert host_profiles(inbound, host, settings, "marzban-default/") == ["Stream"]
    settings.enabled_profiles = ()
    assert host_profiles(inbound, host, settings, "marzban-default/OWNER") == []


def test_unknown_templates_do_not_report_a_false_total(settings: Settings) -> None:
    host = {"remark": "{DATA_LEFT}", "address": "cdn.example"}
    assert host_profiles({}, host, settings, "marzban-default/alice") is None
    row = {"names": ["Dynamic"], "generated_names": None}
    assert "unavailable" in profile_summary([row])
    assert "unavailable" in profile_label(row)
    assert management_bot.profile_summary([row]) == profile_summary([row])
    assert management_bot.profile_label(row) == profile_label(row)


def test_catalog_counts_hosts_filters_disabled_and_guards_changed_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KEYHOLDER_ADMIN_KEY", "a" * 40)
    monkeypatch.setenv("KEYHOLDER_PROFILE_SOURCE", "upstream")
    monkeypatch.setenv("KEYHOLDER_ALLOWED_CDN_HOSTS", '["cdn.example"]')
    monkeypatch.setenv("KEYHOLDER_CDN_ECH_CONFIG", "cloudflare-ech.com+https://1.1.1.1/dns-query")
    monkeypatch.setenv("KEYHOLDER_CDN_TLS_COMPATIBILITY", "true")
    user = {"username": "alice", "inbounds": {"vless": ["A"]}, "proxies": {"vless": {}}}
    native = {"vless": [{"tag": "A", "network": "grpc", "tls": "none"}]}
    hosts: dict[str, Any] = {
        "A": [
            {"remark": "gRPC", "address": "cdn.example", "security": "tls"},
            {"remark": "hidden", "address": "cdn.example", "security": "tls", "is_disabled": True},
        ]
    }
    first = worker.inbound_catalog(user, native, hosts)
    assert first["entries"][0]["generated_names"] == ["gRPC", "gRPC | ECH FALLBACK"]
    changed = copy.deepcopy(hosts)
    changed["A"][0]["address"] = "other.example"
    assert worker.inbound_catalog(user, native, changed)["revision"] != first["revision"]
    monkeypatch.setenv("KEYHOLDER_CDN_ECH_CONFIG", "")
    assert worker.inbound_catalog(user, native, hosts)["revision"] != first["revision"]


def test_cli_and_bot_show_total_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog = {
        "username": "alice",
        "revision": "v1",
        "entries": [
            {
                "number": 1,
                "tag": "A",
                "protocol": "vless",
                "selected": True,
                "names": ["gRPC"],
                "generated_names": ["gRPC", "gRPC | ECH FALLBACK"],
            }
        ],
    }
    calls: list[Any] = []

    def request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(args[1])
        return {"ok": True, "result": catalog}

    monkeypatch.setattr(cli, "request", request)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["user", "inbounds", "alice", "--select", "1"]) == 1
    output = capsys.readouterr().out
    assert "ECH FALLBACK" in output and "1 inbounds → 2 connection profiles" in output
    assert len(calls) == 1  # No write before confirmation.
    monkeypatch.setattr(management_bot, "dispatch", lambda *args: catalog)
    state: dict[str, Any] = {}
    output = management_bot.command("/inbounds alice", state)
    assert "ECH FALLBACK" in output and "2 connection profiles" in output
    assert "2 connection profiles" in management_bot.command("/select 1", state)


def test_ipv6_host_identity_is_preserved(settings: Settings) -> None:
    inbound = {"protocol": "vless", "network": "xhttp", "tls": "none"}
    host: dict[str, Any] = {
        "remark": "Stream | IPv6",
        "address": "[2a06:98c1:3121::7]",
        "sni": "cdn.example",
        "host": "cdn.example",
        "security": "tls",
    }
    assert host_profiles(inbound, host, settings, "marzban-default/OWNER") == ["Stream | IPv6"]
    host["allowinsecure"] = True
    assert host_profiles(inbound, host, settings, "marzban-default/OWNER") == []


def test_address_scoped_fragmentation_uses_actual_selected_upstream_profile(
    settings: Settings,
) -> None:
    from keyholder.rendering.profiles import normalize
    from tests.conftest import TCP

    profile = normalize(TCP)
    assert profile is not None
    settings.fragmentation_hosts = (profile.address,)
    host = {"remark": profile.name, "address": "{SERVER_IP}"}
    inbound = {"protocol": "vless", "network": "tcp", "tls": "reality"}
    assert host_profiles(inbound, host, settings, "marzban-default/OWNER", profile) == [
        profile.name,
        profile.name + " | FRAG",
    ]
    assert host_profiles(inbound, host, settings, "marzban-default/OWNER") is None
