# Operator CLI

Install the project with `uv sync` or a built wheel; its entrypoint is `keyholder`.
The old `scripts/admin/cli.py` entrypoint remains a checkout compatibility wrapper.
Commands communicate over SSH; administrator credentials remain in the API container.

Customer selectors accept an exact username, customer ID, phone, Telegram handle,
or private name. Quote names containing spaces. Duplicate names require a username
or ID; changing a private name never changes the Marzban username.

```sh
keyholder customer show "Full Name"
keyholder customer list --brief
keyholder customer list --brief --search "part of a name"
```

The management bot's `/directory [PAGE] [SEARCH]` shows only usernames and private
names; `/show "Full Name"` opens one customer. Searches match usernames and names.
`/customers [PAGE] [SEARCH]` returns the usual details with the same search filter.

## Installation and configuration

After pulling a release on the VPS, refresh its separately installed CLI and manual:

```sh
cd /srv/keyholder
sudo python3 scripts/admin/install_cli.py
keyholder user inbounds
```

The server wrapper dispatches locally by default. It needs no Python packages and
does not restart services, deploy the API, modify users or change the firewall.
Pulling alone does not update `/usr/local/bin/keyholder` or its installed modules.
Keep the server CLI/worker and deployed API on compatible releases.

Copy `host.py`, `worker.py` and `../backup_database.py` to a root-owned private
server directory such as `/usr/local/lib/keyholder-admin/`. This requires the
matching Keyholder release in its API container. Install Python 3.10+ for the
stdlib dispatcher; the container worker uses the application's Python environment.

A workstation JSON config selected by `KEYHOLDER_ADMIN_CONFIG` supports:

```json
{"host":"keyholder-server","ssh_config":"/home/operator/.ssh/config","remote_path":"/usr/local/lib/keyholder-admin/host.py","panel_target":"127.0.0.1:8000","panel_path":"/dashboard/"}
```

Default SSH alias: `keyholder-server`; `--host` overrides it. Checkout-local
`.private/admin.json` can hold personal defaults and is excluded from release
artifacts. `panel` opens a loopback SSH recovery tunnel, independent of a public
private-prefix bookmark.

The dispatcher reads `host.json` beside itself or `KEYHOLDER_HOST_CONFIG`.
The file must be root-owned, mode 0600 and not a symlink. Example:

```json
{
  "api_container":"keyholder-api-1",
  "status_containers":["keyholder-api-1","marzban-marzban-1"],
  "container_python":"/app/.venv/bin/python",
  "api_url":"http://127.0.0.1:18000",
  "env_file":"/etc/keyholder/keyholder.env",
  "backup_dir":"/var/backups/keyholder",
  "panel_access_file":"/etc/keyholder/panel-access.json",
  "extra_backups":{"xray.json":"/var/lib/marzban/xray_config.json"},
  "sqlite_backups":{"marzban.sqlite3":"/var/lib/marzban/db.sqlite3"}
}
```

Backup destinations are filenames, not paths. Add the private panel access file
and ingress configuration when those are part of your recovery plan. Verify
`status`, `health`, `doctor` after installation; never rotate real credentials as
a smoke test. The default dispatcher assumes Docker and a named `/data` volume.
Other runtimes need a separate host dispatcher, not API contract changes.

## Commands

| Task | Command |
|---|---|
| New local private env | `keyholder config init` |
| Service / DB checks | `keyholder system status`, `keyholder system health`, `keyholder system doctor` |
| Live system metrics | `keyholder system metrics` |
| Alert controls and rules | `keyholder monitor controls`, `keyholder monitor ack KEY`, `keyholder monitor silence KEY --hours 2`, `keyholder monitor rule-disable RULE --confirm` |
| Monitoring state / immediate check | `keyholder monitor status`, `keyholder monitor run` |
| Configure / inspect / test Telegram alerts | `keyholder alert-bot configure`, `keyholder alert-bot status`, `keyholder alert-bot test` |
| Configure / test outage heartbeat | `keyholder heartbeat configure`, `keyholder heartbeat test` |
| Configure / inspect / test management bot | `keyholder management-bot configure`, `keyholder management-bot status`, `keyholder management-bot test` |
| Configured backends / registration | `keyholder backend list`, `keyholder backend register` |
| Panel inventory | `keyholder upstream users`, `keyholder upstream inbounds` |
| Canonical customers / history | `keyholder customer list`, `keyholder customer list --history` |
| Attach account / retrieve same URL | `keyholder user attach alice`, `keyholder customer link alice` |
| List individual profiles / retrieve one URI | `keyholder customer configs alice`, `keyholder customer config alice CONFIG_ID` |
| Customer / compatible profiles | `keyholder customer show alice`, `keyholder customer check alice` |
| Register missing panel accounts | `keyholder upstream sync` |
| Provision user with private identity | `keyholder user create customer_001 --name 'Alice Example' --telegram @alice --phone +989121234567 --quota-gb 20 --days 30 --inbounds default` |
| Update plan / traffic | `keyholder user update alice --quota-gb 30 --days 30`, `keyholder user usage alice` |
| Explicit usage reset | `keyholder user reset-usage alice --confirm` |
| Export owner-only DNSTT profile | `keyholder personal dnstt --save-link ./owner-dnstt.json` |
| Local administrator MASQUE recovery | `keyholder personal masque` |
| Select protocol inbounds | `keyholder user inbounds alice --protocol trojan --tags 'TROJAN TLS'` |
| Numbered picker | `keyholder user inbounds alice` |
| List available inbounds | `keyholder user inbounds` |
| View / replace defaults for future users | `keyholder user defaults`, `keyholder user defaults --select 1,3,5 --confirm` |
| Scripted replacement | `keyholder user inbounds alice --select 1,3,5 --confirm` |
| Update private identity / clear contact | `keyholder customer update customer_001 --name 'Alice Example' --telegram @alice`, `keyholder customer update customer_001 --clear-phone` |
| Rename / remap without URL rotation | `keyholder customer rename customer_001 'Alice'`, `keyholder customer remap customer_001 replacement` |
| Pause local delivery / resume | `keyholder customer disable alice`, `keyholder customer enable alice` |
| Revocation / token rotation | `keyholder customer revoke alice --confirm`, `keyholder customer rotate-token alice --confirm` |
| Recovery snapshot | `keyholder system backup` |
| Private bookmark / SSH tunnel | `keyholder panel url`, `keyholder panel open` |
| Complete command reference | `keyholder help`, `keyholder help RESOURCE ACTION`, `man keyholder` |

Global `--backend ID` selects an account namespace. Commands accepting a customer
selector support customer UUID, exact upstream username, Telegram handle/ID or
phone. Customer UUIDs remain unambiguous. HTTP-source providers support local
customer/link operations but not Marzban-specific provisioning/inventory commands.

`user create` defaults the private customer name to the Marzban username when
`--name` is omitted. `user attach USER --name ...` does the same when attaching an
existing panel user. Telegram and phone are nullable but unique when present;
use international `+digits` phone format. These fields stay in Keyholder and are
never copied to Marzban or customer subscription output.

`user attach` is idempotent. Links require an interactive terminal or explicit
`--save-link /new/private/file.json`; overwrite/symlinks are refused. `--json`
returns nonsecret inventory only. After an uncertain mutation response, check
state rather than repeating a rotation or creating another upstream account.

Zero quota/days explicitly means unlimited. `user update --days` sets expiry from
now and does not reset traffic. The numbered picker replaces the whole inbound
selection; the advanced `--protocol --tags` form changes just one protocol.
Both preserve existing credentials. Telegram: `/inbounds USER`, then `/select 1,3,5`,
then the returned `/confirm CODE`. `/cancel` leaves selections unchanged. Numbers
belong to that catalog, not permanent identifiers. Stale selections are rejected.
Each entry is one Marzban inbound. The picker lists its generated host/ECH/fragmentation
variants and totals the selected connection profiles before confirmation. OWNER-specific
rules apply only when viewing OWNER; the global/default catalog uses ordinary-user rules.
The usage-information row is excluded. Dynamic templates that cannot be predicted are
marked unavailable instead of showing an invented total. Totals require provider-authoritative
mode (`KEYHOLDER_PROFILE_SOURCE=upstream` or `marzban`); legacy customer-policy mode
may further restrict delivery. This previews delivery, not connectivity.

Creation accepts `--inbounds 1,3,5`, `all`, or `default` (also used when omitted).
Protocols are inferred. `all` means the current catalog of enabled public host entries,
not a rule enabling future inbounds. Use `user inbounds` to see numbers first.
`user defaults --select 1,3,5 --confirm` stores initial choices per backend in the DB;
existing users remain unchanged. Before any saved override, `KEYHOLDER_DEFAULT_INBOUND_TAGS`
provides the initial defaults. Empty or unavailable selections fail before creating an account.
Legacy `--protocols`/`--inbound-tags` still work; do not combine them with `--inbounds`.
Panel-created users use the panel's selections; no background process overwrites them.
The bot accepts `/create USER quota=20 days=30 inbounds=default` and `/select all` or
`/select default` in its existing picker. `KEYHOLDER_CDN_ECH_KINDS` limits generated ECH alternatives;
`KEYHOLDER_CDN_ECH_FULL_CATALOG` lists `backend-id/username` exceptions for the full
set of variants, without granting additional upstream inbounds.

Local disable/revoke does not stop previously
imported proxies; use the provider to enforce access. `upstream reconcile --confirm` is a
legacy recovery tool, not daily maintenance. Infrastructure deployment, user
bulk deletion and automatic restore are intentionally outside this CLI.

Install the manual locally with:

```console
sudo install -Dm0644 docs/keyholder.1 /usr/local/share/man/man1/keyholder.1
sudo mandb
```

Individual configuration IDs identify the exact published URI. A profile change can
change its ID; list again before selecting. A unique profile kind is also accepted.
Exports use the same filtering and ECH settings as subscriptions and omit the usage
label. `--save-link FILE` saves the selected URI privately. No token is rotated.

In the allowlisted private management chat, use `/link alice`, `/configs alice`,
then `/config alice CONFIG_ID`. Only these explicit commands return bearer links;
other replies redact credentials. Treat Telegram history as sensitive and protect
the administrator account. DNSTT remains an SSH-only personal command.

## Public subscription TLS

`keyholder tls configure HOST --email EMAIL` privately accepts the scoped Cloudflare
DNS token and starts certificate issuance. `keyholder tls status` shows expiry and
job state; `keyholder tls issue` retries issuance/renewal. DNS migration is separate.
See [domestic entry](../../docs/domestic-node.md) for routing and recovery.

## Personal MASQUE recovery

Install a Linux release from [Aether](https://github.com/CluvexStudio/Aether/releases)
and verify its archive against the release checksum. Run
`keyholder personal masque --binary /absolute/path/to/aether`. The private operator
configuration can set `aether_binary` and `masque_state` to avoid repeating paths.

This starts HTTP/2 with fragmentation on SOCKS `127.0.0.1:1819`; it does not change
system proxy settings. Point your administrator client at that local SOCKS proxy.
Ctrl+C stops it. Try `--no-fragment` or `--ipv6` when appropriate. Identity keys stay
in the private state directory. First registration and subsequent startup checks
need Cloudflare's WARP API; a filtered API can cause long retries or failure.
It uses Cloudflare's exit, independently of your VPS, Marzban quotas and routing.
