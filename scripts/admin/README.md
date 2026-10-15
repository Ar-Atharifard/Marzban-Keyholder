# Operator CLI

Install the project with `uv sync` or a built wheel; its entrypoint is `keyholder`.
The old `scripts/admin/cli.py` entrypoint remains a checkout compatibility wrapper.
Commands communicate over SSH; administrator credentials remain in the API container.

## Installation and configuration

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
| Monitoring state / immediate check | `keyholder monitor status`, `keyholder monitor run` |
| Configure / inspect / test Telegram alerts | `keyholder alert-bot configure`, `keyholder alert-bot status`, `keyholder alert-bot test` |
| Configure / test outage heartbeat | `keyholder heartbeat configure`, `keyholder heartbeat test` |
| Configure / inspect / test management bot | `keyholder management-bot configure`, `keyholder management-bot status`, `keyholder management-bot test` |
| Configured backends / registration | `keyholder backend list`, `keyholder backend register` |
| Panel inventory | `keyholder upstream users`, `keyholder upstream inbounds` |
| Canonical customers / history | `keyholder customer list`, `keyholder customer list --history` |
| Attach account / retrieve same URL | `keyholder user attach alice`, `keyholder customer link alice` |
| Customer / compatible profiles | `keyholder customer show alice`, `keyholder customer check alice` |
| Register missing panel accounts | `keyholder upstream sync` |
| Provision user with private identity | `keyholder user create customer_001 --name 'Alice Example' --telegram @alice --phone +989121234567 --quota-gb 20 --days 30 --protocols vless trojan` |
| Update plan / traffic | `keyholder user update alice --quota-gb 30 --days 30`, `keyholder user usage alice` |
| Explicit usage reset | `keyholder user reset-usage alice --confirm` |
| Select protocol inbounds | `keyholder user inbounds alice --protocol trojan --tags 'TROJAN TLS'` |
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
now and does not reset traffic. `user inbounds` replaces only the selected protocol's
inbounds, preserving credentials. Local disable/revoke does not stop previously
imported proxies; use the provider to enforce access. `upstream reconcile --confirm` is a
legacy recovery tool, not daily maintenance. Infrastructure deployment, user
bulk deletion and automatic restore are intentionally outside this CLI.

Install the manual locally with:

```console
sudo install -Dm0644 docs/keyholder.1 /usr/local/share/man/man1/keyholder.1
sudo mandb
```
