# Operations

## Daily checks and backup

Use `keyholder status`, `health`, `doctor`, `users`, `inbounds` and `check USER`.
`doctor` checks SQLite integrity, vault retrieval and selected-provider inventory
when supported. `/health` does not establish panel or proxy connectivity.

`keyholder backup` makes a private same-server recovery set: an online SQLite
snapshot and its vault-key environment, plus explicitly configured files/SQLite
sources. Include private panel access metadata when using a secret panel prefix.
Root-owned mode-0600 configuration selects paths; backup directories are root-only.
A copy on the same disk is not protection against host loss. Choose encrypted
external storage, retention and restore objectives separately.

Rehearse restoration in an isolated environment. Verify integrity, schema revision,
customer IDs, hashes, encrypted tokens and mappings. Keep the original public URL
and vault key. Do not restore old rotated tokens without a deliberate decision.

## Release

1. Run local tests/static checks, fresh migrations and packaging validation.
2. Build an immutable image locally; record its digest and previous release.
3. Back up the live DB/key and affected configuration; review migrations.
4. Prepare exact deployment, downtime, rollback and validation steps.
5. Recreate only Keyholder with reviewed environment/networking/volume settings.
6. Check health and existing subscriptions without printing their bearer URLs.

Do not build on a constrained production host, restart Docker globally, run blind
Git pulls over production-only changes, or migrate on every application startup.
Shared ingress changes require syntax checks and graceful reload with recovery
copies. Core changes can interrupt active proxy sessions even if URLs stay stable.

## Private panel prefix

The optional `scripts/render_panel_gate.py` generator creates a private Nginx
snippet and access metadata, refusing overwrite and not printing the entry URL.
The panel remains on loopback and still requires its own login. The generated
files contain an access secret: keep them outside Git and mode 0600.

```bash
python3 scripts/render_panel_gate.py --hostname panel.example.com \
  --output /private/path/panel.conf --access-file /private/path/panel-access.json
```

Include the snippet in your gateway's `http` block with the referenced certificate
files. Configure `panel_access_file` in the dispatcher, then retrieve the bookmark
with `keyholder panel-url` in a terminal. Validate HTML, module assets, login/API
and WebSocket traffic against your installed panel version before activation.
The example targets Marzban's `/dashboard/`, `/statics/` and `/api/` layout; verify
the layout again after panel upgrades. Old public dashboard/API/asset paths return
404 on this hostname. Existing subscriptions on other hostnames remain separate.

A random path reduces discovery; it is not a substitute for authentication and
cannot hide the hostname or guarantee resistance to ISP filtering. Disable path
logs/caching, set no-referrer and keep the panel bookmark private. Gateway files
must be written in place if Docker uses a single-file bind mount; inode replacement
can leave the container reading the old configuration.
