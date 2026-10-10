# Keyholder

Keyholder provides stable customer subscriptions at `/s/{token}` while an operator can change the upstream mapping. It reads Marzban through HTTP; it never provisions panel users, reads the panel database, or changes proxy services.

This release targets the five currently configured Marzban families:

| Policy profile | Accepted upstream configuration |
|---|---|
| `tcp_reality` | IPv4/domain VLESS TCP or RAW with REALITY |
| `xhttp_reality` | VLESS XHTTP with REALITY |
| `grpc_cdn` | VLESS gRPC with TLS, supplied through the external gateway |
| `tcp_reality_ipv6` | IPv6 VLESS TCP or RAW with REALITY |
| `shadowsocks_ipv6` | IPv6 Shadowsocks `aes-128-gcm` |

All five current Marzban families are enabled by default. Administrators can still select a smaller per-customer policy. No endpoints are synthesized and no new upstream protocols, nodes or plans are provisioned. A TLS gRPC link does not independently prove CDN routing; operators must validate the external gateway/domain setup.

ECH generation, its settings API, WebSocket CDN and XHTTP TLS CDN are retired in this deployed release. Legacy ECH application data remains stored for recovery. Migration `0002` archives policies and enables the owner-approved five-profile policy for existing customers. It preserves customer IDs, token hashes, mappings and URLs. It enables gRPC, IPv6 TCP REALITY and IPv6 Shadowsocks alongside TCP/XHTTP REALITY. A policy with no remaining compatible profiles returns 503 until an administrator chooses a supported profile.

## Documentation

- [API reference](docs/API.md): authentication, payloads, endpoints and errors.
- [Operations](docs/OPERATIONS.md): local workflow, backup, release and recovery gates.
- [Architecture](ARCHITECTURE.md): application boundaries and limitations.

The Marzban-only backend is deployed with database revision `0002`. Hiddify has
been removed. Nginx owns public 80/443 and retains 2053 for existing Cloudflare
gRPC origin rules. See [cutover and recovery](docs/CUTOVER.md) and
[Cloudflare settings](docs/CLOUDFLARE.md) for verified outcomes and remaining checks.

## Local development

Use Python 3.12 and the committed dependency lock:

```bash
uv sync --frozen --extra dev --python 3.12
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src tests scripts
```

Tests use synthetic data, disposable SQLite databases and mocked HTTP. They do not require production credentials. Migration tests exercise revision 0001 through 0002 and rollback. Backup tests include committed WAL data and identity preservation.

For a separate development instance, copy `.env.example` only if `.env` does not already exist, restrict it to mode 0600 and replace the placeholder admin key with a privately generated value of at least 32 characters. Use a local database and test-only panel credentials. Then run:

```bash
mkdir -p data
.venv/bin/alembic upgrade head
.venv/bin/uvicorn keyholder.main:create_app --factory --host 127.0.0.1 \
  --port 18000 --workers 1 --no-access-log --no-proxy-headers
```

Application startup never creates tables or runs migrations. Never run the above migration command with a production database URL as part of development checks.

## Configuration

All settings use the `KEYHOLDER_` prefix and can be loaded from `.env`.

| Setting | Behavior |
|---|---|
| `ADMIN_KEY` | Required bearer key, minimum 32 characters; placeholders rejected |
| `DATABASE_URL` | SQLite development path; Compose overrides it to `/data/keyholder.db` |
| `PUBLIC_BASE_URL` | Permanent public base; returned URLs append `/s/{token}` |
| `MARZBAN_URL` | Trusted panel base; same-VPS deployment uses loopback port 8000 |
| `MARZBAN_TOKEN` | Optional static bearer token; operator replaces it on expiry |
| `MARZBAN_USERNAME`, `MARZBAN_PASSWORD` | Login credentials used when no static token is supplied |
| `UPSTREAM_TIMEOUT` | Total login/fetch deadline and HTTP timeout, default 10 seconds, range 1–60 |
| `RATE_LIMIT_PER_MINUTE` | Default 60, range 1–10000; per subscription token or admin peer bucket |

URL settings reject embedded credentials, queries and fragments. Credentials are environment settings, not database records. Do not put them in Git or shell tracing.

## Deployment boundaries

Compose uses Linux host networking. Uvicorn must remain explicitly bound to `127.0.0.1:18000`; there are no published ports. The API container uses a dedicated database volume, a non-root user, a read-only root filesystem, dropped capabilities, `no-new-privileges`, a bounded temporary filesystem and rotated Docker logs.

A reviewed deployment builds a known commit, runs separately approved migrations, and replaces **Keyholder only**. Follow the operations runbook before executing it. Do not use `docker compose down -v`, which deletes the database volume. Keep the previous image and a verified private database backup for rollback.

DNS, public TLS, proxy routing and firewall rules are managed separately. The gateway serves Marzban gRPC and Keyholder `/s/` on the stable hostname.
Admin and health routes remain private. The gateway uses a pinned image, a
read-only root, restricted capabilities, resource limits and rotated Docker logs.
Ingress access/error logging is suppressed to protect subscription tokens.

## Reliability and security

Only SHA-256 subscription-token hashes are stored. Tokens contain 256 random bits and are returned once at creation/rotation. Mapping and policy changes preserve the URL; rotation invalidates the previous token immediately.

Disable/revoke stops Keyholder delivery only. It does not revoke already-downloaded proxy credentials; administer the upstream account separately. Revocation is terminal.

Each subscription fetch awaits Marzban with a bounded deadline. The database read
transaction is closed first so slow upstream requests cannot exhaust its pool. Only active users are accepted. There is no stale cache, snapshot store, background synchronization or automatic failover. The adapter verifies HTTPS, refuses redirects, ignores proxy environment variables, limits decompressed responses to 1 MiB and accepts at most 128 links. Password-login authentication allows one refresh/retry after a 401.

Normalization reconstructs recognized fields. XHTTP `extra` is omitted from URI query output and Xray `xhttpSettings`; host/path and supported upstream modes are retained. ECH and upstream MUX settings are not imported; JSON MUX is disabled. Unsupported or malformed links are omitted and empty output fails closed with 503. TCP/RAW flow is preserved when supported; XHTTP and gRPC never receive Vision flow.

Request logs contain route templates, method, status and duration, without tokens, raw paths, query strings, bodies or upstream responses. HTTP library INFO logging is suppressed. Responses use `no-store`. Validation errors do not echo input values.

The rate limiter is bounded and in-memory. Run one worker. Subscription buckets use token hashes; admin buckets use the immediate peer, ignoring forwarded headers. This is a local abuse guard, not distributed DDoS protection. SQLite uses foreign keys, WAL and a five-second busy timeout. `/health` checks the DB, not subscriptions.

All five profiles passed real HTTPS connectivity through installed Xray clients.
Owner client import/refresh remains the final compatibility check. Verify each client's support for IPv6, XHTTP, gRPC and REALITY fields; renderer tests alone do not prove live access. Billing, user provisioning, multi-node orchestration and additional protocols are future work, not features of this release.
