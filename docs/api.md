# API reference

This documents the application API. Public `/s/` uses the configured subscription
base. Keep admin and health routes private behind your ingress or SSH access.

## Authentication and response conventions

Admin endpoints require `Authorization: Bearer <KEYHOLDER_ADMIN_KEY>`. Missing or
incorrect credentials return 401 with `WWW-Authenticate: Bearer`. There is one
operator key, without roles or per-administrator audit identity.

Subscription tokens are bearer credentials in `/s/{token}`. They contain 256 random
bits, are stored as SHA-256 hashes plus authenticated encrypted ciphertext.
An authenticated subscription-retrieval endpoint recovers the same URL; listing never reveals it. Protect URLs from access logs, shell history and
analytics. Mapping/policy changes preserve the URL; rotation invalidates it.

All responses have `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` and
`Referrer-Policy: no-referrer`. Error bodies use `{"detail":"message"}`. Request
validation errors return `{"detail":"Invalid request"}` without echoing inputs.

## Customer request and response schemas

`MappingInput`:

| Field | Rules |
|---|---|
| `backend_id` | Default `marzban-default`; 1–64 ASCII letters, digits, `_` or `-` |
| `upstream_username` | Required; 3–32 ASCII letters, digits or `_` |

Adapters are registered from server-owned configuration. A backend row does not automatically
enable a provider. Mapping changes do not contact upstream providers or validate user existence;
missing users or permission failures surface when fetching the subscription.

`Policy` has one field, `profiles`: a list of at most eleven supported profile names.
The defaults retain the original five profiles for compatibility. An empty list is allowed
and disables compatible output in legacy policy mode, producing 503.
With `KEYHOLDER_PROFILE_SOURCE=upstream`: supported current upstream
selections control output; stored policy is retained for compatibility. Supported choices are:

- `tcp_reality`
- `xhttp_reality`
- `grpc_cdn`
- `tcp_reality_ipv6`
- `shadowsocks_ipv6`
- `ws_tls_cdn`
- `xhttp_tls_cdn`
- `trojan_grpc_cdn`
- `vmess_httpupgrade_cdn`
- `trojan_reality_ipv6`
- `trojan_xhttp_cdn`

Unknown request fields/profile names are rejected. `ech_enabled`,
`include_base_cdn`, `xhttp_cdn` and `ws_cdn` are no longer accepted API inputs.
Legacy stored policies are read conservatively: supported selections remain, old
fields are omitted, and new families are not added automatically.

`CustomerView` contains `id`, private `name`, nullable `telegram` and `phone`,
`status`, `policy`, `created_at`, `updated_at`, `revoked_at` and `mapping`. IDs are
opaque strings generated as UUIDs. Timestamps
are ISO datetime values; `revoked_at` is null until revocation. SQLite may serialize
timestamps internally without an offset; API views normalize them to UTC. No token
hash or raw token is included in this view.

`TokenResult` contains `customer` (a CustomerView), `token` and `subscription_url`.
Registration, explicit rotation and authenticated retrieval return it.

## Endpoints

### GET `/health`

Unauthenticated. Success: 200, `{"status":"ok"}`. Checks database connectivity
only; it does not log in to Marzban or prove subscription delivery.

### GET `/s/{token}`

No admin authorization. `format=uri` returns `text/plain`: standard base64 of
newline-separated proxy URIs, with a final newline before encoding. `format=xray`
returns `application/json`: an array of individual Xray client configurations,
each with remarks, a loopback SOCKS inbound and one proxy outbound. These formats
include supported profiles selected by Marzban in production; legacy policy mode
uses the stored selection. The configured CDN allowlist applies in either mode.

When validated usage metadata exists, URI output begins with one deliberately
unusable informational record because common clients ignore the standard header.
Its name shows remaining traffic and time, and it points only to `127.0.0.1:1`.
It must not be selected. Its failed delay result is expected. Xray JSON output
does not include this record, and every real profile remains unchanged.

With no format, URI output is the default. An opt-in `Keyholder-Xray` User-Agent
marker selects Xray JSON. Other client names/versions are not guessed. Invalid
format values return 422.

Only active local and upstream customers can receive output. Unsupported/malformed
links are omitted. Empty compatible output returns 503. XHTTP `extra` is omitted
from the URI query and JSON `xhttpSettings`, while allowed host/path/mode fields
are retained. Legacy ECH is not generated. Optional trusted native CDN ECH is added by delivery configuration (see [configuration](configuration.md)); upstream ECH remains ignored. This processing never rewrites panel inbounds.

### POST `/admin/customers`

Create the Marzban user separately first. This endpoint atomically registers or retrieves only local identity
and mapping. A database constraint guarantees one canonical registration per
backend/username, including concurrent calls. Body combines MappingInput with
required private `name` (1–200 characters), nullable `telegram` and `phone`, and
optional `policy`. Telegram and phone are administrator-only and unique when
present. Telegram usernames are stored lowercase with `@`; phone numbers are
stored in international `+digits` form. Example:

```json
{
  "name": "Example customer",
  "telegram": "@example_customer",
  "phone": "+989121234567",
  "upstream_username": "alice",
  "backend_id": "marzban-default",
  "policy": {
    "profiles": ["xhttp_reality", "tcp_reality", "grpc_cdn", "tcp_reality_ipv6", "shadowsocks_ipv6"]
  }
}
```

Success: 201, TokenResult, including repeated registration for compatibility.
Repeated calls return the same ID/token and do not rename or update the customer.
Unknown backend: 422. Revoked or legacy-unrecoverable registration: 409. Broken
vault key: 503; restore the key rather than minting another identity.

### GET `/admin/customers`

Query: `offset` defaults to 0, minimum 0; `limit` defaults to 50, range 1–100.
Success: 200, array of CustomerView, ordered by creation time then ID. There is no
total-count field or panel-wide user listing. Token retrieval uses the endpoint below.

### GET `/admin/customers/{customer_id}`

Success: 200, CustomerView. Missing customer: 404.

### GET `/admin/customers/{customer_id}/subscription`

Admin authentication required. Success: 200, TokenResult with the existing URL.
No mutation or implicit rotation. Missing customer: 404; revoked or legacy token
without ciphertext: 409; missing/wrong encryption key: 503. Disabled customers
can retrieve their URL, but delivery remains disabled.

### PATCH `/admin/customers/{customer_id}`

Optional fields: `name`, `telegram`, `phone`, `status`, `policy`. Omitted fields
remain unchanged. Explicit `null` clears Telegram or phone; name cannot be null.
Duplicate contacts return 409. Status is `active`, `disabled` or `revoked`.
Example: `{"telegram":"@new_handle","phone":null}`.

**A supplied policy replaces the complete policy; it is not merged.**
In production Marzban-authority mode it does not override panel inbound selections.
`{"policy":{}}` replaces it with defaults. To select only gRPC, send
`{"policy":{"profiles":["grpc_cdn"]}}`.

Success: 200, CustomerView. Revocation records a timestamp and is terminal: all
later PATCH, mapping and token-rotation requests return 409. Disable/revoke stops
Keyholder delivery only; downloaded proxy credentials remain usable until the
upstream account is changed separately.

### PUT `/admin/customers/{customer_id}/mapping`

Body: MappingInput. Both mapping fields are replaced; omitting `backend_id`
selects its default. Success: 200, CustomerView. Subscription token and URL remain
unchanged. Unknown backend: 422. Revoked customer or target account already registered: 409.

### POST `/admin/customers/{customer_id}/rotate-token`

No request body. Success: 200, TokenResult. The previous token becomes invalid
immediately; there is no grace period. Disabled customers can rotate but cannot
receive output until re-enabled. Revoked customers return 409.

### Retired / unavailable APIs

`GET/PUT /admin/settings/ech` returns 404. There are no delete-customer, upstream
provisioning, node-management, billing, plan or application-settings endpoints.
`/docs`, `/redoc` and `/openapi.json` are disabled over HTTP. Generate an offline
OpenAPI document with `scripts/export_openapi.py`; it needs no production secrets
and neither creates tables nor starts the application lifespan.

## Error reference

| Status | Meaning |
|---|---|
| 401 | Missing/incorrect admin authentication |
| 404 | Missing customer; invalid/unknown/disabled/revoked subscription; inactive upstream user |
| 409 | Revoked identity, canonical mapping conflict or unrecoverable legacy token |
| 422 | Invalid body/query or unknown backend |
| 429 | Rate limit exceeded; `Retry-After: 60` |
| 502 | Upstream fetch/auth/schema/permission failure or total deadline exceeded |
| 503 | Missing runtime adapter, no compatible profiles or unavailable token vault |
| 500 | Unexpected application/database failure; sanitized response |

Upstream 404/403 responses currently become 502, not a local customer-not-found
response. The adapter cannot distinguish a missing upstream account from other
read failures through the public API.

Subscription rate limits are per token hash. Admin limits are per immediate peer,
which can be shared behind a reverse proxy. Forwarded IP headers do not change
identity. Rate limiting is per process; run exactly one worker.

## Integration contract

Marzban login: `POST /api/admin/token` with form username/password; response includes
`access_token`. Read: `GET /api/user/{username}` with bearer authentication; Keyholder
requires `status == "active"` and `links: list[str]` (maximum 128 entries).
Static tokens are not refreshed. Password-login tokens get one refresh/retry.
Redirects are refused, HTTPS is verified, responses are bounded to 1 MiB and the
entire login/fetch sequence has a configured deadline. No stale output is served.

The installed Marzban OpenAPI was verified as 0.8.4. Guarded private database-clone
checks on October 11, 2026 rendered all ten selected profiles for both current
users in both formats. Installed Xray accepted all client configs and each profile
completed a real certificate-verified HTTPS request, including Titan CDN and IPv6.
XHTTP `extra` was omitted from both output forms.

The owner-approved token rotation and duplicate retirement are documented in
`IDENTITY-AND-AUTHORITY.md`. Future upgrades preserve the replacement URLs.
The gRPC public destination stays on 443; existing Titan/Sealord origin-port rules
use 2053, retained by Nginx. New CDN templates use Titan only. VPS validation does
not guarantee every Iranian ISP or client version; refresh the same URL and test
on the actual client without sharing its credential.

The October 12 streaming expansion adds `trojan_xhttp_cdn` without changing existing
endpoints, subscription paths, tokens, defaults or legacy output fixtures. VLESS
streaming XHTTP uses the existing `xhttp_tls_cdn` family. Multiple Marzban host
entries can produce multiple configurations in the same family.

## Provider metadata endpoints

`GET /admin/backends` lists configured adapters as `id`, `provider`, `config_ref`
and `registered`. No source URLs or credentials are returned.
`POST /admin/backends/register` explicitly registers configured metadata. It is
idempotent; existing provider/config-reference mismatches return 409 and are not
overwritten. Both endpoints require the same administrator bearer authentication.
Server configuration, not this API, controls adapter credentials and URLs.

### Subscription usage information

Successful subscriptions include `subscription-userinfo` when the provider supplies
usage: `upload=0; download=1024; total=4096; expire=1893456000`. Counters are bytes;
expiry is Unix seconds. Zero total/expiry means unlimited/no expiry. Marzban supplies
combined traffic usage, represented as download with upload zero, not a directional
breakdown. The figures follow Marzban's current quota/reset accounting and refresh
when the subscription is fetched. Client support for displaying headers varies.

`GET /s/{token}?format=info` returns a small HTML page with remaining traffic, used
traffic, allowance, account status, remaining time and UTC expiry. It uses the same
bearer token and current upstream data. Limited/expired upstream accounts may view
information while configuration delivery remains unavailable. Disabled/revoked
Keyholder tokens remain denied. Missing provider statistics return 503 rather than
inventing a quota. No configurations, credentials, scripts or external assets are
included. The page uses no-store, no-referrer and a restrictive content security
policy. It adds no dummy profile and never changes the subscription URL.

Administrators can retrieve the usage-page URL with `keyholder link USER --info`
(or append `?format=info` to the existing subscription URL). This retrieves the
existing canonical identity; it does not create a new subscription. As with link
retrieval, use an interactive terminal or explicit private `--save-link` file.
