# Backup and disaster recovery

Targets: **≤24 hours data loss**, **20-minute restore**, Ubuntu 22.04 amd64.
These are objectives, not guarantees: an empty-VM timed restore is still required.
Never reset the source until an independent backup has been downloaded and restored.

## What runs where

| Component | Location / purpose |
|---|---|
| `deploy/ansible/` | Laptop controller; bootstrap, gated restore and backup installation |
| `scripts/recovery.py`, `deploy/recovery/` | VPS capture, consistency checks and restic upload |
| `deploy/systemd/keyholder-recovery*` | Daily backup and weekly retention/maintenance |
| Private inventory and repository password | Separate protected storage; never public Git |

Daily capture: 02:00 UTC; failures retry after 15 minutes, capped at three starts
per two hours. Retain seven daily/four weekly points. Refresh the latest two local
rollback sets only after successful cloud upload. Failed uploads never advance
success status or retention. Daily scheduling alone cannot guarantee a 24-hour RPO.

Keep the repository password, restricted storage credentials, SSH/DNS access and MFA
recovery codes off-server. A delete-capable key on a compromised VPS can delete its
backups; an independent/offline copy gives stronger protection. Restic deduplication
is not a storage/spending cap. Ubuntu 22.04 standard security maintenance ends
May 2027; plan supported maintenance. Images must match the target architecture.

## Configure private B2 storage

1. Create a private Backblaze bucket and enable account MFA. Create a bucket-restricted
   application key with read/write/list/delete. Never use the account password/key.
2. Do not expire live objects by age or enable Object Lock blindly. Restic owns
   retention. For S3, remove already-hidden objects after one day, scoped to
   `keyholder/`; this reclaims deleted objects without removing retained snapshots.
3. On VPS run `sudo keyholder-recovery configure-b2`. Enter credentials through
   prompts and a separately generated repository password (≥32 characters), saved
   in your password manager. Configuration is root-only and refuses overwrite.
4. Run `sudo keyholder-recovery prepare-s3` to validate scope and resolve the official
   endpoint, preserving key/password. Configure billing/size monitoring; free storage
   allowance is finite. Configuration alone does not create backups.

## Capture and verify

Customize `deploy/recovery/capture.example.json` privately. Include every database,
volume, active Compose overlay, env/key/certificate, custom core/geodata, policy,
operator/bot dependency and unit. Declare SQLite sources under `sqlite` for online
snapshots, not raw DB/WAL copies. Exclude logs/caches/obsolete experiments/backups.
Image archives pin exact running IDs; no production build is needed. Allow working
space for exports. Captures are not a distributed transaction: avoid deployments
while capturing and honor the recovery lock.

```sh
sudo keyholder-recovery inventory --seed /etc/keyholder/recovery-seed.json --output /etc/keyholder/recovery.json
sudo keyholder-recovery capture --config /etc/keyholder/recovery.json --output /var/lib/keyholder-recovery/manual-bundle
sudo keyholder-recovery verify --bundle /var/lib/keyholder-recovery/manual-bundle
sudo systemd-run --wait --collect --unit keyholder-recovery-init --property=EnvironmentFile=/etc/keyholder/recovery.env /usr/bin/restic init
sudo systemctl start keyholder-recovery.service
sudo systemctl status keyholder-recovery.service
```

Initialize once, never automatically after unexplained repository failures. Load
credentials through systemd, not shell arguments/source. Inventory and capture
refuse existing output, symlinks, special files and undeclared SQLite sources;
review a new inventory candidate when changing it. Captures rediscover active
Compose paths, but other deployment files still require inventory review.

After an actual downloaded restore passes, set `recovery_initial_upload_verified:
true` in private inventory and use the backup playbook to enable timers. Monitor:

```json
{"offsite_backup_status_file":"/var/lib/keyholder-recovery/status.json","offsite_backup_max_age_hours":24}
```

Service ceilings are 50% CPU/320 MiB memory, not measured requirements. Weekly
maintenance shares the capture lock. Normal failures remove temporary plaintext;
a forced kill may leave private staging: inspect before deleting. Monitor unit
failures, perform a full repository read monthly and restore rehearsal quarterly.
A local `system backup` does not resolve an offsite-backup incident.

## Empty VM rehearsal

Use an isolated Ubuntu 22.04 VM with SSH/sudo, 2 GB RAM and at least 20 GB disk;
prefer synthetic data first. Never bootstrap an everyday laptop, change production
DNS or run the same Telegram bot on both hosts. Use a private VM disk for real data.

```sh
python3.12 -m venv .private/ansible-venv
.private/ansible-venv/bin/pip install -r deploy/ansible/requirements.txt
```

Copy `deploy/ansible/inventory/example.yml` to `.private/recovery-inventory.yml`;
set target, user, sudo and disposable-target flag. Verify SSH fingerprints.

```sh
.private/ansible-venv/bin/ansible-playbook -i .private/recovery-inventory.yml deploy/ansible/playbooks/bootstrap.yml --ask-become-pass
.private/ansible-venv/bin/ansible-playbook -i .private/recovery-inventory.yml deploy/ansible/playbooks/restore.yml --ask-become-pass
```

Between those commands, download the chosen restic snapshot **on the target** into
a new private staging directory. Set `recovery_bundle` to its `bundle`, verify the
manifest and approve roots/Compose projects in dependency order (panel, API, gateway),
including all overlays. Review addresses before setting
`recovery_addresses_reviewed: true` and `recovery_start_applications: true` on the
first restore. Startup uses captured images with `--no-build --pull never`.

Restore refuses populated destinations, databases/volumes and staging. It is one-time,
not an upgrade/convergence tool: if staged without startup, validate/start Compose
separately rather than rerunning restore. Systemd units are captured but not
activated automatically; install/review them explicitly, including optional DNSTT.
Bootstrap does not rewrite SSH/firewall. Before public activation follow the
[network safety procedure](operations.md), validate key-only SSH and do not blindly
restore host keys, interfaces or firewall tables.

Acceptance: time the complete download/restore; check DB/schema/IDs/token retrieval,
quotas/usage/expiry, panel tunnel, subscriptions, representative CDN/REALITY traffic,
domestic blocking, origin protection and reboot/startup. VPS checks cannot establish
all-ISP reachability. Only a successful timed rehearsal establishes the RTO.

## Cutover

Prepare/test replacement first. For planned migration freeze admin writes, stop
old bot/monitor timers, snapshot final DBs and quiesce accounting as needed. Never
run two writers against divergent copies. Preserve domain/path/token vault,
credentials and REALITY/DNSTT keys; restore matching images before upgrades.
Review direct IPs/IPv6 and Cloudflare origins. Already-imported literal IPs need
client refresh; DNS TTL alone cannot fix them.

Move DNS after validated SSH/firewall/TLS/panel/API/proxy checks and a rollback plan.
Activate bots/monitoring only on the chosen host, then backups after verified upload.
Keep the old host available where possible. After new writes, reverting DNS/DBs
is not lossless: account for changes before rollback.

Sources: [restic](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html),
[B2 pricing](https://www.backblaze.com/cloud-storage/pricing),
[Ubuntu lifecycle](https://ubuntu.com/about/release-cycle).
