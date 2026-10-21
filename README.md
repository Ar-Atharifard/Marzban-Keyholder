# Keyholder

Keyholder gives customers a stable `/s/{token}` subscription URL while the upstream
account or panel changes. It runs on FastAPI and SQLite with one worker.

Attach an upstream account once, then retrieve the same URL whenever needed.
Tokens have no scheduled expiry. Delivery still depends on account status, quota,
expiry and service availability; administrators can explicitly revoke or rotate a URL.

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
| [Installation](docs/getting-started.md) | Setup, environment and multiple providers |
| [API](docs/api.md) | Endpoints, authentication, schemas and errors |
| [CLI reference](scripts/admin/README.md) | Installation and daily commands |
| [Development](docs/development.md) | Code map, DB, adapters, compatibility and publishing |
| [Operations](docs/operations.md) | Releases, private panel, monitoring and bots |
| [Alerts](docs/alerts.md) | Deduplication, thresholds, suppression and repairs |
| [Recovery](docs/disaster-recovery.md) | Offsite backup, Ansible and VM rehearsal |
| [Networking](docs/networking.md) | Subscription delivery, Worker and DNSTT |
| [Domestic entry](docs/domestic-node.md) | Split routing, reverse tunnel and node recovery |

## Verify a change

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests scripts
git diff --check
```

Tests use synthetic credentials, temporary databases and mocked HTTP. CI also
checks migrations, packaging and secrets; it never deploys.

Multi-worker rate limits, PostgreSQL and automatic failover are unsupported.
`/health` checks the database, not upstream connectivity.

Licensed under [MIT](LICENSE). See [contribution guidance](CONTRIBUTING.md) and
[security reporting](SECURITY.md). Personal deployment notes belong in ignored
`.private/` storage and are excluded from public artifacts.
