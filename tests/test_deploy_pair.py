import base64
import hashlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from scripts.deploy_pair import inventory, pin_host


def plan(tmp_path: Path) -> dict[str, Any]:
    key = tmp_path / "admin-key"
    key.write_text("private-key-file-must-not-be-copied")
    key.with_name("admin-key.pub").write_text("ssh-ed25519 AAAATEST administrator")
    return {
        "admin_key_file": str(key),
        "subscription_hostname": "sub.example.org",
        "foreign": {
            "ipv4": "192.0.2.10",
            "ipv6": "2001:db8:1::10",
            "previous_ipv4": "192.0.2.11",
            "previous_ipv6": "2001:db8:1::11",
        },
        "domestic": {
            "ipv4": "192.0.2.20",
            "ipv6": "2001:db8:2::20",
            "previous_ipv4": "192.0.2.21",
            "previous_ipv6": "2001:db8:2::21",
        },
    }


def test_single_plan_derives_both_firewalls_and_peer_maps_without_enabling_jobs(
    tmp_path: Path,
) -> None:
    data = inventory(plan(tmp_path), tmp_path / "ssh.config")["all"]
    groups = data["children"]
    foreign = groups["recovery_targets"]["vars"]
    domestic = groups["domestic_targets"]["vars"]
    assert foreign["recovery_environment"] == "production"
    assert not foreign["recovery_activate_jobs"]
    assert not foreign["recovery_old_writers_stopped"]
    assert not domestic["domestic_activate"]
    assert not domestic["domestic_old_node_stopped"]
    assert foreign["recovery_peer_address_map"] == {
        "192.0.2.21": "192.0.2.20",
        "2001:db8:2::21": "2001:db8:2::20",
    }
    assert domestic["domestic_peer_address_map"]["2001:db8:1::11"] == "2001:db8:1::10"
    assert {"port": 24432, "source": "2001:db8:2::20"} in foreign["host_tcp_rules"]
    assert domestic["host_tcp_rules"] == [
        {"port": 443, "source": "any"},
        *[{"port": p, "source": "192.0.2.10"} for p in [62050, 62051, 24430]],
    ]
    assert foreign["host_cloudflare_origin_ports"] == [80, 443, 2053]
    assert domestic["host_cloudflare_origin_ports"] == []
    assert "private-key-file-must-not-be-copied" not in str(data)
    assert foreign["recovery_keep_repository_credentials"]


def test_invalid_target_family_and_shell_injection_are_rejected_before_connection(
    tmp_path: Path,
) -> None:
    good = plan(tmp_path)
    for role, key, value in [
        ("foreign", "ipv6", "192.0.2.10"),
        ("domestic", "ipv4", "192.0.2.10"),
        ("foreign", "ssh_user", "root;command"),
        ("domestic", "ssh_port", 70000),
    ]:
        bad = deepcopy(good)
        bad[role][key] = value
        with pytest.raises(ValueError):
            inventory(bad, tmp_path / "ssh.config")
    good["subscription_hostname"] = "sub.example.org/path"
    with pytest.raises(ValueError):
        inventory(good, tmp_path / "ssh.config")


def test_unverified_host_key_is_never_pinned(tmp_path: Path) -> None:
    key = base64.b64encode(b"example-public-key").decode()
    scanned = f"192.0.2.10 ssh-ed25519 {key}\n"
    known = tmp_path / "known_hosts"
    with (
        patch("scripts.deploy_pair.subprocess.check_output", return_value=scanned),
        patch("scripts.deploy_pair.subprocess.run", return_value=SimpleNamespace(returncode=1)),
        patch("builtins.input", return_value="yes"),
    ):
        with pytest.raises(ValueError, match="not confirmed"):
            pin_host({"ipv4": "192.0.2.10"}, known)
    assert not known.exists()


def test_console_verified_replacement_can_update_a_previous_host_pin(tmp_path: Path) -> None:
    raw = b"example-public-key"
    key = base64.b64encode(raw).decode()
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
    scanned = f"192.0.2.10 ssh-ed25519 {key}\n"
    known = tmp_path / "known_hosts"
    with (
        patch("scripts.deploy_pair.subprocess.check_output", return_value=scanned),
        patch("scripts.deploy_pair.subprocess.run") as run,
        patch("builtins.input", return_value=fingerprint),
    ):
        run.return_value = SimpleNamespace(returncode=0, stdout="192.0.2.10 ssh-ed25519 OLDKEY\n")
        pin_host({"ipv4": "192.0.2.10"}, known)
    assert known.read_text() == scanned
    assert run.call_args_list[-1].args[0][0:2] == ["ssh-keygen", "-R"]
