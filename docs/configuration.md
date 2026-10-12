# Configuration

Application settings use `KEYHOLDER_` environment variables; `.env` is optional.
Environment variables take precedence. JSON collections must be valid JSON,
not comma-separated text. Keep credentials in private server-side configuration.

| Variable | Default / purpose |
|---|---|
| `ADMIN_KEY` | Required bearer secret, at least 32 characters |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for retrievable URLs; back up with database |
| `DATABASE_URL` | `sqlite:///./data/keyholder.db`; Compose uses `/data/keyholder.db` |
| `PUBLIC_BASE_URL` | Example placeholder; set permanent HTTPS hostname before registration |
| `MARZBAN_URL` | `http://127.0.0.1:8000`; legacy single-panel configuration |
| `MARZBAN_TOKEN` | Optional static bearer token; replace when expired |
| `MARZBAN_USERNAME`, `MARZBAN_PASSWORD` | Alternative login with token refresh |
| `BACKENDS` | JSON list of explicit providers; empty uses legacy Marzban settings |
| `PROFILE_SOURCE` | `policy` legacy default; `upstream` follows supported upstream links; `marzban` remains a compatible alias |
| `ENABLED_PROFILES` | All implemented families by default; explicit `[]` disables output |
| `ALLOWED_CDN_HOSTS` | Optional JSON hostname list restricting TLS CDN delivery |
| `ALLOWED_CDN_NETWORKS` | Optional trusted edge CIDRs; literal IPs require allowed SNI and matching HTTP identity |
| `CDN_ECH_CONFIG` | Optional dynamic HTTPS DNS ECH lookup; empty disables |
| `CDN_TLS_COMPATIBILITY` | Default false; prefer non-ECH TLS and append labelled ECH fallbacks for selected, permitted hostname CDN TLS profiles |
| `UPSTREAM_TIMEOUT` | Total fetch/login deadline, default 10 seconds, range 1–60 |
| `RATE_LIMIT_PER_MINUTE` | In-memory per-bucket limit, default 60; single worker |

Example supported-family restriction:

```dotenv
KEYHOLDER_ENABLED_PROFILES=["tcp_reality","xhttp_reality","grpc_cdn"]
KEYHOLDER_ALLOWED_CDN_HOSTS=["edge.example.com"]
```

Published Cloudflare IPv6 edges remain recognized for compatibility. Other literal
CDN edge addresses require explicit CIDRs. Configure only networks belonging to a
trusted CDN: an arbitrary origin CIDR would defeat the origin-address restriction.
TLS/HTTP identity checks still apply. ECH is not automatically added to literal-IP
profiles or arbitrary providers; validate provider/client support first.

Supported transports use strict secure defaults. This is not a pass-through exporter
for every Xray feature. Adding an unsupported protocol requires implementation and
tests, rather than weakening validation.

Deployment controls: `KEYHOLDER_ENV_FILE` selects the Compose env file;
`KEYHOLDER_PUBLISH_ADDRESS`/`KEYHOLDER_PUBLISH_PORT` control bridge host publishing.
Keep the address `127.0.0.1` unless a reviewed ingress design requires otherwise.
The host override binds 127.0.0.1:18000 and does not use published-port settings.
CLI client settings use `KEYHOLDER_ADMIN_CONFIG`; dispatcher settings use
`KEYHOLDER_HOST_CONFIG`. See the operator guide for their separate JSON schemas.

Changing domain/path or losing the database/vault key can break customer links.
Changing an upstream does not require changing the public hostname or token.

TLS-first delivery and ECH fallbacks retain upstream credentials, SNI, Host, paths, ports
and protocol selection. Primary entries retain their names and prefer plain TLS. ECH alternatives follow
with an explicit `[ECH fallback]` label. Direct and
literal-IP profiles are never duplicated by this setting. Certificate verification
remains enabled. This does not provide automatic failover or guarantee ISP access.
