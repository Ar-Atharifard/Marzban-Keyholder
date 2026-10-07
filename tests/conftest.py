from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from keyholder.config import Settings
from keyholder.main import create_app
from keyholder.models import Backend, Base

ADMIN_KEY = "test-admin-" + "a" * 48
UUID = "12345678-1234-4234-9234-123456789abc"
LINK = f"vless://{UUID}@cdn.example:443?type=xhttp&security=tls&sni=cdn.example&host=cdn.example&path=%2Fx&extra=malformed&flow=xtls-rprx-vision#CDN"


class FakeBackend:
    async def configurations(self, username: str) -> list[str]:
        return [LINK]


@pytest.fixture
def client(tmp_path: object) -> Iterator[TestClient]:
    settings = Settings(
        admin_key=SecretStr(ADMIN_KEY), database_url=f"sqlite:///{tmp_path}/test.db"
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with app.state.sessions() as db:
        db.add(Backend(id="marzban-default", provider="marzban", config_ref="default"))
        db.commit()
    with TestClient(app) as client:
        app.state.backends = {"marzban-default": FakeBackend()}
        yield client
