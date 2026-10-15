# Keyholder

Keyholder provides stable proxy subscription URLs while the upstream account,
panel or infrastructure can change. It is a small Python/FastAPI service designed
for one worker and SQLite, with no background queue or mandatory Redis service.

Customers keep `/s/{token}`. Administrators attach an upstream account once and
retrieve the same URL later. Tokens have no scheduled expiry; delivery still
respects account status, quota/expiry enforcement by the provider, local revocation,
and service availability. Explicit rotation changes a compromised URL.

## Supported integrations

- **Marzban:** account status and current links from its HTTP API; separate explicit
  CLI operations for provisioning, quota, expiry, usage and inbound selection.
- **HTTP subscriptions:** a trusted server-owned URL template exporting plain or
  base64 URI lines. Read-only; it does not implement panel provisioning or inventory.
- Additional panel APIs require an adapter. No arbitrary panel compatibility is claimed.

Supported configurations are VLESS REALITY TCP/XHTTP, TLS gRPC/WS/XHTTP, IPv6
Shadowsocks AEAD, Trojan TLS gRPC/XHTTP or IPv6 REALITY, and VMess AEAD HTTPUpgrade.
Outputs are base64 URI subscriptions or Xray JSON arrays. Unsupported inputs fail
closed. TLS verification stays enabled, XHTTP `extra` is omitted, and arbitrary
upstream ECH/MUX/mask settings are not imported. Supported families and trusted
CDN hosts/networks are configurable; unfamiliar protocols require parser/tests.

## Start here

Use Python 3.12+ and `uv`:

```bash
uv sync --frozen --extra dev --python 3.12
uv run keyholder config init
```

Edit the private `.env`: set your permanent public URL and upstream credentials.
For a same-host Linux Marzban installation, follow the host-network instructions;
for a remote HTTPS upstream, use the default bridge deployment.

**[Installation and first customer](docs/getting-started.md)** explains migrations,
Docker, TLS routing and operator setup. Do not expose the administrator API publicly.

## Documentation

| Guide | Contents |
|---|---|
| [Configuration](docs/configuration.md) | Environment settings and deployment policy |
| [Providers](docs/providers.md) | Multiple backends, HTTP sources, adding an adapter |
| [API](docs/api.md) | Authentication, request/response contracts and errors |
| [Operator commands](scripts/admin/README.md) | Daily customer and panel management |
| [Architecture](docs/architecture.md) | Code layout, database, ownership and limitations |
| [Development](docs/development.md) | Features, protocols, checks and migrations |
| [Operations](docs/operations.md) | Backups, releases, recovery and panel gateway |
| [Alert policy](docs/alerts.md) | Deduplication, acknowledgement, silence, rules and repairs |
| [Monitoring](docs/monitoring.md) | Lightweight host, service and customer alerts |
| [Compatibility](docs/compatibility.md) | Stable links and change policy |
| [Publishing](docs/publishing.md) | Clean source export and private-history precautions |

## Verify a change

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests scripts
git diff --check
```

Tests use synthetic credentials, temporary databases and mocked HTTP. GitHub CI
runs these checks, fresh migrations, source/wheel packaging and secret scanning.
CI never deploys infrastructure or accesses customer credentials.

This release supports a single API worker and SQLite. Multi-worker rate limits,
PostgreSQL support, automatic failover and additional panel adapters are not
implemented or promised. `/health` checks database connectivity, not upstream health.

Licensed under [MIT](LICENSE). See [contribution guidance](CONTRIBUTING.md) and
[security reporting](SECURITY.md). Personal deployment notes belong in ignored
`.private/` storage and are excluded from public artifacts.
