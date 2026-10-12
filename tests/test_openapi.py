import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_offline_schema_export_is_secret_free_and_matches_response_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "schema.json"
    would_be_database = tmp_path / "must-not-be-created.db"
    secret = "fixture-sensitive-value-never-in-schema"
    monkeypatch.setenv("KEYHOLDER_ADMIN_KEY", secret)
    monkeypatch.setenv("KEYHOLDER_MARZBAN_TOKEN", secret)
    monkeypatch.setenv("KEYHOLDER_BACKENDS", "malformed-private-config-" + secret)
    monkeypatch.setenv("KEYHOLDER_DATABASE_URL", f"sqlite:///{would_be_database}")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, str(root / "scripts/export_openapi.py"), "--output", str(output)],
        cwd=root,
        check=True,
        capture_output=True,
        timeout=10,
    )
    raw = output.read_text()
    assert secret not in raw
    assert not would_be_database.exists()
    spec = json.loads(raw)
    paths = spec["paths"]
    subscription = paths["/s/{token}"]["get"]["responses"]
    assert set(subscription["200"]["content"]) == {"text/plain", "application/json"}
    assert subscription["200"]["content"]["application/json"]["schema"]["type"] == "array"
    error_ref = {"$ref": "#/components/schemas/ErrorResponse"}
    assert subscription["422"]["content"]["application/json"]["schema"] == error_ref
    assert "/admin/settings/ech" not in paths
    rotation = paths["/admin/customers/{customer_id}/rotate-token"]["post"]
    assert rotation["security"] == [{"HTTPBearer": []}]
    assert {"401", "404", "409", "422", "429", "500"} <= set(rotation["responses"])
