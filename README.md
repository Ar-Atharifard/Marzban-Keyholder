# Keyholder

Keyholder gives customers a stable `/s/{token}` subscription URL while the upstream
account or panel changes. It runs on FastAPI and SQLite with one worker.

Attach an upstream account once, then retrieve the same URL whenever needed.
Tokens have no scheduled expiry. Delivery still depends on account status, quota,
expiry and service availability; administrators can explicitly revoke or rotate a URL.

The backend lives in `src/keyholder/`; `migrations/` holds its database history.
`scripts/` and `deploy/` contain optional administration, monitoring and recovery
tools. You can run the backend without installing those tools or a domestic node.

Keyholder was developed with substantial direct assistance from **OpenAI Codex**
in implementation, testing, documentation and infrastructure tooling. Human
maintainers remain responsible for reviewing changes and deciding what ships.

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

## Deployment portability

Application settings, provider URLs, domains and credentials come from configuration;
no personal inventory or secrets are required from the maintainer. SQLite is the
supported application database. Object storage holds encrypted backup archives,
not the live application database.

The optional two-command recovery workflow targets the documented Ubuntu 22.04
Marzban/two-server topology and an existing compatible backup. It is not an installer
for arbitrary panels, operating systems or tunnel stacks. Backblaze B2 has a guided
credential setup; other S3-compatible repositories use a private restic environment
prepared on the target. See [deployment scope](deploy/ansible/README.md#portability).

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

## License and acknowledgements

Keyholder is licensed under [MIT](LICENSE). It integrates with
[Marzban](https://github.com/Gozargah/Marzban), developed by Gozargah and its
contributors. Marzban and optional
[Marzban Node](https://github.com/Gozargah/Marzban-node) have their own
[AGPL-3.0 license](https://github.com/Gozargah/Marzban/blob/master/LICENSE).
Keyholder's MIT license does not relicense those projects or other dependencies.
See the [integration and redistribution guidance](docs/development.md#upstream-licensing).

See [contribution guidance](CONTRIBUTING.md) and [security reporting](SECURITY.md).
Personal deployment notes belong in ignored `.private/` storage and are excluded
from public artifacts.
