# Monitoring

Keyholder uses a short-lived host monitor instead of running Prometheus or a
second metrics database on small production servers. Marzban remains the source
of truth for user status, quota, expiry and traffic.

## Coverage

`scripts/monitor.py` checks Docker and critical systemd services, local and public HTTP
endpoints, required TCP listeners, disk space and inodes, memory, swap, load, recovery-snapshot age and
Marzban's user counters. It reports quota, expiry, account-status and traffic-rate
alerts. State is stored in `/var/lib/keyholder-monitor/state.json`; it contains
usernames and counters and must remain root-only.

The systemd timer runs every two minutes. It sends only alert transitions, severity
changes and recoveries, preventing repeated notifications as measurements fluctuate. A
successful composite check pings an optional hosted heartbeat URL. The missing
heartbeat detects total host or network failure, which local Telegram delivery
cannot report.

The monitor does not record destinations, subscription tokens, proxy credentials
or customer contact fields. It cannot infer that an idle user has a connection
problem. Censorship-path tests require synthetic clients on the target networks.

## Installation

Copy `scripts/monitor.py` to `/usr/local/lib/keyholder-admin/monitor.py`, copy
`deploy/monitor.example.json` to `/etc/keyholder/monitor.json`, and create
`/etc/keyholder/monitor.env` from `deploy/monitor.env.example`. All three private
configuration/state locations must be owned by root; secret files use mode 0600.

Install the units from `deploy/systemd/`, run one check with notifications disabled,
then enable the timer. Configure the hosted provider to alert when the heartbeat is
late by at least five minutes. Do not put a real subscription URL in an external
HTTP monitor.

Use separate Telegram bot identities for monitoring and management. The alert bot
needs only its token and the administrator chat ID. The management bot accepts
commands only from one configured numeric ID in a private chat and calls the same
server-side dispatcher as the SSH CLI. It never returns subscription links in chat.

Run `keyholder alert-bot configure` from an interactive workstation terminal. The
token is read without echo. Send `/start` to the new bot when prompted; Keyholder
discovers the single private chat through Telegram's official API. The token is
transferred over SSH input and written only to the root-owned monitor environment.
Then run `keyholder alert-bot test`. `keyholder alert-bot status` reports whether
delivery is configured, the timer is active and the most recent run succeeded without
revealing credentials. Do not pass bot tokens on command lines, paste
them into issue trackers or commit them.

Configure the second bot with `keyholder management-bot configure`, then verify it
with `keyholder management-bot test` and `keyholder management-bot status`. Use
`/help` in its private chat for the compact command reference. Link retrieval stays
in the SSH CLI so Telegram chat history never becomes a subscription credential store.

For external outage detection, create a Better Stack heartbeat with a five-minute
grace period, then run `keyholder heartbeat configure` and
`keyholder heartbeat test`. The URL is read without terminal echo and stored only
in the root-owned monitor environment. Customer quota and expiry warnings do not
suppress the host heartbeat.

## Operator commands

`keyholder monitor status` reads the most recent state. `keyholder monitor run`
runs checks immediately without sending notifications. The systemd timer owns
normal alert delivery.

## Alert policy and management

Quota warnings fire at 80% and 95%, expiry warnings at 7, 3 and 1 days. A changing
percentage within the same threshold does not resend the alert. New problems are
batched per check; recoveries are reported separately. Traffic warnings require
at least 1 GiB growth since the last sample, a rate of 20 GiB/hour, and three times
the seven-day hourly baseline (when available). These are investigation signals,
not proof of abuse, and never automatically disable a customer.

The management bot supports inspection (`/status`, `/doctor`, `/monitor`, `/alerts`,
`/users`, `/customers`, `/history`, `/check USER`, `/usage USER`), provisioning and
identity/plan updates. `/help` shows syntax. `/resetusage`, `/remap`, `/revoke` and
`/rotate` require a five-minute confirmation; `/cancel` discards it. Updates are
persistently consumed before dispatch, preventing automatic replay after a reply
failure. If a reply is lost, inspect state before retrying a mutation.

This lightweight monitor observes VPS resource pressure, not physical hardware
health, per-request tracing, or end-to-end ISP connectivity. Whole-host outage
alerting requires a separately configured external heartbeat.

## Responsiveness and exhausted accounts

The management bot polls independently of one serialized command worker, with a
bounded queue. `/ping` and `/help` remain responsive during audits. Commands older
than five minutes are rejected; mutations are never automatically replayed after
reply failure. Replies are split within Telegram limits; use `/customers PAGE` or
`/history PAGE` for large inventories. Command duration and error classes are logged
without message text, credentials or customer contact data.

Use `/metrics` or `keyholder system metrics` for live RAM, swap, disk, inodes, load,
uptime and network byte counters. CPU busy percentage is the latest monitor sample;
load averages are live. The monitor and manual checks serialize access to their state.

Quota exhaustion and expiry are combined into one account alert. It is sent on first
detection and reminded at most daily for the first 72 hours, then silenced. Such
accounts remain visible in `/monitor`; silence never hides infrastructure failures.
Recovery clears the silence period so a later exhaustion starts a new lifecycle.
The configurable settings are `terminal_reminder_hours` (24) and
`terminal_silence_hours` (72). This timer begins when monitoring first observes the
condition, since the panel does not supply a reliable exhaustion timestamp.

Replies are paced to avoid Telegram chat rate limits and honor one bounded
`retry_after` response. Fast `/metrics`, `/monitor` and `/alerts` reads bypass the
long-operation queue. Long operations still execute one at a time, protecting the
small VPS and preserving the order of account changes.
