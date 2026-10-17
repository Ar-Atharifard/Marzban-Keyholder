# Operations and monitoring

Daily tools: `keyholder system status`, `system health`, `system doctor`,
`system metrics`, `customer check USER`, `upstream users` and `upstream inbounds`.
`doctor` checks DB/vault/mappings and supported provider inventory; `/health` alone
checks DB connectivity. See [CLI reference](../scripts/admin/README.md).

## Release and recovery

1. Test locally, including migrations and packaging; build an immutable image.
2. Back up DB, vault key and affected configuration. Record current image/downtime,
   exact deployment, rollback and validation steps before changing production.
3. Recreate only the affected service. Never build on the constrained VPS, restart
   Docker globally, migrate at startup or pull over production-only Git changes.
4. Check health, existing subscriptions and real proxy traffic without printing tokens.

`keyholder system backup` creates a root-only local SQLite snapshot/key/config set;
latest two complete sets are retained by default (`backup_retention_count`, minimum
2). Pruning occurs only after success. Same-disk copies are rollback material, not
disaster recovery. [Offsite backup and restore](disaster-recovery.md) is separate.
Preserve DB, vault key, domain/path and mapping identity. Never restore old rotated
tokens accidentally. Rehearse DB integrity, schema, token retrieval and proxy access.

## Network changes and private panel

Inspect existing listeners/rules before changes. Do not flush firewall tables,
reset/disable/re-enable UFW or blindly restore host networking over the only SSH
path. Keep an independent provider console open, preserve the authorized SSH port,
and verify a fresh second key-authenticated session before/after activation.
An on-host rollback timer is not independent recovery. Shared ingress needs syntax
validation and a graceful reload; Xray changes can interrupt active connections.

Prefer `keyholder panel open` for a loopback SSH tunnel. The optional
`scripts/render_panel_gate.py` generates a secret bookmark/cookie gate, not a
replacement for authentication or protection against hostname filtering:

```sh
python3 scripts/render_panel_gate.py --hostname panel.example.com \
  --output /private/path/panel.conf --access-file /private/path/panel-access.json
```

It refuses overwrite; protect generated files as 0600 and configure
`panel_access_file` in the dispatcher. `keyholder panel url` retrieves the bookmark.
The bookmark grants a Secure/HttpOnly/SameSite gate cookie for 30 days and redirects
to native `/dashboard/`. Native paths remain visible to admitted browsers; visitors
without the cookie receive 404 except the decoy root. Validate login, locale, assets,
API and WebSockets before activation. Disable path logging/caching and keep the
bookmark private. Write gateway files in place when Docker binds individual files;
replacing an inode can leave the container using the old configuration.

## Lightweight monitoring and bots

`scripts/monitor.py` runs briefly every two minutes: containers/systemd, HTTP/TCP,
disk/inodes, RAM/swap/load, backup age, Marzban status/quota/expiry and traffic growth.
It stores root-only counters/state, not destinations, tokens or customer contacts.
It does not prove physical hardware health or per-user connectivity. Idle users
cannot be distinguished from failed connections. ISP probes need a domestic host.

Install `monitor.py` under `/usr/local/lib/keyholder-admin/`, private config/env
from `deploy/monitor*`, and its systemd service/timer. Keep configuration/state
root-owned and secrets mode 0600. Run once without notifications before enabling.
Use separate alert and management Telegram identities:

```sh
keyholder alert-bot configure
keyholder alert-bot test
keyholder management-bot configure
keyholder management-bot test
keyholder heartbeat configure
keyholder heartbeat test
```

Interactive prompts hide secrets; never put tokens in shell arguments or chat.
For whole-host outages, configure the external heartbeat with at least five minutes
grace. A dead VPS cannot send Telegram itself. Customer quota warnings do not
suppress infrastructure heartbeat health.

`keyholder monitor status` reads state; `monitor run` checks without notifications.
Bot `/help` lists commands; `/metrics`, `/monitor`, `/alerts` and `/ping` are read-only.
Mutations use a bounded serial queue and expire after five minutes. Lost replies
are not replayed: inspect state before retrying. Destructive commands require
single-use confirmation. Only the configured private admin is admitted; retrieve
subscription links through SSH, not Telegram.

For thresholds, deduplication and mute/repair commands, use the single
[alert policy](alerts.md). Runtime paths and personal deployment instructions
belong in private inventory, not duplicate public guides.
