# Optional Xray exit restart

This is a workaround for a confirmed exit-core incident, not a CPU tuning default.
It disconnects existing streams through the selected exit. Client recovery can
outlast listener startup. It does not restart the panel, API, node or backhauls.

Copy `deploy/xray-restart.example.json` to `/etc/keyholder/xray-restart.json`
(root-owned, mode 0600), and install `scripts/xray_restart.py` under
`/usr/local/lib/keyholder-admin/`. The example is disabled. Set `enabled` to true
and `on_calendar` to a systemd calendar expression with an explicit timezone, e.g.
`*-*-* 04:00:00 Asia/Tehran`. Paths, target unit, readiness listeners and timeouts
must match the actual exit. Keep checks on loopback; public exposure is unnecessary.

```sh
sudo python3 /usr/local/lib/keyholder-admin/xray_restart.py check
sudo python3 /usr/local/lib/keyholder-admin/xray_restart.py apply
systemctl list-timers keyholder-xray-restart.timer
```

`check` validates the active executable/configuration without restarting it.
`apply` validates the calendar, generates the timer and oneshot service, and starts
or stops only the timer according to `enabled`. Edit the JSON and run `apply`
after changing the time or enabled state. To disable immediately without editing:
`sudo systemctl disable --now keyholder-xray-restart.timer`; also set `enabled`
to false and apply so recovery preserves the choice. Disabling the timer does not
cancel a restart already in progress. Missed times are not caught up after boot.

Each scheduled execution validates the active target identity and Xray config
before stopping the service, then waits for all configured listeners. Failures
mark the oneshot failed and trigger the existing monitor. Include its service in
`systemd_failed_units` in monitor.json; this checks failure, not whether a oneshot
is continuously active. After repairing an incident, reset the failed unit using
`systemctl reset-failed keyholder-xray-restart.service` and recheck monitoring.

For reproducible installation, use `deploy/ansible/playbooks/xray-restart.yml`
with `recovery_targets` and a complete `xray_restart_config` dictionary in your
private inventory. It checks the target without restarting, configures scheduling,
and adds the helper, JSON and both generated units to existing recovery inventories
and monitoring where present. Existing application paths must already be installed.
During recovery the captured units remain inactive until the production handover;
`deploy/ansible/tasks/activate-jobs.yml` then applies the captured JSON, respecting `enabled: false`.
The next regular backup captures changes; installing a timer does not create or
verify an offsite backup. Rehearse restoration separately on a disposable host.
