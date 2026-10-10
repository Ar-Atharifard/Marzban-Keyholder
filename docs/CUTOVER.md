# Marzban-only cutover candidate

This is preparation, not an executed deployment. The owner approved retiring
Hiddify customers/links, retaining current proxy ports with Nginx on 80/443, and
enabling all five current Marzban profiles. Use `braavos` for Hiddify and host administration;
use `braavos-keyholder` for the Keyholder workspace. Never download production
databases, certificates, credentials or private subscription paths to development.

## Verified dependencies

- Hiddify HAProxy owns port 80; Hiddify's `rpxy-l4` owns port 443.
- The existing `braavos-gateway` already runs Nginx 1.30.5 on TLS port 2053,
  forwarding an existing private gRPC location to Marzban on loopback 12084.
- Its certificate is Cloudflare Origin CA, valid through October 2041. This is
  not evidence of public-browser trust or of correct external CDN configuration.
- Keyholder is loopback 18000; Marzban's API is loopback 8000.
- Marzban proxy ports are REALITY TCP 8443, XHTTP 9443, IPv6 TCP 10443 and
  IPv6 Shadowsocks 10444 (aes-128-gcm). Preserve them during the initial cutover
  unless the owner explicitly accepts changing downloaded client configurations.
- Hiddify has enabled services plus watchdog, auto-update, daily and reboot
  reinstall cron jobs. Stopping its units alone is not a reliable retirement.
- The gateway has an existing static fallback. Its purpose and all accepted
  hostnames must be established before replacing that fallback or virtual hosts.

## Candidate ingress

Reuse the existing gateway instead of adding another server. The local
`deploy/nginx.conf.template` proposes ports 80/443 plus transitional 2053,
unchanged gRPC routing and `/s/` forwarding to Keyholder without rewriting the
path or query. Admin and health routes remain private. Access logs are disabled;
error logs are suppressed because they can contain subscription tokens.

This template is intentionally not deployable: public hostname and existing
private gRPC matcher are placeholders, and fallback behavior needs review.
The candidate passed `nginx -t` locally in an isolated, network-disabled Nginx
1.29.5 container with synthetic hostname, gRPC path and certificate. This does
not validate production Nginx 1.30.5, public TLS, routing or proxy connectivity.
The hostname must match the existing stable subscription address, TLS SANs and
gRPC client SNI. Preserve any additional production virtual hosts after inventory.
For Cloudflare-proxied use, validate strict origin TLS and the external origin
port/routing rule. For direct public access, provision a publicly trusted
certificate and a renewal process independent of Hiddify before switching.
Do not give Nginx and a REALITY inbound the same IP/port combination.

## Gates before production changes

1. Hiddify links are intentionally retired. Inventory recovery dependencies before
   stopping services; no Hiddify customer migration is required.
2. All five current profiles are approved for existing/new Keyholder customers.
   Confirm migration preserves IDs, token hashes, mappings and customer status.
3. Verify actual public domain/path ownership, CDN origin port and routing,
   certificate SANs, all gateway hostnames, and client connectivity. Do not rotate
   subscription tokens or create test customers incidentally.
4. Record a reviewed release commit and immutable image identities. Build on the
   workstation; do not build the dirty production checkout or stress VPS memory.
5. Create private on-VPS recovery snapshots of Keyholder SQLite (including WAL),
   Marzban database/configuration, Hiddify database/generated configuration,
   gateway config/certificates, systemd units and maintenance jobs. Check storage
   capacity and recovery permissions first. Retain existing images. Record active
   firewall rules without altering SSH or networking. Rehearse recovery securely.

## Staged execution after approval

1. Deploy Keyholder alone using the reviewed release and approved migration.
   Validate private health/admin access and existing canary subscriptions in both
   formats. Verify token identity and XHTTP `extra` removal. This stage can briefly
   interrupt subscription refreshes; existing proxy traffic is independent.
2. Prepare a rendered Nginx candidate on the VPS without replacing the active
   file. Preserve the current gRPC matcher and any required hosts/static routes.
   Syntax-check with the actual running Nginx version and certificate mounts.
   Validate subscription proxying on an approved unused loopback test listener;
   an Nginx syntax check alone is not an end-to-end routing test.
3. In a maintenance window, prevent Hiddify maintenance jobs from restarting it
   and stop only the inventoried Hiddify services. Preserve their files and data.
   Confirm 80/443 are free, activate the gateway candidate and reload Nginx.
   Keep 2053 until its upstream dependency has been checked. Existing Hiddify
   sessions are interrupted at this point; Marzban proxy ports remain unchanged.
4. Validate public subscriptions, unchanged URL/token, both render formats,
   REALITY TCP/XHTTP/IPv6, existing gRPC and Shadowsocks with supported clients.
   Confirm private admin routes are unreachable and no token-bearing logs are
   produced. Observe memory, swap, container health and certificate behavior.
5. Remove Hiddify only after a successful, owner-accepted observation period.
   Review its uninstall lifecycle first: it must not remove shared certificates,
   Marzban data, gateway files, Docker, SSH/firewall state or retained backups.
   Permanent deletion is a distinct irreversible step, not part of the first
   traffic switch. Do not blindly execute an upstream uninstall script.

## Rollback

Before permanent deletion, restore the previous gateway configuration and reload
it to release 80/443, then restart the exact previously active Hiddify units and
restore their prior maintenance-job state. Verify original listeners and customer
links. Do not restart Docker globally. If Nginx cannot reload, retain the old
workers/config and restore before further attempts; verify listener ownership.

Keyholder rollback uses the previous immutable image plus the reviewed database
recovery procedure in `OPERATIONS.md`. Preserve post-cutover database state before
restoration; restoring a snapshot loses subsequent administrative changes.
After deleting Hiddify, restoration requires its private recovery artifacts and
is slower. That risk must be accepted before deletion.
