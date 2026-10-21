import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from keyholder import cli
from scripts import monitor, tls


def test_cli_uses_resource_action_and_never_accepts_token_in_arguments() -> None:
    args = cli.parser().parse_args(
        ["tls", "configure", "sub.example.org", "--email", "a@example.org"]
    )
    assert args.operation == "tls-configure"
    assert "token" not in vars(args)
    assert cli.parser().parse_args(["tls", "status"]).operation == "tls-status"


def test_private_dns_setup_does_not_put_token_in_service_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tls, "ROOT", tmp_path / "acme")

    calls = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: calls.append(args))
    token = "test_dns_token_" * 4
    result = tls.configure({"domain": "sub.example.org", "email": "a@example.org", "token": token})
    assert result["configured"]
    assert (tls.ROOT / "token").read_text() == token
    assert (tls.ROOT / "token").stat().st_mode & 0o777 == 0o600
    assert token not in json.dumps(calls)
    assert token not in (tls.ROOT / "settings.json").read_text()


@pytest.mark.parametrize(
    "domain,email,token",
    [
        ("bad/domain", "a@example.org", "x" * 40),
        ("sub.example.org", "not-email", "x" * 40),
        ("sub.example.org", "a@example.org", "token\ninvalid"),
    ],
)
def test_invalid_dns_setup_rejected_without_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, domain: Any, email: Any, token: Any
) -> None:
    monkeypatch.setattr(tls, "ROOT", tmp_path / "acme")
    with pytest.raises(ValueError):
        tls.configure({"domain": domain, "email": email, "token": token})
    assert not tls.ROOT.exists()


def test_certificate_pair_restored_when_gateway_validation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, certs = tmp_path / "acme", tmp_path / "certs"
    source = root / "state/certificates"
    source.mkdir(parents=True)
    certs.mkdir()
    (root / "settings.json").write_text(
        json.dumps({"domain": "sub.example.org", "email": "a@example.org"})
    )
    (source / "sub.example.org.crt").write_text("new certificate")
    (source / "sub.example.org.key").write_text("new key")
    (certs / "subscription.crt").write_text("old certificate")
    (certs / "subscription.key").write_text("old key")
    monkeypatch.setattr(tls, "ROOT", root)
    monkeypatch.setattr(tls, "CERTS", certs)

    def run(args: list[str], **kwargs: Any) -> Any:
        if args[0] == "/usr/local/bin/lego":
            assert args[1] == "run"
            assert "--renew-days" in args
            assert "renew" not in args
        if args[-1] == "-t":
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        tls.issue()
    assert (certs / "subscription.crt").read_text() == "old certificate"
    assert (certs / "subscription.key").read_text() == "old key"


@pytest.mark.parametrize(
    "results,expected", [([0, 0], None), ([0, 1], "warning"), ([1], "critical")]
)
def test_certificate_alert_thresholds(
    monkeypatch: pytest.MonkeyPatch, results: Any, expected: Any
) -> None:
    results = iter(results)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kw: subprocess.CompletedProcess(args, next(results)),
    )
    alerts = monitor.certificate_alerts([{"name": "subscription", "path": "private"}])
    assert list(alerts) == ([f"tls:subscription:{expected}"] if expected else [])
    if expected:
        assert monitor.rule_for_key(next(iter(alerts))) == "service.tls"
        assert monitor.severity_for_key(next(iter(alerts))) == expected
