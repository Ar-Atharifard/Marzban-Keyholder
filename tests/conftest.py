import base64
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from keyholder.config import Settings
from keyholder.main import create_app
from keyholder.models import Backend, Base

ADMIN_KEY = "test-admin-" + "a" * 48
UUID = "12345678-1234-4234-9234-123456789abc"
PBK = "A" * 43
LINK = f"vless://{UUID}@192.0.2.1:9443?type=xhttp&security=reality&sni=direct.example&host=direct.example&path=%2Fx&pbk={PBK}&sid=abcd&extra=malformed&flow=xtls-rprx-vision#Direct"


IPV6 = "2001:db8::1"
PASSWORD = "sanitized:+/=@password"
TCP = f"vless://{UUID}@192.0.2.1:8443?type=tcp&security=reality&pbk={PBK}&sid=aB12&sni=direct.example&fp=firefox&flow=xtls-rprx-vision&spx=%2Fhello#IPv4"
TCP6 = TCP.replace("192.0.2.1:8443", f"[{IPV6}]:10443").replace("type=tcp", "type=raw")
GRPC = f"vless://{UUID}@titan.example:443?type=grpc&security=tls&sni=tls.example&serviceName=service%2Fname%3Fx%3D1&authority=grpc.example&mode=multi&alpn=h2%2Chttp%2F1.1&fp=chrome&flow=xtls-rprx-vision&pbk=invalid&ech=ignored#Titan"
SS = (
    "ss://"
    + base64.urlsafe_b64encode(f"aes-128-gcm:{PASSWORD}".encode()).decode().rstrip("=")
    + f"@[{IPV6}]:10444#IPv6%20SS"
)
ALL = [TCP, LINK, GRPC, TCP6, SS]
KINDS = ["tcp_reality", "xhttp_reality", "grpc_cdn", "tcp_reality_ipv6", "shadowsocks_ipv6"]


class FakeBackend:
    async def configurations(self, username: str) -> list[str]:
        return [LINK]


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
