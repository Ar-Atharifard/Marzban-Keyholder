# Alert contract (version 1)

The alert bot delivers notifications. The private management bot and SSH CLI control
alerts. Every two minutes, checks evaluate actual conditions independently of their
notification settings. No alert action automatically disables or modifies a customer.

## Identity and delivery

Each active incident has an exact `key` (for example `user:12:quota`), occurrence
`id`, `rule`, `severity`, message, first/last observation times and repair guidance.
`/monitor` and `keyholder monitor status` expose these, including suppression state.
`/alertcontrols` and `keyholder monitor controls` list the rule registry and controls.

Deduplication uses the key, occurrence and threshold/severity. Moving from 81% to
84% does not send another quota warning; crossing 95% does. A confirmed recovery
ends the occurrence; recurrence gets a new ID and may notify again. Expiry and
exhausted quota combine into one `user:ID:account` incident. Distinct infrastructure
probes retain separate identities, even when they might share a root cause.

Each run batches new/escalated alerts and recoveries into one message, split only
when Telegram's size limit requires it. Failed delivery is retried by later checks;
no delivery is recorded as successful prematurely. Partial multi-message delivery
can repeat already delivered parts on retry; exactly-once delivery is not promised.

Ordinary unchanged conditions do not repeat. Exhausted/expired accounts receive
at most one daily reminder for 72 hours from first observation, then automatic
silence until recovery. The source panel does not expose historical exhaustion time.

## Controls

Copy the exact key from `/monitor` or a notification. Examples below use a synthetic
`user:12:quota`; substitute the key you actually see.

| Intent | Management bot | SSH CLI |
|---|---|---|
| View rules and controls | `/alertcontrols` | `keyholder monitor controls` |
| Acknowledge current occurrence | `/ack user:12:quota` | `keyholder monitor ack user:12:quota` |
| Remove acknowledgement | `/unack user:12:quota` | `keyholder monitor unack user:12:quota` |
| Silence this key for two hours | `/silence user:12:quota hours=2` | `keyholder monitor silence user:12:quota --hours 2` |
| Remove silence | `/unsilence user:12:quota` | `keyholder monitor unsilence user:12:quota` |
| Disable quota notifications for all users | `/rule_disable user.quota`, then `/confirm CODE` | `keyholder monitor rule-disable user.quota --confirm` |
| Enable quota notifications | `/rule_enable user.quota` | `keyholder monitor rule-enable user.quota` |

Acknowledgement applies only to the current occurrence and threshold. It expires
on recovery or escalation. Temporary silence applies to the exact key, across
occurrences/severity changes, for more than zero and at most 168 hours (default 24).
Use it deliberately for planned work. Rule disable persists until re-enabled.
Removing a mute restores normal notification rules; it does not force a duplicate
of an already delivered warning. Unsent active alerts can then notify.

All suppression affects notifications only: checks, metrics, active incidents and
infrastructure heartbeat health remain truthful. Recovery notifications for a
currently disabled/silenced key are suppressed. Acknowledged incidents still report
recovery. Controls persist in root-only `controls.json` beside monitor state and
are serialized with monitor writes. No secret values belong in control commands.

## Resolve the cause

There is no command that falsely marks a failing condition as solved. Fix its cause
and run `/runmonitor` (or `keyholder monitor run`) to inspect the result. That manual
check sends no notifications; the timer subsequently delivers any pending recovery.

| Rule | Typical repair |
|---|---|
| `user.quota`, `user.account` | Increase/renew quota in Marzban or `/update USER quota=GB`; reset usage only deliberately with `/resetusage USER` plus confirmation. Renew time if expired. |
| `user.expiry` | Renew with `/update USER days=N`; inspect account status afterwards. |
| `user.status` | Inspect why the account is inactive; update upstream status only when appropriate. `/enable` changes Keyholder delivery, not Marzban status. |
| `user.traffic` | Inspect `/usage USER`, account ownership and quota; high traffic alone is not proof of abuse. |
| `host.memory`, `host.swap`, `host.cpu` | Inspect `/metrics` and Linux process usage; correct the workload or capacity. |
| `host.disk`, `host.inode` | Remove verified obsolete artifacts/logs or expand storage; preserve active data and rollback material. |
| `service.container`, `service.systemd`, `service.http`, `service.tcp` | Inspect the component, journal/health check, TLS and routing. Do not blindly restart the whole stack. |
| `backup.age` | Run `/backup`, verify its successful completion and repair the backup process if needed. |
| `marzban.usage`, `marzban.users` | Inspect DB permissions/health or upstream inventory; do not create/delete users to conceal the alert. |

Quota warnings default to 80%/95%; expiry warnings to 7/3/1 days. Traffic anomalies
require 1 GiB growth, 20 GiB/hour and three times the available seven-day baseline.
Resource thresholds are in the private monitor configuration; `/alertcontrols`
provides rule-specific guidance. Notification severity is critical for failed
service probes, inventory/DB failures and critical disk/inode pressure; other
conditions are warnings. This classification does not imply an automatic repair.

## Bot execution and test limits

One bounded command queue serializes account changes. Quick reads bypass that queue.
Only the configured private administrator is admitted. Invalid arguments fail before
dispatch. Mutations are consumed before execution and are not automatically replayed
when reply delivery fails. Commands older than five minutes are rejected, including
at execution time. Destructive operations require a short-lived, single-use
confirmation. If a reply is lost, inspect state before retrying.

Tests cover supported command dispatch, argument failures, confirmations, owner
checks, redaction, pagination, Telegram failures, alert transitions, deduplication,
controls, escalation, recurrence and exhausted-account lifecycle. Tests cannot
prove every possible network failure, timing interleaving, client or future panel
version. Production checks use reads and isolated synthetic controls, not live
customer mutations.
