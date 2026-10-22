import base64
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from keyholder.config import Settings
from keyholder.main import create_app
from keyholder.models import Backend, Base
from tests.support import ADMIN_KEY, FakeBackend


@pytest.fixture
def client(tmp_path: object) -> Iterator[TestClient]:
    settings = Settings(
        admin_key=SecretStr(ADMIN_KEY),
        token_encryption_key=SecretStr(base64.urlsafe_b64encode(b"x" * 32).decode()),
        database_url=f"sqlite:///{tmp_path}/test.db",
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with app.state.sessions() as db:
        db.add(Backend(id="marzban-default", provider="marzban", config_ref="default"))
        db.commit()
    with TestClient(app) as client:
        app.state.backends = {"marzban-default": FakeBackend()}
        yield client


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mocked tests must never inherit deployment credentials or configuration.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for key in os.environ:
        if key.startswith("KEYHOLDER_"):
            monkeypatch.delenv(key)
