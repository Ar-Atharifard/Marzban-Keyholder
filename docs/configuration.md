# Configuration surfaces

Deployment values belong in private configuration, not edits to Python/JavaScript.
Defaults preserve current behavior. This is a map of the supported settings, not a
claim that arbitrary protocols, filesystem layouts or operating systems are supported.

| Component / source | Configuration surface |
|---|---|
| API: `src/keyholder/config.py`, `main.py`, `db.py` | `.env` / `KEYHOLDER_*`; `.env.example` lists credentials, provider URLs, trusted CDN policy, profile selection, client SOCKS port, timeouts, connection pool, SQLite busy timeout and limiter capacity |
| Native profiles: `src/keyholder/rendering/`, `profile_types.py`, `inbounds.py` | Marzban account/inbound/host configuration, stored customer policy and API settings; supported protocol syntax remains implementation code |
| Operator CLI: `src/keyholder/cli.py`, `scripts/admin/` | `KEYHOLDER_ADMIN_CONFIG` JSON (host, SSH config, dispatcher, panel target/path, string-valued panel_port/masque_port); host.json selected by `KEYHOLDER_HOST_CONFIG` controls server container, API URL, paths, backups, TLS helper and Telegram API base |
| API process/resources: `docker-compose.yml`, `deploy/compose.host.yml` | Compose environment overrides for bind/port, published address/port, memory/PID/tmpfs limits, health timing and log rotation; existing security restrictions remain enabled |
| Bot: `scripts/management_bot.py` | Private management-bot.env holds token/admin ID/state/dispatcher; `management_bot` component settings control polling/request timeouts, endpoint, queue, command age, confirmation TTL, send spacing and retry bounds |
| Monitoring: `scripts/monitor.py` | Private `monitor.json`, `monitor.env`, monitor.timer/service; endpoints/thresholds, service inventory, heartbeat, schedules and resource limits are configurable. Alert API base and HTTP timeouts are in monitor.env; command safety limits remain fixed |
| Profile probes: `scripts/proxy_probe.py` | Existing CLI flags select account, container, core, state and domestic prefix; `proxy_probe` component settings select HTTPS/DNS canaries, timeout budgets, concurrency and startup limits |
| Gate backhaul probes: `scripts/backhaul_probe.py` | `backhaul_probe` component settings select allowed local ports, canaries, credentials-file path, curl and budgets; credentials remain in the separate private probe.json |
| Domestic guard: `scripts/domestic_guard.py` | `domestic_guard` component settings select arm/state paths, node/gateway units and heartbeat/journal windows; timer/service files select frequency/resources |
| Backhaul guard: `scripts/backhaul_guard.py` | `backhaul_guard` component settings select failure threshold, cooldown, state directory, target unit/path and alternates; alternate health and panel permission remain mandatory |
| Gate telemetry: `scripts/gate_status.py` | `gate_status` component settings select HAProxy socket/backend/path names, guard file and service inventory |
| TLS: `scripts/tls.py` | Private acme/settings.json and token for domain/contact/credentials; `tls` component settings select directories, gateway container, lego path, renewal windows and unit names; Cloudflare DNS-01 is the implemented provider |
| Backhaul generators: `scripts/forward_config.py`, `domestic_config.py` | Existing function inputs select credentials/peers; `forward` and `domestic_routing` component settings select ports/keepalives, trusted DNS/local geoip and XUDP concurrency |
| Nginx, HAProxy, Xray, Rathole, FRP, node | Their existing nginx.conf, haproxy.cfg, JSON/TOML and environment files; `deploy/domestic/`, `deploy/nginx.conf.template`, and `render_panel_gate.py` are templates/generators, not live forwarding daemons |
| Foreign/gate backups: `scripts/recovery.py`, `gate_snapshot.py`, `gate_backup.py` | recovery.json/env, timers/services, capture inventory and restic variables; `gate_snapshot` component settings select target, SSH config/alias and transfer budgets. Gate export/restore allowlists remain fixed safety contracts |
| Restart workaround: `scripts/xray_restart.py` | Private xray-restart.json controls enabled state, explicit-timezone calendar, unit/binary/config/assets, listeners and timeouts; [procedure](xray-restart.md) |
| Cloudflare delivery: `deploy/cloudflare-subscription/` | Wrangler private vars select UPSTREAM_ORIGIN and UPSTREAM_TIMEOUT_MS (100–60000 ms). Routes/account/zone belong in the private deployment configuration; bearer URLs must not be logged |
| Recovery/orchestration: `deploy/ansible/`, `scripts/deploy_pair.py` | Private replacement plan/inventories select host addresses, keys, source mappings, artifacts and cutover flags. See fixed contracts below before changing layout or ports |
| Personal tools: `src/keyholder/personal.py`, `deploy/dnstt*.json`, units/env examples | CLI/operator JSON and personal client JSON select endpoints/binaries/state; DNSTT unit EnvironmentFile controls its listener/domain/upstream. These are not customer-profile defaults |

## Operational component overrides

`deploy/components.example.json` is a complete example for the newly configurable
operational choices. Copy only the sections you need into a non-secret JSON file.
Helpers read `KEYHOLDER_COMPONENT_CONFIG` if set; otherwise they use `components.json`
next to the installed `component_config.py` (normally
`/usr/local/lib/keyholder-admin/components.json`). Source-side generators can use
the environment selector to read the same deployment file. Missing files retain
defaults. Unknown fields within a used section, wrong types, nonpositive budgets,
nonfinite numbers and group/world-writable files are rejected. Settings do not
contain tokens, passwords or customer data. Use root ownership and mode 0644 when
an unprivileged HAProxy probe must read them; keep secrets in existing private files.

```sh
sudo python3 /usr/local/lib/keyholder-admin/component_config.py --check /path/to/components.json
```

Validation checks installed helpers without executing them. Oneshots read new
settings on their next run. Long-running bots need a deliberate restart. Changes
to generators affect newly generated configuration only; they do not alter a
running tunnel. Changing ports requires coordinated gateway, tunnel, routing and
firewall review; setting one generator's port does not perform that migration.

`deploy/ansible/playbooks/component-settings.yml` installs matched operational
helpers and validates overrides for an explicitly selected `component_targets`
group, `component_role` (foreign/domestic), and `component_settings` dictionary.
It does not restart services or deploy API/Worker/gateway changes. It updates
foreign capture inventories; the domestic exporter and restore include the shared
helper/settings dependency. Always keep helpers, settings and restore definitions
from the same release. Do not copy one dependent script alone.

## Compose/API settings

Compose controls are prefixed `KEYHOLDER_`: BIND_HOST, API_PORT, PUBLISH_ADDRESS,
PUBLISH_PORT, API_MEMORY_LIMIT, API_PIDS_LIMIT, API_TMPFS_SIZE, HEALTH_INTERVAL,
HEALTH_TIMEOUT, HEALTH_RETRIES, LOG_MAX_SIZE, LOG_MAX_FILES and LOG_LEVEL.
CONTAINER_DATABASE_URL optionally overrides the container DB URL; it is separate
from a development DATABASE_URL to preserve the existing /data volume default.
ENV_FILE selects container environment input. Compose interpolation reads its own
project .env/--env-file; changing the container env-file alone does not change
Compose interpolation. Keep API_PORT consistent with host dispatcher, monitoring,
gateway and recovery health URLs. No live port change is performed automatically.

Keep one API worker: the limiter is process-local. A multi-worker deployment needs
a reviewed shared limiter. Security headers, secret-safe logging, authentication,
read-only mounts and no proxy-header trust are not disabled by these settings.

## Supported fixed contracts and audit limits

These remain code/layout contracts, not arbitrary runtime knobs:

- REST routes, bearer-token format/entropy, quota/authentication enforcement,
  protocol parsing, safe header allowlists and persistence migrations.
- The reviewed recovery workflow targets Ubuntu 22.04 amd64, standardized final
  SSH access on port 2222, and the documented Marzban/Node/three-backhaul layout.
  Several restore/health paths and paired workflow ports are still fixed. Arbitrary
  filesystem relocation, alternate service naming and arbitrary paired topology
  require further work and a fresh-host recovery rehearsal. No production SSH or
  firewall changes are part of this configurability update.
- Fixed domestic archive allowlists protect the restricted observer from exporting
  arbitrary host files. Safety ceilings on bodies/archives and secret checks remain.
- Built-in Cloudflare IPv6 trust data is a code snapshot; additional CIDRs are
  configurable. Disabling/replacing every built-in range is not currently exposed.
- The TLS helper implements Cloudflare DNS-01, although restic can use a separately
  configured S3-compatible provider. A configuration field does not add an unimplemented
  adapter or protocol.

Consequently this audit does **not** certify literal configurability of every
constant or complete deployment portability. New source knobs need a matched
release before they are available in an older installed helper/API image/Worker.
