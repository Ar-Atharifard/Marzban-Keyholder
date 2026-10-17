# Development and architecture

Keyholder owns customer identity, stable tokens and provider mappings. The panel
owns proxy credentials, quota, expiry, status and inbound selection. With
`PROFILE_SOURCE=upstream`, selecting supported profiles in the panel needs no
Keyholder code change. No duplicate account database or background queue is needed.

```text
/s/{token} → customer/mapping → provider → validate profiles → URI or Xray output
CLI / Telegram management → host dispatcher → explicit panel/local operations
```

## Code map

| Path | Responsibility |
|---|---|
| `src/keyholder/main.py` | App lifecycle, shared HTTP client, sanitized logging |
| `src/keyholder/api/` | Public subscriptions and authenticated administration |
| `src/keyholder/backends/` | Provider adapters, authentication and bounded fetches |
| `src/keyholder/rendering/` | Profile parsing, validation, output and usage display |
| `src/keyholder/profile_types.py` | Supported families and compatibility defaults |
| `src/keyholder/{config,schemas,policies}.py` | Settings, request validation, legacy policy |
| `src/keyholder/{models,db,vault,security}.py` | SQLite, identity and token protection |
| `src/keyholder/cli.py` | Workstation CLI; `scripts/admin/` dispatches on the host |
| `scripts/{management_bot,monitor,recovery}.py` | Optional standalone operational tools |
| `migrations/`, `tests/contracts/` | Ordered DB upgrades and frozen API/output fixtures |
| `deploy/` | Optional deployment examples, services, Ansible and Worker |

Database tables: `customers` stores private name, nullable unique Telegram/phone,
status, token hash/ciphertext and timestamps; `customer_mappings` links identities
to backend/account; `registrations` enforces canonical registration; `backends`
stores nonsecret provider metadata; `application_data` preserves migration archives;
`alembic_version` records the schema. Contact fields never enter subscriptions or
Marzban. Changing a private customer name does not rename the upstream account.

## Work locally

Use Python 3.12+, a development branch, synthetic accounts and a disposable DB:

```sh
uv sync --frozen --extra dev --python 3.12
uv run keyholder config init
mkdir -p data
uv run alembic upgrade head
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests scripts
git diff --check
```

Use a disposable database. Reuse existing validation and keep changes focused;
add abstractions only when they simplify a real requirement.

| Change | Edit and validate |
|---|---|
| API feature | `api/`, schemas, contract tests, API guide and CLI if needed |
| Existing transport | Configure it in the provider; verify both output formats |
| New family | `profile_types.py`, parser/renderers, regression tests and real core/network tests |
| Database | New Alembic revision; test historical upgrades and recovery |
| Provider | Adapter and factory/config registration; mocked provider contract tests |

## Provider boundary

`BackendAdapter.configurations(username)` returns URI links. Disabled/missing
accounts raise `UpstreamUnavailable`; fetch/schema failures raise sanitized
`UpstreamError`. Optional `subscription_details()` returns `SubscriptionData`
with validated usage/status in the same request. Never store customer-specific
metadata in shared adapter state. Reuse pooled HTTP, bounds, deadlines and TLS
verification. Provisioning is separate from read-only subscription delivery.

Marzban supports inventory/provisioning through the CLI. The HTTP adapter accepts
plain/base64 URI exports and validated usage headers; it has no provisioning or
inventory API. Its source must enforce account availability. See [installation](getting-started.md)
for multiple-provider configuration.

## Compatibility and publication

Preserve `/s/{token}`, existing API fields/defaults, historical migrations and frozen
fixtures. Registration/retrieval returns the same token; mapping and panel changes
must not rotate it. Explicit rotation/revocation remains explicit. Preserve XHTTP
`extra` removal, certificate verification and credential redaction. Local revocation
stops delivery, not previously downloaded proxy access: enforce that in the panel.

Run one worker with SQLite. Shared rate limits, replicas, PostgreSQL and billing
are not implemented. `/health` checks the DB, not upstream or ISP reachability.

Public docs describe reusable behavior. Keep real inventories, personal guides,
network tests and credentials in ignored `.private/`; ignored does not mean encrypted.
Never publish private Git history. Export reviewed source into a fresh repository:

```sh
uv run python scripts/export_source.py --output /private/path/keyholder-source.tar.gz
```

The exporter excludes private files/Git metadata but is not a full secret scanner.
Scan export and original history privately with Gitleaks; verify installation,
packaging, migrations, license and author metadata before publishing. CI uses
synthetic data and never deploys production.
