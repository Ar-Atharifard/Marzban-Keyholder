# API reference

Expose only `/s/` publicly; keep `/admin/` and `/health` private. Admin requests
require `Authorization: Bearer <KEYHOLDER_ADMIN_KEY>` (one operator key, no roles).
Unauthorized requests return 401 with `WWW-Authenticate: Bearer`.

Responses use `Cache-Control: no-store`, `nosniff` and `Referrer-Policy: no-referrer`.
Errors are `{"detail":"message"}`; validation returns `{"detail":"Invalid request"}`
without echoing inputs. Never log bearer paths, credentials or response bodies.

## Schemas

| Type | Fields and rules |
|---|---|
| `MappingInput` | `backend_id` defaults to `marzban-default` (1–64 ASCII letters/digits/`_-`); required `upstream_username` (3–32 letters/digits/`_`) |
| `CustomerView` | `id`, private `name`, nullable `telegram`/`phone`, `status`, `policy`, UTC `created_at`/`updated_at`/`revoked_at`, `mapping`; no token/hash |
| `TokenResult` | `customer` (CustomerView), `token`, `subscription_url` |
| `Policy` | `profiles` list, at most eleven names; defaults retain original five families; empty list allowed |

IDs are opaque UUID strings. Unknown fields/profile names are rejected. Names are
private display metadata, not upstream usernames. Telegram/phone are nullable and
unique when present; handles normalize to lowercase `@name`, phones to international
`+digits`. Contacts never enter subscription output or Marzban.

Supported families: `tcp_reality`, `xhttp_reality`, `grpc_cdn`, `tcp_reality_ipv6`,
`shadowsocks_ipv6`, `ws_tls_cdn`, `xhttp_tls_cdn`, `trojan_grpc_cdn`,
`vmess_httpupgrade_cdn`, `trojan_reality_ipv6`, `trojan_xhttp_cdn`.
Legacy stored policies retain supported choices and omit obsolete fields. With
`PROFILE_SOURCE=upstream`, supported provider selections control output instead;
the global enabled-family/CDN restrictions always apply.

## Routes

All `/admin` routes require the bearer key.

| Method and path | Input → success |
|---|---|
| GET `/health` | No auth → 200 `{"status":"ok"}`; DB connectivity only |
| GET `/s/{token}` | `format=uri` (default), `xray`, or `info`; details below |
| GET `/admin/backends` | → 200 list of `id`, `provider`, `config_ref`, `registered` |
| POST `/admin/backends/register` | No body → 200 same list; idempotently registers configured metadata |
| GET `/admin/backends/{id}/inbound-defaults` | → 200 `backend_id`, `inbound_tags`, `source` (`database` or `environment`) |
| PUT `/admin/backends/{id}/inbound-defaults` | `{"inbound_tags":["TAG",...]}` → 200 same view; Marzban backends only |
| POST `/admin/customers` | MappingInput + required `name` (1–200), optional contacts/policy → 201 TokenResult |
| GET `/admin/customers` | `offset` ≥0 (default 0), `limit` 1–100 (default 50) → 200 CustomerView array |
| GET `/admin/customers/{id}` | → 200 CustomerView |
| GET `/admin/customers/{id}/subscription` | → 200 TokenResult with existing URL; no mutation |
| PATCH `/admin/customers/{id}` | Optional `name`, `telegram`, `phone`, `status`, `policy` → 200 CustomerView |
| PUT `/admin/customers/{id}/mapping` | MappingInput replaces both mapping fields → 200 CustomerView |
| POST `/admin/customers/{id}/rotate-token` | No body → 200 TokenResult; old URL invalid immediately |

Registration attaches local identity to an existing upstream account; the API does
not provision panel users. It atomically returns the same canonical identity/token
for repeated backend/account registration (201 retained for compatibility); it does
not update metadata on repeated calls. Listing is ordered by creation/ID, contains
no total count and never exposes URLs. Provisioning/inventory is in the CLI.

Inbound defaults apply only to future CLI/bot provisioning. Tags must be unique,
nonempty, at most 200 characters each (1–128 tags). The CLI validates them against
the live catalog; raw API callers must choose available tags. Saved defaults override
environment defaults and are backed up in the existing application-data table.
Unknown/non-Marzban backend returns 404; a concurrent first write can return 409.

PATCH omission leaves fields unchanged; explicit null clears contacts, not name.
A supplied policy replaces the entire policy (`{}` restores compatibility defaults).
Statuses: `active`, `disabled`, `revoked`. Revocation is terminal; later PATCH,
remapping and rotation return 409. Local disable/revoke stops subscription delivery,
not proxy credentials already downloaded; enforce access in the upstream panel.

Mappings do not verify upstream existence; delivery detects unavailable accounts.
Unknown backend is 422, another registered owner of the target mapping is 409.
Tokens/URLs survive remapping. Configured provider identity cannot be overwritten
under an existing backend ID: register a new ID and remap explicitly.

Retrieval/rotation work for disabled identities, but delivery remains disabled.
Revoked/legacy-unrecoverable tokens return 409. Missing/broken vault key returns
503; restore it rather than creating another identity. Tokens have 256 random bits,
a SHA-256 lookup hash and authenticated encrypted ciphertext. They have no scheduled
expiry; status/quota/expiry and infrastructure still affect delivery.

Example registration:

```json
{"name":"Example customer","upstream_username":"alice","telegram":"@example_customer","phone":null}
```

## Subscription output

- **URI:** `text/plain`, standard base64 of newline-separated URIs, final newline
  inside encoding. Optional usage information adds one leading informational record
  at `127.0.0.1:1`; it is deliberately unusable, shows remaining/total traffic/time
  and must not be selected. Its failed delay result is expected.
- **Xray:** `application/json`, array of individual client configs with remarks,
  loopback SOCKS inbound and proxy outbound; no informational record. Explicit
  `format=xray` or `Keyholder-Xray` User-Agent opts in; other apps are not guessed.
- **Info:** `?format=info` is script-free HTML showing current usage, remaining time,
  allowance, status and UTC expiry. Limited/expired upstream accounts may view it;
  locally disabled/revoked tokens cannot. Missing statistics returns 503. No proxy
  credentials or external assets; restrictive CSP and no caching/referrers.

Only active local/upstream accounts receive configurations. Invalid/malformed or
unsupported profiles are omitted; no compatible output returns 503. XHTTP `extra`
is stripped from URI/JSON transport output, not unrelated fields. Certificate
verification remains enabled; upstream ECH is ignored and trusted native ECH is
controlled by [settings](getting-started.md#settings). Delivery never edits inbounds.

When available, `subscription-userinfo` contains byte counters and Unix expiry:
`upload=0; download=1024; total=4096; expire=1893456000`. Zero total/expiry means
unlimited/no expiry. Marzban combined usage is represented as download, upload zero.
It refreshes on fetch; clients may ignore it. `keyholder customer link USER --info`
retrieves the same URL with `format=info` privately.

## Errors and limits

| Status | Meaning |
|---|---|
| 401 | Missing/incorrect admin key |
| 404 | Missing customer or unknown/disabled/revoked subscription; inactive upstream |
| 409 | Revoked identity, mapping/contact conflict, backend mismatch or legacy token |
| 422 | Invalid input/format or unknown backend |
| 429 | Rate limit; `Retry-After: 60` |
| 502 | Upstream fetch/auth/schema/permission failure or total deadline |
| 503 | Missing adapter, no compatible output or unavailable vault/statistics |
| 500 | Sanitized unexpected application/DB failure |

Marzban read HTTP 403/404 currently becomes 502, not local customer-not-found.
Subscription rate limits use token hashes; admin limits use immediate peer IP,
which can be shared behind a gateway. Forwarded headers do not change identity.
Limits are per process: one worker only. No stale subscriptions are served.

Marzban uses form login `/api/admin/token` and bearer GET `/api/user/{username}`;
status/links/usage are validated, at most 128 links/1 MiB, redirects refused and
HTTPS verified. Password login gets one refresh/retry; static tokens do not refresh.
The configured deadline covers the full login/fetch sequence. HTTP-export providers
are read-only and must enforce availability; see [provider boundary](development.md).

`/docs`, `/redoc`, `/openapi.json` and retired `/admin/settings/ech` are unavailable.
Generate offline OpenAPI with `scripts/export_openapi.py` (no production secrets,
DB creation or lifespan startup). No delete-customer, billing, node-management,
plan, provisioning or application-settings API is implemented.
