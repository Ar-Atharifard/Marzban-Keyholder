# Keyholder developer guide

## Where to work

Edit `/home/alireza/projects/braavos-dev/keyholder` locally. Check `git status`
before making changes. Use synthetic users and a local disposable database.
The VPS `/srv/keyholder` has historical uncommitted changes: do not overwrite it.
Production releases are separate under `/srv/keyholder-releases/<commit>`.

## Code map

| Location | Responsibility |
|---|---|
| `src/keyholder/main.py` | FastAPI factory, shared HTTP client, middleware, safe logs |
| `src/keyholder/api/public.py` | Health and `/s/{token}` subscription delivery |
| `src/keyholder/api/admin.py`, `src/keyholder/api/dependencies.py` | Private management API and authentication |
| `src/keyholder/backends/marzban.py` | Panel login, user status and upstream configuration fetch |
| `src/keyholder/rendering/profiles.py` | Parse upstream links, validate protocols, CDN/ECH rules |
| `src/keyholder/rendering/renderers.py` | Generate URI/base64 and Xray JSON subscriptions |
| `src/keyholder/policies.py`, `src/keyholder/schemas.py` | Supported families, validation and API request/response models |
| `src/keyholder/models.py`, `src/keyholder/db.py`, `src/keyholder/vault.py`, `src/keyholder/security.py` | SQLite schema, sessions, encrypted stable tokens |
| `src/keyholder/config.py`, `.env.example` | Environment settings and nonsecret examples |
| `migrations/versions/` | Explicit Alembic schema upgrades; never run automatically at startup |
| `scripts/admin/{cli,worker,host}.py` | `keyholder` command parsing, panel/API operations, SSH/Docker execution |
| `tests/`, `tests/contracts/` | Regression tests and frozen API/subscription compatibility fixtures |
| `Dockerfile`, `docker-compose.yml` | Container build and development deployment definition |
| `docs/` | API, authority, operations, transports and recovery instructions |

All table paths are relative to the repository root.

## Change and verify

Install Python 3.12 dependencies with `uv sync --frozen --extra dev --python 3.12`.
Use `.env.example` as a development template, never production credentials.
Make one focused change, add tests for changed behavior, then run:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src tests scripts
git diff --check
```

For a development server, follow README's local migration/start commands with a
local database. Update relevant documentation and commit reviewed changes.
Never regenerate frozen compatibility fixtures merely to make failing tests pass.
Keep `/s/{token}`, existing tokens, defaults and existing API fields compatible.

## Features and protocols

For an API feature: update the route, schemas and tests; document authentication,
errors and CLI support. Database changes need a new migration and upgrade tests.

For a transport already supported by the parser: configure its inbound and hosts
in Marzban, plus a gateway route if CDN delivery requires one. Select it in the
panel. Keyholder follows panel selections; no per-user source edit is needed.

For a new protocol family: extend parsing/validation, supported family lists,
renderers where needed, API validation and CLI family lists. Add round-trip,
security and old-contract tests. Validate with the installed Xray core and real
network traffic using synthetic credentials before rollout. Preserve XHTTP
`extra` removal. Use Titan only; direct IPv4 must use REALITY, other direct paths
must use IPv6. Do not promise reliability based only on ping or startup success.

## Maintenance and release

Use `keyholder status`, `doctor`, `users`, `inbounds` and `check USER` for inspection;
`keyholder backup` creates a private recovery set on the VPS. `create USER` is
idempotent; `link USER` retrieves the same URL. Panel quota, expiry and inbound
selections remain authoritative. See `scripts/admin/README.md` for commands.

Build and test immutable images locally. Before deployment, prepare a private
backup, isolated validation, exact image digest, rollback and downtime notes.
Deploy a separate release, changing only the intended components. Validate health,
canonical links, panel selection and actual traffic afterwards. Detailed deployment
and recovery gates are in `docs/OPERATIONS.md`; do not copy secrets or production
DBs locally, use a blind Git pull, or restart all services to deploy one component.
