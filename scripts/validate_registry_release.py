"""Guarded, isolated production-clone rehearsal; prints no bearer credentials."""

import json
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from keyholder.config import Settings
from keyholder.db import make_database
from keyholder.main import create_app
from keyholder.models import Customer, Registration


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    assert settings.database_url == "sqlite:////data/keyholder.db"
    assert Path("/data/isolated-clone").is_file()
    assert settings.profile_source == "marzban"
    engine, sessions = make_database(settings.database_url)
    with engine.connect() as connection:
        before = connection.execute(
            text("SELECT id,status,token_hash FROM customers ORDER BY id")
        ).all()
    command.upgrade(Config("/app/alembic.ini"), "head")
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT id,status,token_hash FROM customers ORDER BY id")).all()
            == before
        )
        assert connection.execute(text("PRAGMA integrity_check")).all() == [("ok",)]
        assert not connection.execute(text("PRAGMA foreign_key_check")).all()
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0003"
        )
    app = create_app(settings)
    logging.disable(logging.CRITICAL)
    headers = {"Authorization": "Bearer " + settings.admin_key.get_secret_value()}
    with TestClient(app) as client:
        with sessions() as db:
            registrations = list(db.scalars(select(Registration)))
            ids = [(r.customer_id, r.upstream_username) for r in registrations]
        for cid, username in ids:
            rotated = client.post("/admin/customers/" + cid + "/rotate-token", headers=headers)
            assert rotated.status_code == 200
            value = rotated.json()
            repeated = client.post(
                "/admin/customers",
                headers=headers,
                json={"name": username, "upstream_username": username},
            )
            assert repeated.status_code == 201 and repeated.json() == value
            assert (
                client.get("/admin/customers/" + cid + "/subscription", headers=headers).json()
                == value
            )
            for fmt in ["uri", "xray"]:
                response = client.get("/s/" + value["token"] + "?format=" + fmt)
                assert response.status_code == 200
                if fmt == "xray":
                    for config in response.json():
                        stream = config["outbounds"][0].get("streamSettings", {})
                        assert "extra" not in stream.get("xhttpSettings", {})
        with sessions() as db:
            for cid, _ in ids:
                row = db.get(Customer, cid)
                assert row is not None and row.token_encrypted is not None
    engine.dispose()
    print(
        json.dumps(
            {
                "clone_migration": "ok",
                "canonical_registrations": len(ids),
                "encrypted_retrieval": "ok",
                "idempotent_registration": "ok",
                "both_subscription_formats": "ok",
            }
        )
    )


if __name__ == "__main__":
    main()
