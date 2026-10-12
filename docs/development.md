# Developer quick guide

Start with the [code map](architecture.md). Use Python 3.12+, a local development
branch, synthetic credentials and a disposable SQLite database.

```bash
uv sync --frozen --extra dev --python 3.12
uv run keyholder init-config
mkdir -p data
uv run alembic upgrade head
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests scripts
```

Edit `.env` for development only. Never point development migrations or integration
tests at production. Startup does not migrate tables.

- **API feature:** edit `api/`, add schemas/tests, document authentication/errors,
  and add an operator command when needed.
- **Provider:** implement the small adapter boundary; see `providers.md`.
- **Existing transport:** configure/select it in the provider. No source change
  is needed if its links already normalize to a supported family.
- **New family:** update `profile_types.py`, strict parsing/rendering and regression
  tests. Test installed-core acceptance and authenticated traffic with synthetic
  accounts. Preserve XHTTP `extra` removal and TLS verification.
- **Database change:** create a new Alembic revision and test historical upgrades
  and recovery. Keep historical migrations frozen.

Existing API fields/defaults, token paths and frozen subscription fixtures must
remain compatible. New operations/formats are additive; do not regenerate baseline
fixtures simply to make tests pass. Emit only route templates in logs, never URLs,
credentials or upstream response bodies.

Update public docs with supported behavior and limitations. Keep personal notes,
network diagnostics and deployment records in ignored `.private/` storage.
Before release, run the checks above, an isolated fresh install and source export
validation. Build locally; deployment follows the reviewed operations runbook.
