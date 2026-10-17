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
| `backup.age` | Complete a successful local `/backup` and repair its schedule |
| `backup.offsite` | Repair credentials/connectivity and complete encrypted upload; local backup is insufficient |
| `marzban.usage`, `marzban.users` | Inspect DB permissions/health and inventory; do not delete users to hide an alert |
