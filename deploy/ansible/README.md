# Restore both servers

On the laptop, from the project root:

```sh
./deploy/restore-foreign
./deploy/restore-domestic
```

Run **foreign first**, then **domestic**. Both read `.private/replacement.yml`;
a different private plan can be supplied as an argument. Start from
empty Ubuntu 22.04 amd64 servers with IPv4/IPv6 and initial SSH key access. Keep
their provider consoles available. No whole-system upgrade runs.

Copy `replacement.example.yml` privately once. Enter the new and previous server
IPs, administrator key path and existing subscription hostname. No passwords or
API tokens belong in that file. `--plan-only` validates/renders without connecting:

```sh
./deploy/restore-foreign .private/replacement.yml --plan-only
```

The commands guide the remaining steps:

- **Foreign:** verify host identity, secure SSH/firewall, download the existing
  encrypted backup, restore databases/configuration/exact images, then confirm the
  old writers are stopped before starting the replacement. Bots/timers wait for
  the paired domestic command.
- **Domestic:** secure the new host, stream its archive from the recovered foreign
  host, restore all backhauls/node/gateway, configure monitoring trust, confirm old
  node handover, activate and test real dual-stack profiles. After the prompted DNS
  cutover and acceptance, enable foreign bots/alerts/renewal/backup jobs.

Enter B2 credentials and the **existing repository password** at the command’s
hidden prompts; they are sent over SSH and stored only in root-private files on
the foreign target, never in the plan or command arguments. Never initialize a new repository during recovery. Compare new SSH host
fingerprints with the provider console; discovery alone is not authentication.
The firewall uses reviewed TCP roles and official Cloudflare origin networks;
public UDP and personal DNSTT are not activated by this production workflow.

URLs, tokens, databases and tunnel keys are restored, not regenerated. No secret
archive is saved on the laptop. The workflow does not stop old production servers
or change DNS silently: confirm handover and perform the DNS changes when prompted.
Update laptop SSH aliases after accepting the new hosts. Generated replacement
aliases are in `.private/replacement-*/ssh.config`.

These are fresh-host restores, not live upgrades. Existing data/checkpoints cause
refusal. If interrupted, preserve the target and inspect the failed task; do not
wipe/retry blindly. Local tests and syntax checks passed; the complete paired
workflow still needs a fresh-host rehearsal. The 20-minute target is unproven.

## Internal commands

The files under `playbooks/` and `ansible/run` expose individual stages for
contributors and incident recovery. Normal paired deployment needs only the two
commands above. The old `ansible/recover` still supports an isolated foreign VM
rehearsal and its `--finish` / `--check` modes.

[Recovery reference](../../docs/disaster-recovery.md) covers backups and cutover.

## Portability

Use your own private plan: addresses, previous addresses, domain, initial SSH
account and administrator key are deployment inputs. The supported security
policy deliberately standardizes final access on `khadmin`, key-only SSH on 2222.
The paired workflow requires both IP families and the documented Marzban,
Marzban Node, Rathole, FRP and Xray layout. It restores an existing bundle; it
does not invent an initial service configuration or translate arbitrary stacks.
Lower-level inventories expose additional paths and service settings. Changes to
tunnel ports must also match the restored configurations, not just firewall rules.

B2 is the guided storage option. For another S3-compatible service, provision
`/etc/keyholder/recovery.env` on the foreign target before the foreign command:
root-owned, mode `0600`, with these values (one literal `KEY=value` per line,
without shell quotes or substitutions):

```text
RESTIC_REPOSITORY=s3:https://s3.example.org/bucket/keyholder
RESTIC_PASSWORD_FILE=/etc/keyholder/recovery-password
AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY
AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY
AWS_DEFAULT_REGION=YOUR_REGION
RESTIC_CACHE_DIR=/var/cache/keyholder-recovery
GOGC=50
```

Store the existing repository password separately in the root-owned `0600`
password file; keep `/etc/keyholder` mode `0700`. Use an existing repository
containing a compatible `keyholder-recovery-v1` snapshot. The workflow detects
this environment and skips B2 setup. Do not run `prepare-s3` for another provider:
that helper specifically resolves B2 endpoints. Provider compatibility still needs
a restore rehearsal; only B2 has been exercised for this deployment. Credentials
never belong in the public inventory, Git, or shell command arguments.
