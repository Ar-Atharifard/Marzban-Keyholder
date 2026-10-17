# Recovery automation

Read [the recovery runbook](../../docs/disaster-recovery.md) before execution.
These playbooks target **new Ubuntu 22.04 amd64 servers only**; production
restoration and the 20-minute target still require a successful VM rehearsal.

- `playbooks/bootstrap.yml`: repeatable host prerequisites, no SSH/firewall edits.
- `playbooks/restore.yml`: one-time, overwrite-refusing application/data restore.
- `playbooks/backup.yml`: install backup units, enable only after verified upload.

Keep inventory and secrets private. Defaults refuse execution. DNS cutover,
host security, address changes and bot/unit activation require separate review.
This is a staged restore, not an unattended one-command rebuild.
