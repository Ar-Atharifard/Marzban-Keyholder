# Operations and monitoring

Daily tools: `keyholder system status`, `system health`, `system doctor`,
`system metrics`, `customer check USER`, `upstream users` and `upstream inbounds`.
`doctor` checks DB/vault/mappings and supported provider inventory; `/health` alone
checks DB connectivity. See [CLI reference](../scripts/admin/README.md).

## Release and recovery

GitHub Actions runs checks for pushes and pull requests. To prepare a release,
merge reviewed changes into the default branch (`master` here), set a new
`project.version` in `pyproject.toml`, and refresh `uv.lock` with `uv lock`. In GitHub open **Actions →
Prepare release → Run workflow**, selecting that default branch. Other branches cannot publish. No production SSH
key or server credential belongs in GitHub. The workflow runs all CI jobs before it:

- Builds the amd64 API image on the hosted runner and pushes it to GHCR.
- Packages the Python wheel/sdist and reviewed source archive, including operational
  helpers and deployment files. The wheel itself does not install system services.
- Records the commit, immutable image digest and artifact hashes in `release.json`
  and `SHA256SUMS`, then creates a **draft** GitHub release.

The workflow uses the repository's temporary `GITHUB_TOKEN`. Repository settings
must allow its package/release writes. GHCR package visibility is separate from
repository visibility; maintainers choose it explicitly. An existing version is
refused, including drafts. A failure after image publication may leave an unused
image, but never changes production. Review the draft and publish it deliberately.
The first hosted run still needs validation in your GitHub repository. Protect the
default branch with required CI checks before merging; branch protection is a
repository setting, not something this workflow enables automatically.

Deploy **from the laptop**, as a separately reviewed operation:

1. Select a release and verify its downloaded files with `sha256sum -c SHA256SUMS`
   in the release directory. Use `api_image` from its manifest, not a mutable tag.
2. Inspect installed versions and server-local changes. Back up the DB, vault key
   and affected configuration; record current images, migration state and rollback.
3. Pull the image on the target, or transfer a saved image from the laptop if the
   registry is unreachable. Recreate only the affected service using its actual
   Compose project/overlays. Never build on the constrained VPS, restart Docker
   globally, migrate at startup or pull over production-only Git changes.
4. Install only changed operational helpers/configuration from the same release,
   using the relevant reviewed Ansible playbook. Do not extract the archive over
   `/usr/local` or assume an API deployment updates bots, the Worker or tunnels.
5. Check health, existing subscriptions and real proxy traffic without printing
   tokens. Record the release commit/image and component changes privately.

There is currently no single general-purpose live-upgrade command. The
`restore-foreign` / `restore-domestic` commands are for empty-host recovery, not
release updates. Publishing a release never updates `/srv/keyholder`, installed
helpers or running containers. Keep that checkout as a reference to the deployed
source; installed components may differ only when that is explicitly recorded.
Database rollback is separate from reverting an image and must be planned.

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

Host and container DNS are separate. If the host resolves names but proxy traffic
fails, inspect `docker exec CONTAINER cat /etc/resolv.conf` and test a lookup inside
that container. A stale `127.0.0.53` entry fails when the host DNS stub is disabled.
For host-network containers, configure reachable resolvers explicitly with Compose
`dns`; validate with `docker compose config --quiet`. A running-container repair
alone does not configure future replacements. Confirm real HTTPS through profiles
after repair. Do not restart Docker or change firewall rules to fix a DNS mismatch.

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
single-use confirmation. Only the configured private admin is admitted. Explicit
`/link USER` and `/config USER CONFIG_ID` return bearer links there; `/configs USER`
lists choices without credentials. Protect the admin Telegram account and chat history.

For thresholds, deduplication and mute/repair commands, use the single
[alert policy](alerts.md). Runtime paths and personal deployment instructions
belong in private inventory, not duplicate public guides.
