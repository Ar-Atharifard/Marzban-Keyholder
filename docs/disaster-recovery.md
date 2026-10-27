# Backup and disaster recovery

Targets: **≤24 hours data loss**, **20-minute restore**, Ubuntu 22.04 amd64.
Validate both objectives in a timed fresh-host rehearsal; scheduling alone is not a guarantee.
Never reset the source until an independent backup has been downloaded and restored.

## What runs where

| Component | Location / purpose |
|---|---|
| `deploy/ansible/` | Laptop controller; bootstrap, gated restore and backup installation |
| `scripts/recovery.py`, `deploy/recovery/` | VPS capture, consistency checks and restic upload |
| `deploy/systemd/keyholder-recovery*` | 12-hour backup and weekly maintenance |
| Private inventory and repository password | Separate protected storage; never public Git |

Capture: 02:00 and 14:00 UTC; failures retry after 15 minutes, capped at three starts
per two hours. Retain seven daily/four weekly points. Refresh the latest two local
rollback sets only after successful cloud upload. Failed uploads never advance
success status or retention. Scheduling cannot guarantee a 24-hour RPO through
prolonged outages.

Keep controller source independently too. If captured, `controller-source.tar.gz`
under the restored helper directory can recreate the laptop checkout without Git
history or private notes. Recreate private inventory separately; deployed application
images remain authoritative, not this potentially newer source archive.

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
maintenance holds the capture lock through checks and compaction; the first Sunday
of each month reads the entire repository, other weeks sample 5%. Normal failures remove temporary plaintext;
a forced kill may leave private staging: inspect before deleting. Monitor unit
failures and perform a restore rehearsal quarterly.
A local `system backup` does not resolve an offsite-backup incident.

## Empty VM rehearsal

Use an isolated Ubuntu 22.04 VM with SSH/sudo, 2 GB RAM and at least 20 GB disk;
prefer synthetic data first. Never bootstrap an everyday laptop, change production
DNS or run the same Telegram bot on both hosts. Use a private VM disk for real data.

Copy `deploy/ansible/inventory/example.yml` to `.private/recovery-inventory.yml`.
Set the target, user, disposable flag, approved restore roots and Compose projects
in dependency order (panel, API, gateway), including overlays. New snapshots record
project/release paths automatically; explicit entries support older backups. Review
`recovery_project_order` for other stacks. Verify SSH fingerprints.
Run from the laptop:

```sh
./deploy/ansible/recover .private/recovery-inventory.yml
```

The command installs its pinned controller environment if missing, bootstraps the
target and pauses if repository credentials need setup. Enter those **on the target**
using `configure-b2` then `prepare-s3`, with the existing repository password.
It downloads the latest tagged backup, verifies it and restores captured images
with `--no-build --pull never`. Applications are not started by the restore stage.

Rehearsal activation binds the three Braavos projects to loopback. It verifies DB
identity, panel plans/credentials, token retrieval, URI/Xray/info output and loopback
REALITY traffic, then reboots and checks again. Only those containers gain reboot
persistence; bots and scheduled jobs stay disabled. The aggregate report is saved
under `.private/recovery-reports/` without credentials or customer identifiers.
The Braavos verifier expects its three project/container names and standard paths;
other deployments must adapt those checks, not claim an untested successful restore.

For an already restored target, resume validation with:

```sh
./deploy/ansible/recover .private/recovery-inventory.yml --finish
# Verify an already running restored VM without reconfiguration or reboot:
./deploy/ansible/recover .private/recovery-inventory.yml --check
```

Production activation additionally requires `recovery_security_validated: true`,
`recovery_addresses_reviewed: true` and `recovery_address_map`, mapping old public
IPv4/IPv6 to addresses assigned to the replacement. Use `deploy/ansible/run host` on a fresh target for the separate transactional
SSH/UFW bootstrap; then update the inventory user/port. DNS cutover and scheduled-job
handover remain explicit; do not copy host networking.

Restore refuses populated destinations, databases/volumes and staging. It is one-time,
not an upgrade/convergence tool; use the finish path after a completed restore.
The restore stage does not activate captured systemd units. Reviewed production
activation installs them; owner-only DNSTT activation requires
`recovery_enable_personal_dnstt: true`. Bots/timers require the explicit
cutover/handover flags. Rehearsals leave operational jobs disabled.
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

## Two-server replacement

The normal operator interface is two commands, from the laptop:

```sh
./deploy/restore-foreign
./deploy/restore-domestic
```

Use the same private plan, foreign first. The commands aggregate fresh-host security,
restore, peer mapping, archive transfer, observer trust, activation and job handover.
They prompt for console/identity verification, existing storage credentials, old
writer/node handover and DNS cutover. See the [short deployment guide](../deploy/ansible/README.md).
No old server is stopped and no public DNS record changed without your action.
Preserve old hosts until acceptance; after new writes, rollback must account for
changed data. Stage-specific commands above remain for contributors and incident
recovery, not the normal paired procedure. A fresh paired rehearsal is still required.

## Bounded storage and receipt objects

[Ledger storage and recovery](billing.md#coordinate-recovery) describes the optional
shared 10 GB budget, 6 GB recovery allocation, protected restore points, receipt
capture/rehydration and activation gates. Without its private `storage` configuration,
legacy backup capture does not enforce that capacity limit. Install the matched
`storage_budget.py` helper and include it in the recovery inventory.
