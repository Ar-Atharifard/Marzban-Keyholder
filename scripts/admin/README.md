# Keyholder operator commands

Run `keyholder --help` from the workstation. These tools use the existing `braavos`
SSH alias; the administrator key stays inside the API container. No new service,
Python package installation, public API route or database migration is required.

| Task | Command |
|---|---|
| Container status | `keyholder status` |
| Database/API health | `keyholder health` |
| Open private panel | `keyholder panel` |
| Show public-panel URL | `keyholder panel-url` |
| List customers | `keyholder list` |
| Next page | `keyholder list --offset 100` |
| Customer details | `keyholder show alice` |
| Check mapped Marzban profiles | `keyholder check alice` |
| Attach an existing panel user | `keyholder create alice --name 'Alice'` |
| Rename | `keyholder rename alice 'Alice Smith'` |
| Select profiles | `keyholder profiles alice tcp_reality xhttp_reality grpc_cdn tcp_reality_ipv6 shadowsocks_ipv6` |
| Pause/resume delivery | `keyholder disable alice` / `keyholder enable alice` |
| Change upstream mapping, retain link | `keyholder remap alice replacement_user` |
| Private server-side DB snapshot | `keyholder backup` |
| Permanently revoke | `keyholder revoke alice --confirm` |
| Replace a compromised/lost token | `keyholder rotate-token alice --confirm` |

A selector is a customer UUID or an unambiguous Marzban username. After remapping,
use the new username or the same customer ID. Duplicate/ambiguous usernames require
IDs. Listing never reveals tokens. `--json` is available before the command for
nonsecret results. On Braavos as root, use `keyholder --local <command>`; `panel`
forwarding runs on the workstation.

Create the Marzban user with its quota, expiry, VLESS/Shadowsocks permissions and
selected inbounds first. `create`, `profiles` and `remap` check the active upstream
user before mutation and refuse missing selected families. This preflight does
not continuously synchronize accounts or provide an atomic guarantee across two
independent systems. The create duplicate check is not a database uniqueness
constraint; concurrent operators should not attach the same username at once.

## Credentials and confirmations

Creation and rotation show a URL only in an interactive terminal, never with
`--json` or redirected stdout. Optionally save it deliberately to a new mode-0600
local file; existing files and symlinks are refused **before** making the request:

```bash
keyholder create alice --save-link /path/to/private-storage/alice.json
```

This explicitly saves a customer credential on your workstation. Use secure
storage/password-manager import; do not put it in Git, shared folders or logs.
No administrator key, panel password or database is downloaded. URLs cannot be
recovered from stored hashes. Keep the issued URL: rotation invalidates old links.
Never rotate tokens during ordinary upgrades, remapping or infrastructure moves.

`disable` pauses delivery but preserves the link for `enable`. `revoke` is terminal.
Neither changes downloaded proxy credentials or terminates Marzban access; manage
those accounts separately in the panel. No bulk mutation, deletion, deployment,
restore, firewall or proxy restart command is provided.

A failed mutation may have succeeded if its response was lost. Inspect `show` /
`list` before retrying. Do not automatically retry create or token rotation.
Backups use the SQLite online backup API and integrity checks, stay root-only in
`/var/backups/keyholder`, and are not off-server recovery. Retention is manual.

## Installation and updates

The workstation command links to `scripts/admin/cli.py`. Root-owned server files
live in `/usr/local/lib/keyholder-admin`: `cli.py`, `host.py`, `worker.py`, and the
existing `backup_database.py` utility. `/usr/local/bin/keyholder` links to `cli.py`.
The frontend and host dispatcher require Python 3.10+; the worker executes inside
the existing API Python 3.12 environment. The host dispatcher requires the existing
administrative SSH account because Docker access and private backups are privileged.
Do not grant broader Docker/sudo privileges to other users to run this tool.

Update only these operator files after tests. No running container needs replacement.
Run read-only `status`, `health`, `list`, and an approved existing user's `check`
after installation. Do not create customers or rotate tokens as smoke tests.

## New CDN profile pilot

The installed CLI accepts `ws_tls_cdn` and `xhttp_tls_cdn` in explicit `--profiles`
or `profiles` selections. Defaults remain the original five. The backend/core release is active and all
seven profiles passed actual HTTPS tests through the deployed routes. The approved initial pilot covers both existing subscriptions mapped to
`test1`; wider rollout needs Iranian-network results and owner approval.
Since test1 has two mappings, use a customer ID from `keyholder list` for
`show`, `check` or policy edits; username selection intentionally refuses ambiguity. Preserve all
existing selections when adding new ones; `profiles` replaces the selection.
