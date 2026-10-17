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
See Settings below for multiple panels or HTTP subscription sources.

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

## Settings

All names below use the `KEYHOLDER_` prefix. Environment overrides `.env`;
collections are JSON, not comma-separated strings. `.env.example` and
`src/keyholder/config.py` define the complete accepted settings and validation.

| Setting | Purpose / default |
|---|---|
| `ADMIN_KEY` | Required bearer secret, at least 32 characters |
| `TOKEN_ENCRYPTION_KEY` | Fernet key; preserve with DB to retrieve existing URLs |
| `DATABASE_URL` | `sqlite:///./data/keyholder.db`; Compose uses `/data/keyholder.db` |
| `PUBLIC_BASE_URL` | Permanent public HTTPS subscription hostname |
| `MARZBAN_URL` | Legacy single panel, default `http://127.0.0.1:8000` |
| `MARZBAN_TOKEN` or `MARZBAN_USERNAME`/`MARZBAN_PASSWORD` | Static bearer or refreshable login |
| `BACKENDS` | Explicit provider JSON list; empty uses legacy Marzban settings |
| `PROFILE_SOURCE` | Set `upstream`; legacy default `policy`, alias `marzban` supported |
| `ENABLED_PROFILES` | Supported families allowed globally; `[]` disables output |
| `ALLOWED_CDN_HOSTS`, `ALLOWED_CDN_NETWORKS` | Trusted CDN hostnames and edge CIDRs |
| `CDN_ECH_CONFIG` | Optional trusted dynamic ECH lookup; empty disables |
| `CDN_TLS_COMPATIBILITY` | False by default; prefer ordinary TLS with labelled ECH alternatives |
| `UPSTREAM_TIMEOUT` | Entire upstream/login deadline, 10 seconds (1–60) |
| `RATE_LIMIT_PER_MINUTE` | Per-process limit, 60; run one worker |

Example multiple providers (replace credentials privately):

```dotenv
KEYHOLDER_BACKENDS=[{"id":"west","provider":"marzban","config_ref":"west","url":"https://panel.example.com","username":"admin","password":"replace-privately"},{"id":"export","provider":"http_subscription","config_ref":"export","url":"https://export.example.com/accounts/{username}","token":"replace-privately"}]
KEYHOLDER_PROFILE_SOURCE=upstream
```

HTTP templates require exactly one `{username}` outside the authority. No URL
userinfo, redirects or caller-selected hosts. Account references retain the API's
3–32 ASCII letters/digits/underscores. Register configured metadata explicitly
with `keyholder backend register`; startup does not write it. Use a new backend
ID for another provider identity, then explicitly remap customers. Select a
namespace with `keyholder --backend west user attach alice`.

Literal CDN IPs require trusted networks and matching allowed TLS/HTTP identity;
existing recognized Cloudflare IPv6 edges remain compatible. Never trust arbitrary
origin CIDRs. ECH applies only to eligible trusted CDN hostname profiles, not direct
or literal-IP profiles, and retains credentials/ports/paths. It cannot guarantee
ISP reachability. Unsupported inputs fail closed.

Compose uses `KEYHOLDER_ENV_FILE` and bridge `KEYHOLDER_PUBLISH_ADDRESS`/`PORT`;
keep publishing on loopback. CLI config is selected by `KEYHOLDER_ADMIN_CONFIG`,
host dispatcher config by `KEYHOLDER_HOST_CONFIG`; see the operator reference.
