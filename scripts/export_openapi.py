"""Generate API schemas offline without environment secrets or database access."""

import argparse
import json
from pathlib import Path

from pydantic import SecretStr

from keyholder.config import Settings
from keyholder.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings(  # type: ignore[call-arg]  # _env_file is a BaseSettings runtime option.
        _env_file=None,
        admin_key=SecretStr("offline-schema-fixture-" + "x" * 32),
        database_url="sqlite:///:memory:",
        public_base_url="https://subscription.example.invalid",
        marzban_url="http://127.0.0.1:8000",
        marzban_token=SecretStr(""),
        marzban_username=SecretStr(""),
        marzban_password=SecretStr(""),
        upstream_timeout=10,
        rate_limit_per_minute=60,
    )
    app = create_app(settings)
    try:
        args.output.write_text(json.dumps(app.openapi(), indent=2) + "\n")
    finally:
        app.state.engine.dispose()


if __name__ == "__main__":
    main()
