# Executed Marzban-only cutover and recovery

The owner approved complete Hiddify link retirement, all five current Marzban
profiles, and Nginx ingress. The cutover and Hiddify removal were executed on
October 10, 2026. Use `ssh braavos` for host administration and
`ssh braavos-keyholder` for the preserved project workspace. Never copy customer
credentials, databases, certificates or subscription URLs to the workstation.

## Current routing and validation

Nginx owns 80/443 and keeps 2053 because titan/sealord Cloudflare Origin Rules
still use it. Their existing private gRPC matcher and static fallback were
preserved. Keyholder's stable hostname and `/s/{token}` path forward to loopback
18000 without rewriting path or query. Admin and health paths return 404 at
public ingress. No access logs or token-bearing error logs are produced.

Marzban remains on its original ports: REALITY TCP 8443, XHTTP 9443, IPv6 TCP
10443, IPv6 Shadowsocks 10444 (`aes-128-gcm`), and loopback gRPC 12084.
Its container was not restarted and its configuration/users were not changed.
All five profiles passed real HTTPS requests via temporary Xray clients. Both
subscription render formats and XHTTP-only `extra` removal were verified using
an isolated clone with a synthetic token; the live customer token was unchanged.

The independent Cloudflare Origin CA certificate covers the apex and wildcard,
expires in October 2041, and lives outside the removed Hiddify directory. It is
for Cloudflare origin verification, not direct browser trust. The owner reported
Keyholder Full (strict) and disabled Bot Fight Mode. Normal client/browser checks
reach Keyholder with `DYNAMIC` cache status; Python-urllib still receives 403.
See `CLOUDFLARE.md` for event investigation and explicit cache bypass.

## Private recovery inventory

Recovery directory: `/var/backups/braavos-cutover/20261010T163352Z` (root-only).
Never download or publish it. Inspect `manifest.json` for artifact hashes.

- `keyholder.sqlite3`: original revision 0001 snapshot.
- `keyholder-predeploy.sqlite3`: fresh pre-migration snapshot, checked integrity.
- `marzban.sqlite3`: consistent online SQLite backup, isolated restore verified.
- `recovery-files.tar`: old Hiddify installation, generated configuration and
  environment; old gateway certificates/configuration; dirty Keyholder workspace;
  Marzban installation; systemd units and cron/configuration hooks.
- `hiddify-mysql.sql`, `hiddify-mysql-precutover.sql`, `hiddify-mysql.cnf`:
  logical recovery artifacts. `hiddify-data-cold.tar` contains the final consistent
  physical data directory after all Hiddify services were stopped.
- `marzban-runtime-config.tar`: original Xray configuration and binary.
- `nginx-precutover.conf`, `root-bashrc.before`, `disabled-hiddify-cron/`, and
  `retirement-file-metadata.json`: old ingress, shell hooks, jobs and symlink targets.
- `iptables.rules` and `ip6tables.rules`: read-only snapshots; no firewall rules
  were modified. Network tuning was preserved as `/etc/sysctl.d/braavos.conf`.

Images were retained with `braavos-rollback/...` tags and immutable identities.
Release `deployment.json` records the previous API image. Backups are on this
same VPS: disk/server loss remains a risk until encrypted off-host storage is
chosen. Scheduling, retention and recovery objectives need an owner decision.

## Removal details

Hiddify's eight active services were stopped and disabled; all its unit files,
watchdog/update/reinstall/daily jobs, application directory, CLI links, profile
hooks, completion, sudoers entry and obsolete parked Nginx configuration were
removed. The upstream uninstaller was not used because it broadly purges shared
packages. Shared MariaDB/Redis/Nginx packages remain inactive, allowing recovery;
they do not constitute a running Hiddify installation. Docker, Marzban, SSH,
firewall and routing rules were preserved.

## Targeted rollback

A code-only Keyholder rollback recreates only the API with the previous pinned
image and current database, provided schema compatibility is established. For a
revision-0001 restore, stop only Keyholder, preserve a fresh copy of current data,
restore the selected snapshot with UID/GID 10001 and correct permissions, and
start the original image. Restoring loses subsequent administrative changes;
obtain owner approval for that data-loss decision.

Gateway hardening rollback removes its production override and recreates only
`gateway` from its original Compose file, retaining current Marzban-only routing.
This briefly disconnects gRPC clients, which should reconnect. Other Marzban
proxy ports are independent. Do not restart Docker globally.

Restoring retired Hiddify requires a separately approved maintenance operation:

1. Restore `nginx-precutover.conf` **in place** in its existing bind-mounted file,
   syntax-check and reload Nginx, then verify 80/443 are released. If necessary,
   stop only the gateway. Keep customer impact explicit.
2. List archive members and selectively extract the old Hiddify application and
   its units/hooks from `recovery-files.tar`. Never extract the whole archive over
   current Keyholder, Marzban or gateway configuration.
3. Restore `hiddify-data-cold.tar` over the recovered Hiddify data directory,
   preserving ownership. This is the final stopped-state database snapshot;
   do not overlay it with older live files. Shared OS packages/UIDs were retained.
4. Restore CLI links from `retirement-file-metadata.json`, shell hooks and the
   original root bashrc after checking syntax. Keep network tuning values intact.
5. Reload systemd, enable/start only the originally active Hiddify units, validate
   listeners and panel, then restore maintenance jobs last.

Hiddify recovery is slower than rollback before removal. No automatic revival
or recovery job is installed. The generated local Nginx template uses synthetic
placeholders; never deploy it over the rendered production file without preserving
private gRPC matching, certificates and fallback behavior.
