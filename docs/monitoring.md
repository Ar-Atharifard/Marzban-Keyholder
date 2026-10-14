# Monitoring

Keyholder uses a short-lived host monitor instead of running Prometheus or a
second metrics database on small production servers. Marzban remains the source
of truth for user status, quota, expiry and traffic.

## Coverage

`scripts/monitor.py` checks Docker health, local and public HTTP endpoints,
required TCP listeners, disk, memory, swap, load, recovery-snapshot age and
Marzban's user counters. It reports quota, expiry, account-status and traffic-rate
alerts. State is stored in `/var/lib/keyholder-monitor/state.json`; it contains
usernames and counters and must remain root-only.

The systemd timer runs every two minutes. It sends only alert transitions and
recoveries, preventing repeated notifications for an unchanged condition. A
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

Run `keyholder alerts-configure` from an interactive workstation terminal. The
token is read without echo. Send `/start` to the new bot when prompted; Keyholder
discovers the single private chat through Telegram's official API. The token is
transferred over SSH input and written only to the root-owned monitor environment.
Then run `keyholder alerts-test`. Do not pass bot tokens on command lines, paste
them into issue trackers or commit them.

Configure the second bot with `keyholder management-bot-configure`, then verify it
with `keyholder management-bot-test` and `keyholder management-bot-status`. Use
`/help` in its private chat for the compact command reference. Link retrieval stays
in the SSH CLI so Telegram chat history never becomes a subscription credential store.

For external outage detection, create a Better Stack heartbeat with a five-minute
grace period, then run `keyholder heartbeat-configure` and
`keyholder heartbeat-test`. The URL is read without terminal echo and stored only
in the root-owned monitor environment. Customer quota and expiry warnings do not
suppress the host heartbeat.

## Operator commands

`keyholder monitor-status` reads the most recent state. `keyholder monitor-run`
runs checks immediately without sending notifications. The systemd timer owns
normal alert delivery.
