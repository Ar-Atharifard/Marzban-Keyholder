import json
import sys
from pathlib import Path

import pytest

from scripts.render_panel_gate import main, render


def test_private_entry_preserves_native_frontend_routes() -> None:
    prefix = "/manage-" + "a" * 43
    s = render("panel.example", prefix, "127.0.0.1:8000")
    assert "map $cookie_panel_gate $panel_allowed" in s
    assert 'default 0; "' + "a" * 43 + '" 1;' in s
    assert "return 302 /dashboard/;" in s
    assert "Secure; HttpOnly; SameSite=Strict; Max-Age=2592000" in s
    assert s.count("if ($panel_allowed = 0) { return 404; }") == 2
    assert "location = /api/admin/token" in s
    assert "proxy_pass http://127.0.0.1:8000;" in s
    assert "sub_filter '/api/'" not in s
    assert "sub_filter '/statics/'" not in s
    assert "sub_filter_types" not in s
    assert 'Referrer-Policy "no-referrer"' in s
    assert "limit_req zone=panel_login" in s


@pytest.mark.parametrize(
    "host,prefix,upstream",
    [
        ("panel.example; bad", "/manage-" + "a" * 43, "127.0.0.1:8000"),
        ("panel.example", "/short", "127.0.0.1:8000"),
        ("panel.example", "/manage-" + "a" * 43, "external.example:8000"),
    ],
)
def test_gate_rejects_configuration_injection(host: str, prefix: str, upstream: str) -> None:
    with pytest.raises(ValueError):
        render(host, prefix, upstream)


def test_generator_creates_private_files_and_refuses_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "gateway.conf"
    access = tmp_path / "access.json"
    args = [
        "render",
        "--hostname",
        "panel.example",
        "--output",
        str(output),
        "--access-file",
        str(access),
    ]
    monkeypatch.setattr(sys, "argv", args)
    main()
    secret = json.loads(access.read_text())["panel_url"]
    assert secret not in capsys.readouterr().out
    assert output.stat().st_mode & 0o777 == access.stat().st_mode & 0o777 == 0o600
    old = output.read_bytes()
    with pytest.raises(FileExistsError):
        main()
    assert output.read_bytes() == old
