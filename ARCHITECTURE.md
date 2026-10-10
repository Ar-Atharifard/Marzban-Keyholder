# Keyholder boundaries

FastAPI's factory in `main.py` owns lifecycle, pooled HTTPX, bounded single-process
rate limiting, sanitized errors and route-template logging. Startup creates no
tables and performs no migrations. HTTP Swagger/OpenAPI routes remain disabled.

`api/public.py` authenticates `/s/{token}` using SHA-256, checks local status and
mapping, closes the DB read transaction before awaiting Marzban, then normalizes
and renders supported upstream links within a total deadline. Production follows
Marzban selections and restricts TLS CDN destinations to Titan. `/health` checks
DB connectivity only. Public GETs never mutate identities, vaults or policies.

`api/admin.py` uses one environment bearer key with constant-time digest comparison.
It atomically registers/retrieves canonical customers, retrieves encrypted tokens,
manages local status/mappings and explicitly rotates tokens. Uniqueness races
return the winning identity. Remapping to another canonical account is refused.
Revocation is terminal; local disable/revoke does not invalidate downloaded proxy
credentials. The admin API never provisions upstream users.

`models.py`/`db.py` own customers, mappings, backend references, canonical
registrations and dormant application archives. SQLite enables foreign keys and
WAL; schema evolution belongs to Alembic. `vault.py` uses maintained Fernet
cryptography with a server-only key and verifies decrypted tokens against hashes.
Missing vault entries/keys fail explicitly instead of rotating links. See the
[database schema](docs/IDENTITY-AND-AUTHORITY.md).

`policies.py` retains conservative legacy policy compatibility. In legacy policy
mode only explicit supported selections are served. Production Marzban-authority
mode follows current supported upstream links, without duplicating user quota,
expiry or inbound state. Original five defaults remain frozen. Migration 0002
archives/applies the old five-profile policy; 0003 adds the vault column and unique
canonical registry without changing token hashes or deleting historical rows.
Downgrading 0003 refuses while encrypted tokens exist; restoring pre-rotation data
would restore old URLs and needs a deliberate full recovery decision.

`backends/marzban.py` handles bounded authentication/user fetches, refresh after
401, schema validation and sanitized failures. Public rendering only logs in and
reads users. Explicit `scripts/admin/worker.py` operations separately use Marzban's
authenticated management API for provisioning, quota/expiry and inbound selection.
It preserves existing protocol credentials and never changes proxy core config.
There is no application background synchronization or stale subscription cache.

`rendering/profiles.py` parses supported VLESS, Shadowsocks, Trojan and VMess links
into immutable profiles. It validates UUIDs, addresses, REALITY fields, transport
metadata and ciphers. Ten protocol/transport combinations are supported. New CDN
families reject literal origin IPs; direct Trojan requires IPv6 REALITY. Standard
IPv6 Shadowsocks preserves the per-user AEAD cipher. Unsupported links fail closed.
XHTTP `extra` is never copied; unrelated extra fields are not globally removed.

`rendering/renderers.py` rebuilds base64 URI lines or an Xray JSON config array.
TLS verification stays on, MUX off, IPv6 literals bracketed and incompatible Vision
flow omitted from XHTTP/WS/gRPC/Trojan. Formats and original fixtures stay frozen.
New representations must be opt-in instead of replacing an established format.

The SSH CLI separates nonsecret inventory from credential output. Link commands
require a terminal or an explicitly chosen new private file. The root-owned host
dispatcher retains secrets inside the API container; backup snapshots and the
vault-key environment remain on the VPS. No additional management service runs.

Same-VPS host networking uses loopback 18000 for Keyholder and 8000 for Marzban.
Nginx owns public TLS/routing/Java homepages; Cloudflare provides the Titan CDN.
Admin/health stay private. The browser Marzban panel uses its existing login on
edge's `/dashboard/`. One worker keeps rate limits coherent without Redis.
Domain, path, DB and vault-key preservation are required across future VPS moves.
Multi-node orchestration, billing, queued jobs, failover, per-operator identities,
off-host scheduled backups and CI deployment are not implemented.
