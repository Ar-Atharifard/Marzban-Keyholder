# Keyholder

An isolated subscription backend. Customers keep `https://keyholder.javatechpack.ir/s/<token>` while their upstream mapping changes. Keyholder reads Marzban through HTTP only; it does not create or modify panel users, query the panel database, or change existing services.

## Setup and run (Ubuntu VPS)

Run from `/srv/keyholder`. Docker Compose must already be available. Do not copy real credentials into Git.

```bash
cd /srv/keyholder
cp .env.example .env
chmod 600 .env
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
# Edit .env: replace KEYHOLDER_ADMIN_KEY with the generated value;
# keep KEYHOLDER_MARZBAN_URL=http://127.0.0.1:8000 and set panel credentials or a bearer token.
docker compose build
docker compose run --rm --no-deps api /app/.venv/bin/alembic upgrade head
docker compose up -d api
curl --fail http://127.0.0.1:18000/health
docker compose logs --tail=100 api
```

Compose uses **Linux host networking**, with Uvicorn explicitly bound only to **`127.0.0.1:18000`**. There are no published ports or host-gateway overrides. It uses a dedicated named database volume and a non-root container. Migrations run explicitly before startup; application startup never creates tables. No other service is started, stopped, or modified. `docker compose down` stops Keyholder; **do not add `-v`**, which deletes its database.

This project does not configure DNS, TLS, Nginx, or firewall. Public HTTPS routing to the loopback API is a separate deployment step. Keep the admin routes private where practical. Any future ingress access logs must redact `/s/*` paths and query strings, because the token is a bearer secret. Back up the database volume before upgrades; retain the public domain and database for stable URLs.

On this Linux VPS, host networking lets Keyholder reach Marzban at `http://127.0.0.1:8000` while Marzban retains its existing loopback-only binding. Keyholder also listens only on loopback at port 18000; the healthcheck uses that port. Container hardening remains in place, including the non-root user, read-only filesystem, dropped capabilities, and no-new-privileges. Host networking shares the host network namespace, so the explicit loopback bind is essential. Do not change panel bindings, networks, or firewall for this project. TLS verification remains enabled for HTTPS upstream URLs; redirects and environment proxy settings are off. Panel credentials are environment variables, never database records.

## Admin workflow

Use `Authorization: Bearer <KEYHOLDER_ADMIN_KEY>`. The key must have at least 32 characters; use the generation command above. Create the Marzban user separately, then create its Keyholder mapping. The examples below use shell variables; enter values privately and avoid shell tracing.

```bash
read -rs -p 'Admin key: ' ADMIN_KEY; echo
export ADMIN_KEY
curl --fail-with-body http://127.0.0.1:18000/admin/customers \
  -H "Authorization: Bearer $ADMIN_KEY" -H 'Content-Type: application/json' \
  -d '{"name":"First customer","upstream_username":"alice","policy":{"profiles":["xhttp_reality","tcp_reality","xhttp_cdn","ws_cdn"],"ech_enabled":false}}'
```

The response includes `customer`, `token`, and `subscription_url`. **Save the URL securely now:** only its SHA-256 hash is persisted. Listing cannot recover it. Tokens contain 256 random bits. Normal mapping/policy/status changes preserve the token; rotation intentionally changes it immediately.

| Method | Endpoint | Behavior |
|---|---|---|
| GET | `/health` | Database connectivity; no upstream login |
| GET | `/s/{token}` | Base64 VLESS URI subscription |
| GET | `/s/{token}?format=xray` | Xray JSON array with one client config per profile |
| POST | `/admin/customers` | Create customer and mapping; return raw token once |
| GET | `/admin/customers?offset=0&limit=50` | Paginated listing, no tokens |
| GET | `/admin/customers/{id}` | Customer and current mapping |
| PATCH | `/admin/customers/{id}` | Change name, policy, or status |
| PUT | `/admin/customers/{id}/mapping` | Replace upstream username/backend reference |
| POST | `/admin/customers/{id}/rotate-token` | Invalidate old token, return new token |
| GET/PUT | `/admin/settings/ech` | Read/replace static ECH application data |

Disable with `{"status":"disabled"}`; re-enable with `{"status":"active"}`. Revoke with `{"status":"revoked"}`; revocation is terminal and records a timestamp. Mapping changes and token rotation are also rejected for revoked customers. These statuses only stop Keyholder subscription delivery: they do not revoke configurations already downloaded or stop upstream proxy access. For that, manage the upstream account separately.

The seeded backend ID is `marzban-default`. This MVP configures one panel through environment variables. Backend rows reserve provider/configuration references for a future controlled registry; admin callers cannot supply panel URLs.

## Profiles and static ECH

The adapter reads VLESS links and the normalizer reconstructs only recognized fields. Unknown transports/protocols and malformed links are omitted; an empty compatible set fails closed with HTTP 503. Unwanted parameters such as `extra`, `allowInsecure`, upstream ECH, MUX, and upstream flow are never forwarded.

| Profile | Output behavior |
|---|---|
| XHTTP REALITY | `stream-one`, no Vision |
| RAW/TCP REALITY | normalized to TCP, `xtls-rprx-vision` |
| XHTTP TLS CDN | `stream-up`, ALPN `h2,http/1.1`, no Vision |
| WebSocket TLS CDN | ALPN `http/1.1`, no Vision |

Xray MUX is explicitly off. XHTTP+TLS links are classified as CDN profiles by transport/security; the adapter cannot independently prove Cloudflare routing. Ensure the upstream links describe the intended CDN hosts. Existing IPv6 addresses are supported. New IPv6 endpoint derivation and F&F TLS variants are extension points, not implemented policies.

To configure ECH, use the verified working **standard base64 ECHConfigList** (not a DNS/DoH URL):

```bash
# Write this file locally with your current verified value:
# {"ech_config_list":"<static base64 ECHConfigList>"}
curl --fail-with-body -X PUT http://127.0.0.1:18000/admin/settings/ech \
  -H "Authorization: Bearer $ADMIN_KEY" -H 'Content-Type: application/json' \
  --data-binary @ech-settings.json
# Enable on a customer (replace CUSTOMER_ID):
curl --fail-with-body -X PATCH http://127.0.0.1:18000/admin/customers/CUSTOMER_ID \
  -H "Authorization: Bearer $ADMIN_KEY" -H 'Content-Type: application/json' \
  -d '{"policy":{"ech_enabled":true,"include_base_cdn":true}}'
```

The JSON renderer duplicates eligible XHTTP CDN profiles and injects `streamSettings.tlsSettings.echConfigList`. No DNS lookup is used. ECH application data is read each request, so rotation takes effect without rebuilding or changing subscription URLs. Missing ECH data with ECH enabled returns 503. Validation checks base64 and list length framing; it cannot establish whether Cloudflare currently accepts the supplied value.

Use the same stable URL with `?format=xray` for ECH-compatible clients. The default URI output omits ECH variants and retains base profiles; URI ECH parameter import is deliberately not assumed. `include_base_cdn=false` makes CDN profiles ECH-only; URI output may then have no compatible profiles and return 503. Format selection is explicit or uses the opt-in `Keyholder-Xray` User-Agent marker. There is no automatic assumption that all v2rayN versions accept Xray JSON arrays. **Verify subscription/import behavior, bundled Xray version, `echConfigList`, XHTTP, and REALITY key fields on your actual clients before rollout.** No claim of live v2rayN 7.25.4 verification is made.

## Marzban compatibility gate

The HTTP contract was checked against published Marzban source:

- [Admin router](https://github.com/Gozargah/Marzban/blob/master/app/routers/admin.py): POST `/api/admin/token` with URL-encoded `username` and `password`, response `access_token`.
- [User router](https://github.com/Gozargah/Marzban/blob/master/app/routers/user.py): GET `/api/user/{username}` with bearer authorization.
- [User response model](https://github.com/Gozargah/Marzban/blob/master/app/models/user.py): `status` and `links: list[str]`.
- [Xray TLS configuration](https://github.com/XTLS/Xray-core/blob/main/infra/conf/transport_internet.go): client JSON fields are version-sensitive; validate using the deployed Xray core.

**Installed Marzban version remains unverified.** Before live use, inspect its existing API documentation/OpenAPI without altering service configuration. Confirm the above paths, authentication, `active` status meaning, and that `links` includes the desired VLESS transports, UUID, address, port, SNI, host/path, REALITY public key and short ID. Verify access with the intended admin's user ownership permissions. If it differs, change only the adapter/parser and its fixtures. Keyholder never follows `subscription_url` and never calls write endpoints. The upstream authentication POST is only for obtaining an access token.

Requests have bounded timeouts and a 1 MiB decompressed response limit. An expired password-login bearer token gets one refresh/retry. A configured static bearer token requires operator replacement on expiry. Inactive users fail closed; malformed schemas, network errors, permission errors and upstream HTTP failures become sanitized errors. There is no stale configuration cache or arbitrary URL fetch endpoint.

## Future requirement: deployment on an Iranian VPS

The public subscription endpoint currently calls Marzban synchronously on every request. Moving Keyholder to an Iranian VPS cannot use this same-host loopback connection: cross-border connectivity, Marzban outages, or filtering would directly affect subscription delivery. Stable URLs alone do not remove this availability dependency.

Before that move, design and implement authenticated background synchronization of upstream configurations into local durable snapshots, and serve public subscriptions from those snapshots. Define refresh scheduling/retries, snapshot freshness and expiry, atomic updates, upstream status/revocation propagation, credential protection, and explicit fail-closed behavior when data is stale or unavailable. The synchronization channel must not require publicly exposing the panel. This is a future architecture requirement only; no caching, snapshot storage, background synchronization, or stale-serving behavior is implemented in this change.

## Local development, tests, and migrations

Install Python 3.12 and `uv` using your normal tooling, then:

```bash
cd /srv/keyholder
uv sync --frozen --extra dev --python 3.12
cp .env.example .env  # only if .env does not already exist
# Set a generated admin key; configure upstream credentials only for live testing.
mkdir -p data
uv run alembic upgrade head
uv run uvicorn keyholder.main:create_app --factory --host 127.0.0.1 --port 18000 \
  --workers 1 --no-access-log --no-proxy-headers
```

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run alembic check
# New schema change:
uv run alembic revision --autogenerate -m 'describe change'
uv run alembic upgrade head
# Rollback only against a backed-up development database:
uv run alembic downgrade -1
```

Tests use temporary SQLite databases and mocked HTTP; no real panel or services are touched. Dependencies are locked in `uv.lock`. Docker uses the same frozen production dependency lock.

## Operational scope

Structured logs contain route templates, method, status, and duration, never raw paths, query strings, bodies, authorization, upstream responses, or tokens. API responses use `no-store`. Validation errors are sanitized. Uvicorn access logging is disabled. Run exactly one worker for the bounded in-memory rate limiter; forwarded headers are not trusted. For `/s/{token}`, each token has an independent SHA-256 digest bucket, so customers sharing a reverse proxy peer do not share subscription limits. Neither raw tokens nor bucket digests are logged. Admin requests use a separate peer bucket and do not consume subscription limits. Other public routes retain peer limiting. Arbitrary `X-Forwarded-For` headers cannot change these buckets. Replace the in-memory limiter with a distributed implementation before scaling. It is a local abuse guard, not distributed DDoS protection.

SQLite uses foreign keys, WAL, and a busy timeout. Back up using SQLite's backup API or stop **Keyholder only** before copying its DB and WAL files. Keep the volume permissions restricted. For PostgreSQL, add a driver, change the environment database URL, run migrations against a fresh database, and migrate customer/token-hash/mapping/application-data records while preserving IDs and hashes. Provider URLs remain trusted operator configuration. See [ARCHITECTURE.md](ARCHITECTURE.md).

No billing, payment, web admin UI, WARP, MASQUE, or Aether integration is included.

## Verification completed

Targeted review on October 7, 2026: Python 3.12 runs 27 passing tests, including independent subscription buckets, forwarded-header resistance, rejected mutations after revocation, and mapping/rotation timestamps. Ruff lint/format, strict mypy, and Alembic schema-drift checks pass. Alembic verification used an isolated migrated SQLite database inside the repository. `KEYHOLDER_ENV_FILE=.env.example docker compose config` validates host networking, the explicit `127.0.0.1:18000` Uvicorn bind, the matching healthcheck, and retained hardening with no published ports or host-gateway overrides. Starlette emits one development TestClient deprecation warning for httpx; the requested httpx adapter is retained. No live panel, client import, public HTTPS route, container redeployment, or production service was modified or tested during this review.
