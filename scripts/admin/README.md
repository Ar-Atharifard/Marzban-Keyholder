# Operator CLI

`keyholder` manages customers over SSH. Credentials stay on the server.
Use `keyholder help RESOURCE ACTION` for every command's arguments; `man keyholder`
is the offline reference. On the server, commands dispatch locally by default.

## Install

On your workstation, install the project with `uv sync` or its wheel. Configure an
SSH alias and, optionally, a JSON file selected by `KEYHOLDER_ADMIN_CONFIG`:

```json
{"host":"keyholder-server","ssh_config":"/home/operator/.ssh/config","remote_path":"/usr/local/lib/keyholder-admin/host.py"}
```

Checkout-local `.private/admin.json` also supplies these defaults. `--host` overrides
the alias; `--backend ID` selects the provider namespace. `--json` returns nonsecret
results. A private name, exact username, customer ID, phone or Telegram handle can
identify a customer; duplicate names require a username or ID.

On the server, install the matching release's `host.py`, `worker.py` and
`scripts/backup_database.py` under `/usr/local/lib/keyholder-admin/`. The dispatcher
needs Python 3.10+; its worker uses the API container's Python. Refresh the CLI with:

```sh
sudo python3 scripts/admin/install_cli.py
keyholder system status
keyholder system health
keyholder system doctor
```

This updates CLI modules and the manual, without restarting services or deploying
the API. A Git pull alone does not update installed tools. Keep CLI, worker and API
versions compatible. The old `scripts/admin/cli.py` entrypoint remains supported.

The root-owned dispatcher reads mode-0600 `host.json` beside itself, or the path in
`KEYHOLDER_HOST_CONFIG`. Defaults assume Docker and a named `/data` volume:

```json
{
  "api_container":"keyholder-api-1",
  "status_containers":["keyholder-api-1","marzban-marzban-1"],
  "container_python":"/app/.venv/bin/python",
  "api_url":"http://127.0.0.1:18000",
  "env_file":"/etc/keyholder/keyholder.env",
  "backup_dir":"/var/backups/keyholder",
  "extra_backups":{"xray.json":"/var/lib/marzban/xray_config.json"},
  "sqlite_backups":{"marzban.sqlite3":"/var/lib/marzban/db.sqlite3"}
}
```

Backup keys are filenames, not paths. Add ingress configuration and required vault
keys to your recovery inventory. Other runtimes require a host dispatcher; they do
not require changing the public API.

## Daily use

```sh
keyholder user inbounds
keyholder user defaults
keyholder user create customer_001 --name 'Alice Example' --quota-gb 20 --days 30 --inbounds default
keyholder user attach existing_username
keyholder customer list --brief --search Alice
keyholder customer show customer_001
keyholder customer link customer_001 --save-link ./subscription.json
keyholder customer configs customer_001
keyholder customer config customer_001 CONFIG_ID --save-link ./profile.json
keyholder user usage customer_001
keyholder user update customer_001 --quota-gb 30 --days 30
keyholder user inbounds customer_001
keyholder system metrics
```

`user create` provisions a panel account; `user attach` reuses an existing account
and is idempotent. Omitted `--name` uses its username. Private names never rename
panel accounts. Phone and Telegram are nullable and unique when present; use
international `+digits` phone numbers. Update them with `customer update`, including
`--clear-phone` and `--clear-telegram`. Customer metadata stays out of subscriptions.

Links and individual URIs require a terminal or a new `--save-link FILE`; overwrites
and symlinks are refused. Configuration IDs describe exact published URIs and may
change when profiles change. List them again before selecting. Retrieving a link
never rotates it. After an uncertain mutation response, check state before retrying.

## Inbound selection

`user inbounds` lists available entries; adding a username shows that user's picker.
Choose comma-separated numbers, `all` or `default`, then review and confirm. Numbers
refer to the current catalog, not permanent IDs. Scripted changes use:

```sh
keyholder user inbounds customer_001 --select 1,3,5 --confirm
keyholder user defaults --select 1,3,5 --confirm
```

The picker replaces the whole selection, preserves credentials and rejects stale
catalogs. Advanced `--protocol PROTOCOL --tags TAG...` changes one protocol only.
`user create --inbounds` accepts the same choices and infers protocols; omitted means
`default`. `all` selects current enabled public hosts, not future additions.
Legacy `--protocols`/`--inbound-tags` remain supported; do not combine these forms.

Defaults are stored per backend and affect future CLI/bot users only. Before a saved
override, `KEYHOLDER_DEFAULT_INBOUND_TAGS` supplies them. Panel-created users retain
panel choices; no background process resets selections. Zero quota/days means
unlimited. Updating expiry calculates from now and does not reset traffic.

The picker previews generated profiles using subscription delivery rules, excluding
the usage row. Account exceptions require selecting that account. Dynamic templates
may have no preview. Totals require provider-authoritative mode; legacy policies can
further restrict output. A preview does not prove network connectivity.

## Other tools

- `keyholder help` lists all resources; detailed help and the manual cover flags.
- [Operations](../../docs/operations.md): releases, private panel, bots and monitoring.
- [Alert policy](../../docs/alerts.md): acknowledgement, silences, thresholds and repair.
- [Networking](../../docs/networking.md): delivery, personal MASQUE/DNSTT and experiments.
- [Domestic entry](../../docs/domestic-node.md): TLS renewal and tunnel recovery.
- [Recovery](../../docs/disaster-recovery.md): encrypted offsite backups and Ansible.

In the allowlisted management chat, use `/help`, `/directory`, `/inbounds USER`,
`/link USER`, `/configs USER` and `/config USER CONFIG_ID`. Explicit link commands
return secrets there; protect the chat and administrator account. `/cancel` abandons
a pending change. HTTP-source providers support customer/link operations, not panel
provisioning. Local disable/revoke stops delivery, not previously imported proxies;
enforce access in the panel. `upstream reconcile --confirm` is a legacy recovery
operation that can rotate links, not routine maintenance.
