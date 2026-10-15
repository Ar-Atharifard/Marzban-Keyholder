# Installation

Prerequisites: Python 3.12+, uv, an existing upstream service, and optionally
Docker/Compose 2.24+ with a TLS reverse proxy. Keyholder does not install a panel,
proxy core, DNS provider or certificates.

## Configure

```bash
uv sync --frozen --extra dev --python 3.12
uv run keyholder config init
```

This creates a mode-0600 `.env` with new admin/vault keys, refusing overwrites.
Set `KEYHOLDER_PUBLIC_BASE_URL` to your permanent HTTPS subscription hostname.
Set `KEYHOLDER_MARZBAN_URL` and either its token or username/password. Use HTTPS
for upstreams across untrusted networks. Never commit this file.

Set `KEYHOLDER_ALLOWED_CDN_HOSTS` if restricting CDN delivery. Keep
`KEYHOLDER_PROFILE_SOURCE=upstream` to follow current supported provider selections.
See configuration/providers for multiple panels or HTTP subscription sources.

## Local development

```bash
mkdir -p data
uv run alembic upgrade head
uv run uvicorn keyholder.main:create_app --factory --host 127.0.0.1 \
  --port 18000 --workers 1 --no-access-log --no-proxy-headers
```

Use only a development database and synthetic credentials here. Startup never
creates tables or runs migrations.

## Docker

Default bridge deployment binds the host's published port to loopback. Its
upstream must be reachable from the container; container loopback is not host
loopback. Set a reachable remote HTTPS upstream URL for this deployment.

```bash
docker compose build api
docker compose run --rm --no-deps api /app/.venv/bin/alembic upgrade head
docker compose up -d --no-build api
```

For an existing same-host Linux panel bound to host loopback, use the explicit
host-network override for **every** command:

```bash
docker compose -f docker-compose.yml -f deploy/compose.host.yml build api
docker compose -f docker-compose.yml -f deploy/compose.host.yml run --rm --no-deps api /app/.venv/bin/alembic upgrade head
docker compose -f docker-compose.yml -f deploy/compose.host.yml up -d --no-build api
```

The override keeps Keyholder on host loopback. These migration commands initialize
a new deployment; upgrades of live databases require a backup and migration review.
One-off containers use the same database volume and private environment file.

## HTTPS and operators

Adapt `deploy/nginx.conf.template` for host Nginx. Supply your hostname and certificate
paths. Expose only `/s/`; admin/health stay private. Disable bearer-path logging,
browser challenges and caching for subscriptions. Cloudflare is optional.

Install the SSH dispatcher as described in `scripts/admin/README.md`. Set its
container/env/backup paths explicitly in a root-owned mode-0600 host configuration.
The workstation command accepts `--host YOUR_SSH_ALIAS`.

```bash
keyholder --host YOUR_SSH_ALIAS system doctor
keyholder --host YOUR_SSH_ALIAS backend list
keyholder --host YOUR_SSH_ALIAS backend register
keyholder --host YOUR_SSH_ALIAS user attach alice
keyholder --host YOUR_SSH_ALIAS customer link alice
```

For Marzban, create `alice` in the panel first or use the CLI provisioning command
with explicit quota and expiry. For HTTP sources, its configured account endpoint
must already exist. Link commands require a terminal or explicit private output
file. Repeated registration returns the same identity and URL.
