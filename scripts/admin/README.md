# Keyholder operator commands

The workstation command is `~/.local/bin/keyholder`, linked to this folder's
`cli.py`. Ensure `~/.local/bin` is on PATH. On Braavos, `/usr/local/bin/keyholder`
is installed. Run `keyholder --help` or `keyholder COMMAND --help`. Workstation
commands use SSH alias `braavos`; root on the VPS uses `keyholder --local COMMAND`.
Secrets remain inside the API container. No manual curl or script invocation is
needed for routine customer management.

| Task | Command |
|---|---|
| Container state / database health | `keyholder status` / `keyholder health` |
| DB integrity, vault and inventory checks | `keyholder doctor` |
| Panel accounts / available inbound tags | `keyholder users` / `keyholder inbounds` |
| Canonical customers / revoked history | `keyholder list` / `keyholder list --history` |
| Customer details / supported live profiles | `keyholder show alice` / `keyholder check alice` |
| Attach or retrieve an existing panel account | `keyholder create alice --name 'Alice'` |
| Retrieve the same subscription URL | `keyholder link alice` |
| Register missing panel accounts, without rotation | `keyholder sync` |
| Create upstream user and attach subscription | `keyholder user-create alice --quota-gb 20 --days 30 --protocols vless vmess trojan shadowsocks` |
| Traffic per user/node | `keyholder user-usage alice` |
| Explicitly reset used traffic | `keyholder user-reset-usage alice --confirm` |
| Set quota / expiry from now | `keyholder user-update alice --quota-gb 30 --days 30` |
| Disable / enable upstream proxy access | `keyholder user-update alice --status disabled` / `--status active` |
| Select inbounds for one protocol | `keyholder user-inbounds alice --protocol trojan --tags 'TROJAN GRPC CDN TITAN' 'TROJAN REALITY IPV6'` |
| Disable all inbounds for one protocol | `keyholder user-inbounds alice --protocol trojan --tags` |
| Rename / change mapping, preserving URL | `keyholder rename alice 'Alice Smith'` / `keyholder remap alice replacement_user` |
| Pause / resume Keyholder delivery only | `keyholder disable alice` / `keyholder enable alice` |
| Permanently revoke local delivery | `keyholder revoke alice --confirm` |
| Explicitly replace a compromised token | `keyholder rotate-token alice --confirm` |
| Private recovery set on VPS | `keyholder backup` |
| Browser panel / SSH recovery tunnel | `keyholder panel-url` / `keyholder panel` |

A user created in the Marzban panel needs one initial `keyholder create USER`
registration (or `keyholder sync`). Afterwards `link`, `show` and `check` work.
This is an identity-registration step, not a profile or source-code change.
Use the exact, case-sensitive panel username. Repeating `create` keeps the same URL.

Selectors are a UUID or an unambiguous non-revoked Marzban username. `--json`
(before the command) works for nonsecret results. Listing/pagination never reveals
subscription credentials. The current panel is `https://edge.javatechpack.ir/dashboard/`.

`user-create` requires explicit quota and days: zero means unlimited. `user-update
--days` sets expiry from now, not from the previous expiry; quota changes do not
reset used traffic. Use `user-reset-usage --confirm` only for a deliberate traffic
renewal/reset; it does not rotate proxy credentials or the Keyholder URL. User creation uses Marzban's default available inbounds for the
specified protocols. Use `user-inbounds` to restrict selection. It replaces only
that protocol's selection, validates tag ownership and preserves existing proxy
credentials and all other protocol selections. Normal Marzban panel changes are
reflected on the next subscription fetch. The old `profiles` command is refused
in production Marzban-authority mode.

## Stable links and secret handling

`create` is idempotent in the backend, including concurrent requests. `link` is
read-only and retrieves the same token. There is no reason to store URLs manually
for future lookup. Neither changes quota/expiry or recreates an existing panel user.
Renaming, remapping, panel edits and upgrades keep the URL. Rotation invalidates
it immediately; revoke is terminal. Link availability remains subject to upstream
status/quota/expiry and infrastructure availability.

Link-bearing commands require an interactive terminal. `--json` and redirected
stdout are refused. To deliberately save a link, use `--save-link` with a new
private file; files/symlinks are refused before mutation and mode 0600 is used:

```bash
keyholder link alice --save-link /path/to/private-storage/alice.json
```

That option explicitly downloads a customer credential. Keep it outside Git/logs.
Missing legacy vault entries return an error, never an implicit rotation.
`reconcile --confirm` is the historical bootstrap tool: it rotates unrecoverable
legacy registrations and revokes duplicate rows. It is not part of daily use.

The API and panel are independent systems. If panel creation succeeds but attaching
fails, inspect `users` then recover with `create`; do not recreate the upstream user.
After an uncertain rotation response, use `link` rather than rotating again.
Disable/revoke in Keyholder does not invalidate downloaded proxy credentials;
change the account in Marzban when access must stop.

## Backup and scope

`backup` uses SQLite online snapshots, integrity and foreign-key checks. Its
root-only recovery directory includes both databases, the vault-key environment,
Xray and Nginx configuration. This is same-server recovery, not an off-host backup.
Scheduling, encrypted destination and retention still require an owner decision.

The CLI covers customer/API and common panel operations. It deliberately offers
no user deletion, bulk usage reset, firewall changes, deployment or automatic
restore. Infrastructure recovery follows the reviewed operations runbook.

Root-owned server files are in `/usr/local/lib/keyholder-admin`: `cli.py`, `host.py`,
`worker.py`, `backup_database.py`. The frontend/host require Python 3.10+; the worker
runs in the existing API Python 3.12 environment. Docker/private-backup access uses
the existing administrative SSH account. Updating operator files needs no API
container replacement. Verify `status`, `doctor`, `users`, `list` and `check` after
installation; never rotate or create a real account as a smoke test.
