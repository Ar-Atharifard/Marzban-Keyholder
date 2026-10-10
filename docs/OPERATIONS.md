# Operations and release gates

This runbook prepares a release. Production operations require explicit approval.
Run development checks on the workstation with synthetic data, not on the VPS.

## Current baseline (October 10, 2026)

- Remote workspace: `/srv/keyholder`, branch `master`, HEAD `5236238`.
- The workspace has unfinished changes and two untracked files. Do not build it as-is.
- The running image uses older ECH-capable code. Its renderers differ from HEAD.
- Production SQLite is at Alembic revision `0001`.
- Keyholder listens on loopback port 18000, with one worker and host networking.
- Marzban's API listener was observed on loopback port 8000; OpenAPI reports 0.8.4.
- The gateway handles gRPC on TLS port 2053 to Marzban loopback port 12084.
- Root read-only inspection confirms Hiddify owns 80/443. The complete public
  Keyholder path and external CDN rules remain unverified; see `CUTOVER.md` for
  the Marzban-only transition candidate and dependencies.
- Failed units: `cloudzy_agent`, `mtproxy`, `netfilter-persistent`. Diagnose before
  changing them. A failed persistence service does not prove the active firewall is absent.
- Follow-up read-only check: Cloudzy agent and netfilter persistence are enabled,
  loaded and failed with exit status 1. `mtproxy` has no loaded unit file and retains
  failure status 203. No journal entries were readable by this account; no cause
  or cleanup action is established by these metadata alone.

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

Latest local verification: 68 tests passed, Ruff lint/format checks passed, strict
mypy passed for `src`, `tests` and `scripts`, and `git diff --check` passed. Compose
rendered using `.env.example`; selected-field checks confirmed host networking,
loopback binding, one worker, no published ports, read-only root, dropped
capabilities, no-new-privileges, rotated logs and the loopback healthcheck. No image
was built or deployed. The suite emits an existing Starlette/httpx deprecation
warning; dependencies remain locked and unchanged.

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
backup to the development workstation. The utility currently lives in the local
checkout; transferring or running it remotely is a separate approved step.

A backup is not verified recovery until an isolated restore proves database
integrity, Alembic revision, customer IDs, token hashes, mappings, policies, and
ECH settings survive. Backups contain sensitive information and need the same
access restrictions as the live database. Off-host encrypted storage, scheduling,
retention, encryption-key custody and recovery objectives require owner decisions.
No backup scheduling or off-host upload has been configured.

The local recovery rehearsal now backs up a legacy fixture before migration, restores to
a separate file, and verifies all customer, mapping, backend, application-data and
Alembic rows against the original snapshot. It also verifies the migrated source
remains at revision 0002. This is a synthetic rehearsal, not a production backup.

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

Nginx will own 80/443; existing Marzban proxy ports remain unchanged. Preserve
2053 during the transition until external origin rules are verified. See
`CUTOVER.md` for the staged retirement and rollback procedure.

Downgrade preflight refuses to restore any policy if one customer has changed its
policy after migration. This prevents overwriting later administrator edits. The
old ECH settings record is retained. Local migration tests verify restoration,
identity preservation, schema agreement and refusal without partial restoration.

Keep migrations and container replacement separate. Avoid rebuilding a dirty
production workspace. Keep the previous image available locally; never rely on a
mutable tag as the sole rollback reference. Image pinning and changes to production
Compose configuration require a separate reviewed operational change.

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

- Complete privileged routing inventory and firewall-persistence diagnosis.
- Choose canonical private Git hosting and deployment credentials.
- Choose backup storage, encryption, retention and recovery objectives.
- Review gateway/Marzban log rotation and exact image pinning independently.
- Confirm admin-route exposure and subscription-token redaction across the full ingress.
- Keep health checks lightweight. Add canary delivery monitoring separately from DB liveness.

No infrastructure configuration changes are performed by this runbook.
