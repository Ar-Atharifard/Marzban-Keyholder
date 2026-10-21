# Recovery command

From the laptop, with Python 3.12 and verified SSH access:

```sh
./deploy/ansible/recover .private/recovery-inventory.yml
```

Copy `inventory/example.yml` privately and set the empty Ubuntu 22.04 amd64 target,
Compose projects and restore scope first. The command installs its laptop Ansible
environment if missing and prompts for the target sudo password. If repository
credentials are missing, it pauses for private setup on the target.

Flow: bootstrap → encrypted download → verification → restore → activation.
Rehearsal mode binds services to loopback, checks restored data/subscriptions and
REALITY traffic, then reboots the VM and checks again. Bots/timers stay disabled.
Use `--finish` for an already restored target; it skips bootstrap/download/restore.
Use `--check` to validate a running restored VM without reconfiguration or reboot.
New snapshots carry Compose release paths; older ones need explicit inventory entries.
Do not rerun the full command after a partial restore: inspect the failure first.

Production requires reviewed SSH/firewall, `recovery_security_validated`,
`recovery_addresses_reviewed` and `recovery_address_map` (old → new IPv4/IPv6).
Only addresses assigned to the replacement host are accepted. This maps Xray
listeners, literal Marzban host addresses and the optional DNSTT bind. DNS/Cloudflare,
host security and bot/timer handover remain separate cutover steps.

[Recovery runbook](../../docs/disaster-recovery.md) covers credentials, schedules,
rollback and cutover. No playbook resets SSH/firewall or changes production DNS.

For the separate domestic entry, use `inventory/domestic.example.yml` and
`playbooks/domestic.yml` with the captured `nodes/domestic.tar` already on the target.
See [domestic recovery](../../docs/domestic-node.md). Rehearsals disable restored
remote nodes; production foreign recovery requires `recovery_domestic_peers_reviewed`
and `recovery_old_writers_stopped` before starting a replacement panel when a reverse
connector is present. Two panels must never control the same domestic node.
