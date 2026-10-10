# Management and browser access

## Public Marzban panel

The owner selected a simple public panel after reporting Cloudflare Zero Trust
unavailable. The URL is **https://edge.javatechpack.ir/dashboard/**; `/` redirects
there. Sign in with the existing Marzban administrator credentials. The login
screen is public; Marzban authentication protects administrative API operations.
There is no Access application, extra Nginx password or private bookmark gate.
The previous Access/tunnel preparation remains inactive and is superseded.

The existing Nginx gateway terminates HTTPS on 443 and forwards the original paths
to Marzban on `127.0.0.1:8000`. Assets, API paths and WebSocket upgrade headers are
preserved. Marzban and Keyholder containers need no restart. No panel connector,
new proxy port, firewall rule or public Keyholder administrator API was added.
Customer delivery remains exclusively through the existing Keyholder subscription
URL. Never give customers Marzban's upstream subscription URL instead.

`deploy/panel-public.conf` is the reusable Nginx fragment. Responses use no-store;
access/error request logging is suppressed to avoid credential leakage. Login
requests at `/api/admin/token` have a hostname-wide 10/minute limit with a burst
of 10; excess returns 429. It does not trust forwarded client IPs. This bounded
single-admin policy also limits legitimate attempts, so wait before retrying after
429. Use a unique strong Marzban password in a password manager. Cloudflare/browser
protections may remain enabled for this browser-only hostname.

Cloudflare requirements:

1. Keep `edge.javatechpack.ir` as a proxied DNS record pointing to Braavos.
2. Use HTTPS origin port 443; no titan/sealord port-2053 override may match edge.
3. Set a hostname-scoped SSL configuration rule to **Full (strict)** for edge,
   because the existing Cloudflare Origin CA certificate covers this hostname.
4. Use a cache bypass rule for the entire edge hostname. Origin no-store is set,
   but future Cache Everything rules must not override it.

[Cloudflare Full (strict)](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/)
validates the origin certificate. Existing titan/sealord and subscription settings
must retain their current matching rules.

## Validation and rollback

The complete candidate passed syntax validation in the running Nginx image.
An isolated bounded test verified dashboard HTML/static assets and unauthenticated
administrative API rejection. Activation uses an in-place config write and a
graceful Nginx reload. Direct-origin SNI probes verify panel 200, admin API 401,
Keyholder invalid-subscription 404 and public Keyholder admin 404.
Public Cloudflare checks passed for dashboard HTML, all referenced static assets,
admin API 401 and invalid subscription 404. Browser-style request headers are
needed for panel assets under existing Cloudflare browser protections; a generic
Python asset request was blocked. Real administrator login still needs owner
verification. No real user was created or administrator credential downloaded.

Private rollback backups are under `/opt/braavos-panel/nginx.before-public-*.conf`.
Restore the chosen file **in place** to `/opt/braavos-gateway/nginx/nginx.conf`,
run `docker exec braavos-gateway nginx -t`, then
`docker exec braavos-gateway nginx -s reload`. A rename over this bind-mounted
file would leave Docker reading the old inode. Rollback removes browser access;
customer delivery and private SSH access continue. No Marzban restart is needed.
`/opt/braavos-panel/access.json` now records the standard public URL and activation
state; previous tunnel configuration is not used and no tunnel token is required.

## Daily workflow

1. Open the public dashboard and create the Marzban user with the intended quota,
   expiry, VLESS/Shadowsocks permissions and enabled inbounds.
2. Run `keyholder create USERNAME --name 'Customer name'` from the workstation.
   The CLI attaches the existing active user and defaults to all five profiles;
   it refuses missing selected profiles. Save the issued URL privately and give
   that Keyholder URL to the customer.
3. Use `keyholder list`, `show`, `check`, `disable`, `enable`, `remap` and `backup`
   as documented in `scripts/admin/README.md`. `keyholder panel` remains the SSH
   recovery option; `keyholder panel-url` reports the public dashboard address.

The backend stores only token hashes: keep the original issued URL securely.
Renaming, changing policies or remapping must preserve it. Explicit rotation or
revocation invalidates it. See `COMPATIBILITY.md` for frozen contracts and release
rules. Disabling Keyholder delivery does not terminate already-downloaded Marzban
proxy access; manage that access in Marzban separately.

## Prioritized improvements

| Priority | Improvement | Reason / decision |
|---|---|---|
| Implemented | Frozen API/render/URL contracts and operator CLI | Preserve current compatibility; simplify management |
| Implemented | Simple HTTPS Marzban dashboard | Owner selected existing Marzban authentication |
| Next | Encrypted off-host scheduled backups and restore drills | Owner must choose storage, retention, acceptable data loss and downtime |
| Next | Password-manager storage for customer URLs | Raw URLs cannot be recovered from stored hashes |
| Next | Delivery alerts beyond database health | Detect Marzban, Cloudflare, certificate and protocol failures |
| Next | Private canonical Git remote and mandatory CI | Avoid ad-hoc deployment from the dirty server checkout |
| Later | Small authenticated Keyholder management UI | Phone-friendly link creation without exporting the global API key |
| Later | Per-operator identity and sanitized mutation audit | Current API uses one administrator key |
| Later | Read-only reconciliation report | Find missing/disabled upstream users before any correction |
| Later | Idempotent attach / upstream uniqueness policy | CLI duplicate preflight is not atomic |
| Later | Quota/expiry convenience commands | Owner defines product policies; Marzban remains authoritative |
| Later | Billing/plans/multi-node support | Requires separate product decisions |

Avoid a second full proxy panel: Marzban owns users, credentials, quotas, expiry
and inbounds. Keyholder owns durable customer identity, mappings and rendering.
