# Alert policy

Checks run every two minutes. Notifications never change customer access.
`keyholder monitor status` or bot `/monitor` shows incidents; `/metrics` shows
resources. [Installation and bots](operations.md).

## Delivery contract

- Incidents have an exact key, occurrence ID, severity, rule, timestamps and repair
  guidance. Deduplication uses key/occurrence/threshold; 81% → 84% does not resend,
  crossing 95% can. Recovery closes the occurrence; recurrence starts a new one.
- Each run batches new/escalated/recovered incidents. Messages split only at Telegram
  limits. Failed delivery retries later; partial delivery may repeat some parts.
- Unchanged warnings do not repeat. Exhaustion/expiry combine into one account
  incident, reminded at most daily for 72 hours from first observation, then silenced
  until recovery. Infrastructure alerts remain independent.
- Quota thresholds: 80%/95%; expiry: 7/3/1 days. Traffic needs 1 GiB growth,
  20 GiB/hour and 3× the available seven-day hourly baseline. This is an investigation
  signal, not proof of abuse. Thresholds/resource limits are private configuration.
- Failed service/inventory/DB probes, overdue configured offsite backups and critical
  disk/inode pressure are critical; other conditions are warnings. No automatic repair.

## Control notifications

Copy the exact incident key. These examples use synthetic `user:12:quota`.

| Intent | Bot | CLI (`keyholder monitor …`) |
|---|---|---|
| Rules/controls | `/alertcontrols` | `controls` |
| Acknowledge | `/ack user:12:quota` | `ack user:12:quota` |
| Undo | `/unack user:12:quota` | `unack user:12:quota` |
| Silence two hours | `/silence user:12:quota hours=2` | `silence user:12:quota --hours 2` |
| Unsilence | `/unsilence user:12:quota` | `unsilence user:12:quota` |
| Disable quota notices | `/rule_disable user.quota` + confirmation | `rule-disable user.quota --confirm` |
| Re-enable | `/rule_enable user.quota` | `rule-enable user.quota` |

Acknowledgement ends at recovery/escalation. Silence applies across occurrences
and severity for the chosen key, up to 168 hours (default 24). Rule disable persists.
Removing suppression does not force duplicates of delivered warnings. Suppression
never hides checks/metrics/incidents or changes heartbeat health. Recovery notices
are suppressed while silenced/disabled, but acknowledgements allow recovery notices.
Controls persist privately and serialize with monitor state writes.

## Resolve the cause

Optional authenticated checks (`scripts/proxy_probe.py`, systemd service/timer)
download the internal `kh_monitor` account's current Marzban profiles and test real
HTTPS through each one every two minutes. Keep this account private, active and
enabled for the intended inbounds; it needs no Keyholder customer record. Production
uses a 2 GiB monthly allowance with no expiry. Probe traffic counts against it.
Set `proxy_status_file` to `/var/lib/keyholder-monitor/proxy.json` to enable alerts.
Two failed runs produce one critical `service.proxy` incident listing affected
profiles. Unchanged failures do not repeat; recovery sends one notice. A missing
or overdue report also alerts. These checks cover server/Cloudflare delivery from
the VPS, not reachability from every customer's ISP. No browsing history is stored.
Domestic deployments can add `--domestic-prefix 'IR | '` to the probe service.
Matching profiles also test filtered foreign destinations and Iranian destinations;
this catches poisoned DNS/split-routing failures that a simple example.com test misses.

There is no false “mark solved” command. Repair, then `/runmonitor` or
`keyholder monitor run` to inspect; the timer delivers pending recovery.

| Rule | Repair |
|---|---|
| `user.quota`, `user.account`, `user.expiry` | Renew quota/time upstream or `/update USER quota=GB days=N`; reset usage only deliberately with confirmation |
| `user.status` | Inspect upstream state; Keyholder `/enable` changes delivery only |
| `user.traffic` | Inspect `/usage USER`, ownership and plan before acting |
| `host.memory`, `host.swap`, `host.cpu` | Inspect processes/workload and capacity |
| `host.disk`, `host.inode` | Remove verified obsolete files; preserve live data/recovery material |
| `service.*` | Inspect component logs, health, TLS and routing; avoid blanket restarts |
| `service.proxy` | Inspect the probe journal, monitoring account, container DNS, Xray and gateway; retry `systemctl start keyholder-proxy-probe.service` |
| `service.remote` | Inspect domestic SSH, node, reverse tunnel, guard heartbeat and available resources |
| `service.tls` | Run `keyholder tls status`; inspect renewal before retrying `keyholder tls issue`. Certificate warning at 14 days, critical at 2 days or unreadable certificate |
| `backup.age` | Complete a successful local `/backup` and repair its schedule |
| `backup.offsite` | Repair credentials/connectivity and complete encrypted upload; local backup is insufficient |
| `marzban.usage`, `marzban.users` | Inspect DB permissions/health and inventory; do not delete users to hide an alert |

`host.conntrack` detects Linux connection-tracking pressure: warning at 75% of the
configured limit, critical at 90%. Inspect the count, maximum and kernel table-full
messages before changing capacity. Never flush connection tracking as a capacity fix.
