# Operations and release gates

This runbook prepares a release. Production operations require explicit approval.
Run development checks on the workstation with synthetic data, not on the VPS.

## Current baseline (October 11, 2026)

The approved Marzban-only cutover has been executed. Hiddify's application,
services, maintenance jobs and shell hooks have been removed. Recovery archives
remain private on the VPS. Shared OS packages and network tuning were retained.

- `/srv/keyholder` still has its original unfinished changes (14 modified and
  two untracked files), branch `master`, HEAD `5236238`. Do not reset or build it.
- Releases live separately in `/srv/keyholder-releases/<commit>` and use the
  existing root-only `/srv/keyholder/.env`. The active code release is `8e0a5ff`; previous compatible release `26e78c3`
  is retained for rollback, and the initial cutover was `b2fb14c`.
  Check the active container's Compose labels and the release `deployment.json`
  for the current commit and immutable image, rather than trusting a mutable tag.
- Production SQLite revision is `0003`. Two canonical users have retrievable encrypted
  subscriptions; two duplicate rows remain revoked as history. The owner approved
  token rotation. Marzban owns supported profile selection for every fetch.
- Keyholder: loopback 18000, one worker, nonroot, read-only root filesystem,
  dropped capabilities, no-new-privileges, and rotated Docker logs.
- Marzban API: loopback 8000, panel 0.8.4, Xray 26.9.30. Its running container and original seven proxy inbounds and existing credentials/plans were preserved;
  the approved expansion adds two Titan loopback profiles and IPv6 Trojan REALITY.
- Nginx: public 80/443 and retained 2053; gRPC forwards to loopback 12084.
  Only `/s/` is exposed for Keyholder; admin and health routes stay private.
- All ten profiles passed real HTTPS connectivity for both current users,
  including Cloudflare CDN paths and the IPv6 profiles.
- Cloudflare Full (strict), disabling Bot Fight Mode, and a `/s/`-scoped Browser
  Integrity Check exception were reported by the owner. Python, v2rayNG and
  browser probes now reach Keyholder without a challenge, returning the expected
  JSON 404 for `/s/invalid`, `no-store` and `DYNAMIC`. See `CLOUDFLARE.md`.
- Latest resource snapshot before final checks: 326 MiB available RAM, 116 MiB swap used, 8.7 GiB
  free disk. These are observations, not guaranteed capacity.
- Existing failed Cloudzy agent / netfilter-persistence state remains outside
  this cutover. It does not establish whether active firewall rules are absent.

## Local development

Use the local branch `fix/production-compatibility`. Its Git origin references the
VPS for provenance; do not push to the live deployment repository. Establish a
private canonical remote after the owner chooses its host and permissions.

Pushes to the VPS origin are disabled locally. Code-only source and deployed-package
snapshots are retained in `.audit/`, excluded from Git and Docker build context.
The original remote worktree remains untouched.

Keep `.env`, database files, credentials, certificates, and customer configurations
on their existing hosts. Use fixtures and disposable databases locally.

```bash
uv sync --frozen --extra dev --python 3.12
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src tests scripts
```

The full test suite must pass before a release is proposed. Tests must migrate
legacy fixture databases as well as create fresh schemas. Production database
migrations must never be used to discover compatibility problems.

Offline OpenAPI export is tested with injected fixture environment values: it
does not create the supplied database or include those secret values. The schema
describes both subscription media types and sanitized error bodies.

Latest local verification: 119 tests passed, Ruff lint/format, strict mypy and
`git diff --check` passed. A regression reproduces connection-pool exhaustion
under slow upstream requests and verifies concurrent subscriptions and health
remain responsive after releasing the read transaction before awaiting Marzban.
The existing Starlette/httpx deprecation warning remains; dependencies are locked.
Build images on the workstation, never on the resource-constrained VPS.

## Database backup and restore rehearsal

The standalone utility uses SQLite's online backup API, checks integrity and
foreign keys, creates a mode-0600 file, and refuses overwrites. It includes
committed WAL transactions. It does not export credentials in its output.

Test the utility on synthetic data first:

```bash
.venv/bin/python scripts/backup_database.py \
  --source /path/to/development.db \
  --destination /path/to/private-backups/development-snapshot.db
```

For production, an authorized operator must run it **on the VPS** with access to
the database volume and a private backup directory. Do not copy a production
backup to the development workstation. Keep the utility and production snapshots on their respective hosts.

A backup is not verified recovery until an isolated restore proves database
integrity, Alembic revision, customer IDs, token hashes, mappings, policies, and
ECH settings survive. Backups contain sensitive information and need the same
access restrictions as the live database. Off-host encrypted storage, scheduling,
retention, encryption-key custody and recovery objectives require owner decisions.
No backup scheduling or off-host upload has been configured.

The local recovery rehearsal now backs up a legacy fixture before migration, restores to
a separate file, and verifies all customer, mapping, backend, application-data and
Alembic rows against the original snapshot. It also verifies the migrated source
remains at the expected migration revision. Production snapshots and isolated recovery rehearsals were also completed; see
`CUTOVER.md` for the private recovery inventory.

## Release procedure

Before asking for deployment approval, record:

1. The reviewed commit and image ID/tag, previous image ID, and migration revisions.
2. Passing tests and static checks, including old-policy and XHTTP-extra regressions.
3. A verified private database backup and tested recovery procedure.
4. Intended customer-visible profile changes, if any, approved by the owner.
5. The affected components, expected interruption, rollback steps and validation.

An ordinary Keyholder release affects only its API container and, if explicitly
approved, its database. Recreating the API can briefly interrupt subscription
refreshes. Previously downloaded proxy configurations continue independently.
Do not restart Docker, Hiddify, Marzban or the gateway as part of an API release.

The approved scope is Marzban-only. The owner approved retiring all Hiddify links
and enabling all five current Marzban profiles for existing and new customers.
Migration `0002` archives original policies and applies those five without
changing status, IDs, token hashes or mappings. Explicit administrator policies
remain supported after migration. Upstream permissions are not expanded by
Keyholder; only existing Marzban configurations are returned.

Nginx owns 80/443; existing Marzban proxy ports remain unchanged. Preserve
2053 during the transition until external origin rules are verified. See
`CUTOVER.md` for the staged retirement and rollback procedure.

Downgrade preflight refuses to restore any policy if one customer has changed its
policy after migration. This prevents overwriting later administrator edits. The
old ECH settings record is retained. Local migration tests verify restoration,
identity preservation, schema agreement and refusal without partial restoration.

Keep migrations and container replacement separate. Avoid rebuilding a dirty
production workspace. Keep the previous image available locally; never rely on a
mutable tag as the sole rollback reference. Use the release-specific image override; pin images by their recorded SHA256.

## Validation and rollback

After an approved release, validate `/health`, private admin authentication,
customer listing, and both subscription output formats using an owner-approved
canary account. Do not create customers or rotate tokens as an incidental health
check. Confirm the established domain/path and token handling still work, and
verify XHTTP output omits `extra` while retaining intended host/path fields.

Use clients with confirmed support for the relevant Xray transport, IPv6 and
REALITY fields before enabling new profile families for customers. The installed
Xray version alone does not establish client import or connectivity compatibility.

For code-only rollback, replace only Keyholder with the retained prior image.
For data-changing migrations, check whether the old application can read the new
data. If restoration is needed, stop **Keyholder only**, preserve the current
database securely for investigation, restore the reviewed snapshot with correct
ownership, and start the prior image. Restoring a snapshot loses changes made
after that snapshot; the owner must approve that recovery action.

## Remaining infrastructure decisions

- Diagnose pre-existing firewall-persistence failures in a separately reviewed task.
- Choose canonical private Git hosting and deployment credentials.
- Choose backup storage, encryption, retention and recovery objectives.
- Retain gateway image pinning and rotated logs; review Marzban log retention separately.
- Confirm owner client import/refresh; consider an explicit Cloudflare cache-bypass rule.
- Keep health checks lightweight. Add canary delivery monitoring separately from DB liveness.

Production changes require the owner's authorized scope; do not broaden a release to unrelated infrastructure.

## Production commands and isolation

Read the active release from the API container's Compose labels:

```bash
ssh braavos "docker inspect keyholder-api-1 --format '{{index .Config.Labels \"com.docker.compose.project.config_files\"}}'"
```

An authorized API replacement uses the recorded commit directory and existing
root-only environment file, without a build or dependency restart:

```bash
KEYHOLDER_ENV_FILE=/srv/keyholder/.env docker compose -p keyholder \
  -f /srv/keyholder-releases/<commit>/docker-compose.yml \
  -f /srv/keyholder-releases/<commit>/production.override.yml \
  up -d --no-build --no-deps api
```

The production override pins the image, limits API memory to 256 MiB and processes
to 128. These are ceilings, not reservations. Keyholder liveness checks the DB only.
The original workspace is excluded from deployment changes.

Gateway recreation must include its hardening override:

```bash
docker compose -p braavos-gateway \
  -f /opt/braavos-gateway/docker-compose.yml \
  -f /opt/braavos-gateway/production.override.json \
  up -d --no-build --no-deps gateway
```

The gateway uses its original image by immutable identity, read-only filesystem,
only CHOWN/SETUID/SETGID/NET_BIND_SERVICE capabilities, no-new-privileges, bounded
tmpfs, 128 MiB memory and 128 processes. Its healthcheck runs `nginx -t`; it checks
configuration/certificate readability rather than public delivery or gRPC.
Access/error logs are suppressed; Docker logs rotate at 10 MiB × 3.
Do not recreate from the base Compose file alone unless intentionally rolling
back hardening. A gateway recreation briefly interrupts gRPC and HTTP requests.

The validator `scripts/validate_server_release.py` refuses an unmarked/live
volume. It requires an isolated `/data` clone and `.release-rehearsal` marker,
then uses a synthetic clone token, real mapped upstream reads and the installed
Xray binary. `--connectivity` launches and cleans up temporary loopback clients;
it does not provision users or alter server inbounds. Run it only in a bounded,
nonroot disposable container as done during this cutover.

## Private administrator access

From the workstation, use an SSH tunnel with an unused local port:

```bash
ssh -N -L 127.0.0.1:28000:127.0.0.1:18000 braavos-keyholder
```

An administrator can then use `http://127.0.0.1:28000/admin/...` with the existing
Bearer key in a private API client. Do not put the key in shell history, request
logs or documentation; the tunnel does not replace API authentication. Close the
tunnel after use. Never copy the server `.env` to obtain credentials.

## Installed operator tools (October 11, 2026)

`keyholder` is installed in the workstation's `~/.local/bin` and on Braavos in
`/usr/local/bin`; server code is root-owned in `/usr/local/lib/keyholder-admin`.
See `scripts/admin/README.md` for every command and its safety/credential behavior.
Read-only installed `status`, `health`, `list` and mapped-user checks passed.
The tool installation did not rebuild/restart the API or migrate its database.

API/renderer snapshots and a fixed historical synthetic token hash are frozen
under `tests/contracts` and `tests/test_contracts.py`. Existing rendering contracts are preserved; canonical registration and
authenticated URL retrieval are documented reviewed changes. CI enforcement/private canonical Git hosting remain decisions.

Public browser management is now served by the existing HTTPS Nginx gateway at
`https://edge.javatechpack.ir/dashboard/`, using Marzban login. The owner selected
this simple model because Cloudflare Zero Trust is unavailable. The previous
private bookmark/tunnel candidate is inactive. No cloudflared service runs.
See `MANAGEMENT.md` for TLS/cache requirements, verification and rollback.

## Homepages, profiles and registry rollout

Domain/subdomain roots serve the recovered Java-learning static homepage. Panel,
subscription and transport routes remain separate. The WS/XHTTP pilot has ended:
both existing users select all ten configurations in Marzban. The original seven
inbounds, credentials and quota/expiry/status were compared unchanged when adding
the three new protocol combinations. New CDN routes/templates are Titan-only.

The runtime account refresh uses Marzban's core-config API, which restarts Xray
and includes users from its authoritative database. Applying a core config can
briefly reconnect sessions. Always test real traffic after changing user protocols;
parser/startup success alone does not prove runtime account registration.
Marzban and the Docker daemon were not restarted. Nginx was gracefully reloaded
only after syntax validation; its single-file bind mount must be updated in place
rather than replacing its inode.

Root-only snapshots before the registry migration are under
`/var/backups/keyholder-registry`; snapshots after rotation before the final API
update are under `/var/backups/keyholder-final`. Recovery sets include both DBs,
core/gateway configuration and the environment containing the vault key.
`keyholder backup` makes another complete private recovery set. Same-server
snapshots do not protect against VPS loss. No off-host upload/schedule is active.

The active source/image are recorded in the release's private `deployment.json`;
operator/docs commits are separately recorded in
`/usr/local/lib/keyholder-admin/installed.json`. API image identity is
`sha256:ef8302623098ba1bcf11da3fd259d4df2c4860200efa2ccca89113f170eaaa5d`.
The dependency update adds maintained cryptography/Fernet and its locked CFFI
requirements. Build on the workstation using the committed lock. Use
`deploy/Dockerfile.dependency-update` only with a verified base for dependency
updates; code-only builds require identical base/candidate manifests.

Rollback an API image without restoring an old DB when the old application is
schema-compatible. Preserve current hashes and the vault key. Restoring a
pre-rotation snapshot reactivates old URLs and loses later writes; it requires a
separate owner-approved full recovery. Removing the new profiles instead should
restore the saved core through Marzban's API and gateway in place, preserving user
DBs and current canonical URLs. Test the retained seven profiles after rollback.
Do not downgrade 0003 with live encrypted entries.

Use `--username` in the guarded validator to verify each current user, both output
formats and actual verified HTTPS through all selected transports. Keep clone DBs
and detailed diagnostics root-private and never transfer them to the workstation.
Iranian ISP reachability/client compatibility still needs customer-side testing.
Panel browser checks and owner confirmation passed; Cloudflare can reject generic
Python panel requests. The SSH panel command remains a recovery option.

## Native ECH API release (October 11, 2026)

The active API code is `248804f`, under `/srv/keyholder-releases/248804f`.
The production override pins image
`sha256:99f70ac196811264514bdee61543afdf790bd99e56580cd856a2b1e3211d7e2a`.
The previous `8e0a5ff` image/release remains available. Only the API was recreated;
no live migration, proxy restart, gateway reload, account/credential change or
subscription URL rotation was performed. The candidate reused byte-identical
pyproject/lock manifests and existing dependencies, built offline on the workstation.
All 131 tests, lint/format and strict source/operator type checks passed. Private
on-server clone validation passed both formats and all ten HTTPS transports for
OWNER, test1 and KasraRezaei. Live internal checks and `keyholder doctor` passed.

The private predeploy recovery set is
`/var/backups/keyholder/20261011T002618.220236Z`. Native ECH configuration is in
`/srv/keyholder/.env`; do not download the file. The release's `deployment.json`
and `predeploy-state.json` record identity/plan/config preservation and validation.
To invoke the CLI while already SSH'd into Braavos, use `keyholder --local doctor`
or `keyholder --local backup`; without `--local`, it intentionally initiates SSH
from the invoking workstation. The marked disposable rehearsal database contains
customer credentials and must stay server-private; remove it after validation.

For API rollback, use the previous release and its pinned image with the current
live volume/environment; schema stays 0003. The old code ignores the new native
ECH setting. Clear only that new setting if reverting the environment, preserving
all other values including the vault key. Do not restore a database snapshot:
canonical URLs and later legitimate writes must survive. API recreation briefly
interrupts subscription HTTP requests; proxy sessions continue. Validate health,
CLI doctor, registration invariants and both output formats afterward.

## Iranian destination policy (October 11, 2026)

Marzban's authoritative `/var/lib/marzban/xray_config.json` now blocks Iranian
proxy destinations for every inbound and user, independently of client routing:

```json
{
  "domainStrategy": "IPIfNonMatch",
  "rules": [
    {"type": "field", "ip": ["geoip:private"], "outboundTag": "BLOCK"},
    {"type": "field", "domain": ["geosite:category-ir", "domain:ir"], "outboundTag": "BLOCK"},
    {"type": "field", "ip": ["geoip:ir"], "outboundTag": "BLOCK"}
  ]
}
```

Keep domain and IP conditions in separate rules: fields in one rule are ANDed.
`IPIfNonMatch` also checks resolved IPs for unknown domains. Existing inbound
settings, sniffing, user credentials, private-network block, and outbounds were
preserved. The installed geodata supports both country labels. Geodata age and
coverage matter: this blocks known domains, `.ir`, and Iranian address ranges;
it cannot identify every Iranian-owned service hosted overseas. HTTPS requests
that specify a foreign literal IP may conceal their destination hostname on
inbounds without existing sniffing. Traffic routed directly by a client bypasses
the server entirely. Tunnels through an allowed foreign proxy can also evade a
destination block; this is not an exhaustive content filter.

The pre-change private backup is
`/var/backups/keyholder/20261011T011106.144826Z`. Previous and validated candidate
core JSON are root-only in `/var/lib/marzban/routing-recovery-20261011`.
For rollback, submit `previous.json` to authenticated `PUT /api/core/config`
from the VPS using locally configured operator credentials; never print the file
or bearer token. This restarts Xray briefly. Do not restart Docker or Marzban,
restore customer databases, regenerate credentials or alter subscriptions.
After a change, validate the core version, all listeners, known `.ir`/Iranian
`.com`/Iranian IP routing to BLOCK, foreign HTTPS, and both subscription formats.
The configuration is panel-managed: future core edits must retain these rules.
No geodata update schedule has been installed.
