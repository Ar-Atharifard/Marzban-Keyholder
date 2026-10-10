# Management improvements and protected panel plan

Implemented operator commands are documented in `scripts/admin/README.md`.
Subscription/API compatibility and release rules are in `COMPATIBILITY.md`.
The public panel plan below is prepared; it is not active until Cloudflare setup
and validation are complete. Current SSH panel access remains available.

## Public browser access

The owner selected `edge.javatechpack.ir`, protected by Cloudflare Access and then
Marzban login. The administrator email is the identity allowed through Access,
not necessarily the account used to administer the Cloudflare zone. Keep the exact
email allowlist in Cloudflare/private operations records, not committed source.
Protect the entire hostname and all paths, including API/static/WebSocket routes.
Never attach Access protection to the customer subscription hostname.

Prefer a small Cloudflare Tunnel connector to a loopback-only panel gateway,
with **Protect with Access** enabled so the connector validates application JWTs.
No public origin panel port or VPS firewall change is needed. This prevents origin
IP bypass, unlike adding only a public Nginx vhost and an edge login screen.
The existing subscription/gRPC ingress and Marzban proxy ports remain untouched.

A complex entry path is an additional privacy gate, not a replacement for Access.
The prepared loopback Nginx template issues a Secure/HttpOnly/SameSite entry cookie
only at a random bookmark path. Other panel paths return 404 without the cookie.
The normal Marzban path/assets are preserved after entry, avoiding brittle upstream
frontend rewrites or a Marzban restart. Access authenticates before this gate;
Marzban login is still required afterwards. Keep the bookmark privately; it is not
published in this repository. A browser's final URL may use `/dashboard/`, but
knowing that URL alone does not open its login screen.

### Cloudflare prerequisites

1. Zero Trust → Access → Applications: add a Self-hosted application for the whole
   `edge.javatechpack.ir` hostname. Add an Allow policy containing only the owner's
   chosen email(s); no Everyone or Bypass policy. Use an existing identity provider
   with MFA where available, or email one-time PIN for initial setup.
2. Create a named Cloudflare Tunnel for the panel. Do not publish its hostname route
   before the Access application exists. The connector token is a secret: place it
   directly in a root-only file on Braavos, never in chat, Git or shell history.
3. Route only `edge.javatechpack.ir` to `http://127.0.0.1:18081`. Enable origin
   **Protect with Access**, using the correct team and application audience.
   Remove/replace the existing edge DNS record as required by the tunnel; do not
   change Keyholder/titan/sealord DNS or their Origin Rules.
4. Keep BIC/bot protections for this browser hostname as appropriate. Add a cache
   bypass for the whole panel hostname; do not cache authenticated panel responses.
5. Validate anonymously, with a disallowed identity, with an allowed identity, and
   through origin bypass attempts. Missing entry cookie should return 404 even
   after Access login. Verify login, user management, logout, static assets and
   WebSockets. Do not use real customer creation as an incidental validation.

Affected components: a loopback gateway listener and one bounded connector.
Nginx graceful reload can add the listener without restarting Marzban. Connector
failure affects browser administration only; SSH access and customer proxies keep
working. Rollback removes the tunnel route/stops only its connector, restores the
previous gateway file **in place**, syntax-checks and reloads Nginx. Keep Access
protection during rollback, and retain the private bookmark/connector credentials
securely. No production exposure should precede owner allowlist configuration.

References: [Publish a protected application](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/),
[Origin JWT validation](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/origin-parameters/#access).

## Prioritized usage and management improvements

| Priority | Improvement | Reason / decision |
|---|---|---|
| Now | Freeze URL/render/API contracts and CLI workflows | Implemented without an API change |
| Now | Protected browser panel with a private entry bookmark | Owner selected Access; dashboard prerequisites remain |
| Next | Encrypted off-host scheduled backups + restore drills | Owner must choose storage, retention, acceptable data loss and downtime |
| Next | Customer link storage in a password manager | Lost raw URLs cannot be recovered from hashes; CLI saving is explicit |
| Next | Delivery alerts separate from DB health | Catch Marzban, Cloudflare, certificate and protocol failures |
| Next | Private canonical Git remote + mandatory CI checks | Prevent ad-hoc deployment from a dirty server checkout |
| Later | Small Keyholder admin web screen behind Access | Create/copy links from a phone without exporting the global API key |
| Later | Per-operator identity and sanitized mutation audit | Current API has one administrator key, not individual roles |
| Later | Reconciliation report for missing/disabled upstream users | Read-only report first; no bulk correction without review |
| Later | Idempotent attach API / uniqueness policy | CLI preflight is not atomic; decide whether shared upstream mappings are allowed |
| Later | Quota/expiry convenience commands | Marzban remains authoritative; owner must define product policies |
| Later | Notification/billing/plans/multi-node work | Requires product decisions; not implemented by these tools |

Avoid building a second full proxy panel. Marzban owns users, credentials, quotas,
expiry and inbounds. Keyholder owns durable customer subscription identity,
provider mapping and rendering. Disabling Keyholder delivery does not revoke
already-downloaded Marzban access. A future web screen should make this distinction
clear and never silently rotate links, expand permissions or expose the admin key.

## Prepared server files and token placement

`/opt/braavos-panel` is root-only and holds `access.json` (private bookmark/cookie),
`nginx.fragment.conf`, `nginx.candidate.conf`, a pinned restricted
`docker-compose.json`, and a nonsecret `deployment.json` record. The private gate
and actual Nginx candidate were tested. The connector is not started and the live
gateway configuration is unchanged. Get the private bookmark interactively using
`keyholder panel-url`; it reports that public access is not active yet.

After creating the Tunnel, copy its connector token from the dashboard and enter it
**directly on Braavos**, without pasting it into chat or putting it on a command line.
In an interactive `ssh braavos` session (bash):

```bash
umask 077
read -rs -p 'Tunnel token (hidden): ' PANEL_TUNNEL_TOKEN
printf '\n'
printf '%s' "$PANEL_TUNNEL_TOKEN" > /opt/braavos-panel/tunnel-token
unset PANEL_TUNNEL_TOKEN
chown 65532:65532 /opt/braavos-panel/tunnel-token
chmod 600 /opt/braavos-panel/tunnel-token
```

The parent directory stays root-only; the secret file is readable by the connector's
nonroot UID through a read-only bind mount. Do not run the dashboard's example command
with its token in argv. No token is embedded in Compose or Git. Never overwrite an
existing active connector token without reviewing rotation/reconnection behavior.

The prepared connector uses host networking to reach loopback 18081, drops all
capabilities, uses no-new-privileges/read-only root, caps memory at 128 MiB/processes
at 128, binds its metrics to loopback 20001, and rotates Docker logs. These are
ceilings, not reserved RAM. Its image is pinned by registry digest. It opens no
public listening port; outbound Cloudflare Tunnel connectivity still needs testing.

Before activation, verify the entire hostname Access policy, the correct
application audience/team under Protect with Access, and the token file. Take a
fresh gateway backup and regenerate the candidate from the **current** active
configuration (the prepared candidate may become stale). Syntax-check, write the
bind-mounted file in place and gracefully reload Nginx. Start only the dedicated
panel connector after those gates. Validate public authentication and private
bookmark behavior; record readiness before setting `access.json` active to true.
Do not activate it simply because the token file exists.
