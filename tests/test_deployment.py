import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import bootstrap_host
from scripts.migrate_peers import address, migrate


def test_bootstrap_rejects_udp_old_ssh_and_invalid_peer() -> None:
    for rule in [
        {"port": 22, "source": "any"},
        {"port": 443, "source": "any", "protocol": "udp"},
        {"port": 443, "source": "not-a-network"},
        {"port": 70000, "source": "any"},
    ]:
        with pytest.raises(ValueError):
            bootstrap_host.validate({"old_port": 22, "rules": [rule]})
    bootstrap_host.validate(
        {
            "old_port": 22,
            "rules": [
                {"port": 443, "source": "any"},
                {"port": 24432, "source": "2001:db8::1/128"},
            ],
        }
    )


def test_ssh_transition_retains_access_then_enforces_keys(tmp_path: Path) -> None:
    (tmp_path / "sshd_config").write_text("Port 22\nInclude /etc/ssh/sshd_config.d/*.conf\n")
    (tmp_path / "sshd_config.d").mkdir()
    cloud = tmp_path / "sshd_config.d/50-cloud-init.conf"
    cloud.write_text("Port 22\nPasswordAuthentication yes\n")
    with patch.object(bootstrap_host, "SSH", tmp_path), patch.object(bootstrap_host, "run") as run:
        bootstrap_host.ssh_config(False, 22)
        assert (tmp_path / "sshd_config").read_text().startswith("Port 22\nPort 2222\n")
        assert "Port 22" not in cloud.read_text()
        bootstrap_host.ssh_config(True, 22)
        text = (tmp_path / "sshd_config").read_text()
        assert text.startswith("Port 2222\nPermitRootLogin no\nPasswordAuthentication no\n")
        assert "AuthenticationMethods publickey\n" in text
        assert run.call_args_list[-2].args == ("/usr/sbin/sshd", "-t")
        assert run.call_args_list[-1].args == ("systemctl", "reload", "ssh")
    cloud.write_text("Match User special\n PasswordAuthentication yes\n")
    with patch.object(bootstrap_host, "SSH", tmp_path), patch.object(bootstrap_host, "run"):
        with pytest.raises(ValueError):
            bootstrap_host.ssh_config(True, 22)


def test_peer_mapping_preserves_keys_and_non_endpoint_fields(tmp_path: Path) -> None:
    etc = tmp_path / "etc"
    forward = etc / "keyholder-forward"
    forward.mkdir(parents=True)
    (forward / "client.json").write_text(
        json.dumps(
            {
                "address": "2001:db8::1",
                "sendThrough": "2001:db8::2",
                "privateKey": "2001:db8::1",
                "serverName": "example.org",
            }
        )
    )
    rathole = etc / "keyholder-rathole"
    rathole.mkdir()
    (rathole / "client.toml").write_text('remote_addr = "192.0.2.1:24430"\ntoken = "192.0.2.1"\n')
    gateway = etc / "haproxy"
    gateway.mkdir()
    (gateway / "haproxy.cfg").write_text("use_backend control if { src 192.0.2.1 }\n")
    mapping = {"192.0.2.1": "192.0.2.3", "2001:db8::1": "2001:db8::3"}
    migrate(tmp_path, mapping, "domestic")
    migrate(tmp_path, mapping, "domestic")  # Repeating a reviewed map is harmless.
    assert json.loads((forward / "client.json").read_text()) == {
        "address": "2001:db8::3",
        "sendThrough": "2001:db8::2",
        "privateKey": "2001:db8::1",
        "serverName": "example.org",
    }
    assert (rathole / "client.toml").read_text() == (
        'remote_addr = "192.0.2.3:24430"\ntoken = "192.0.2.1"\n'
    )
    assert "src 192.0.2.3" in (gateway / "haproxy.cfg").read_text()
    assert address("[2001:db8::1]:24432", mapping) == "[2001:db8::3]:24432"
    with pytest.raises(ValueError):
        migrate(tmp_path, {"192.0.2.1": "2001:db8::1"}, "domestic")


def test_foreign_mapping_updates_node_endpoint_not_user_identity(tmp_path: Path) -> None:
    database = tmp_path / "var/lib/marzban/db.sqlite3"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as db:
        db.executescript(
            "CREATE TABLE nodes(address TEXT); CREATE TABLE users(username TEXT);"
            "INSERT INTO nodes VALUES('192.0.2.1'); INSERT INTO users VALUES('OWNER');"
        )
    migrate(tmp_path, {"192.0.2.1": "192.0.2.2"}, "foreign")
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT address FROM nodes").fetchone() == ("192.0.2.2",)
        assert db.execute("SELECT username FROM users").fetchone() == ("OWNER",)
