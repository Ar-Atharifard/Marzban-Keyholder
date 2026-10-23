from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from keyholder.config import Settings
from keyholder.main import create_app
from tests.support import ADMIN_KEY


def test_file_settings_control_sqlite_wait_and_rate_limit_capacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.env"
    path.write_text(
        "KEYHOLDER_SQLITE_BUSY_TIMEOUT=12.5\nKEYHOLDER_RATE_LIMIT_MAX_KEYS=2\n"
        "KEYHOLDER_RATE_LIMIT_PER_MINUTE=1\n"
    )
    monkeypatch.setitem(Settings.model_config, "env_file", str(path))
    settings = Settings(
        admin_key=SecretStr(ADMIN_KEY),
        database_url="sqlite:///" + str(tmp_path / "test.db"),
    )
    app = create_app(settings)
    try:
        with app.state.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 12500
        limiter = app.state.limiter
        assert limiter.allow("first") and not limiter.allow("first")
        assert limiter.allow("second") and limiter.allow("third")
        assert limiter.allow("first")  # Two-key capacity evicts the oldest bucket.
    finally:
        app.state.engine.dispose()


def test_inconsistent_connection_pool_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Keepalive"):
        Settings(
            admin_key=SecretStr(ADMIN_KEY),
            upstream_max_connections=2,
            upstream_max_keepalive_connections=3,
        )
