# Development and architecture

Keyholder owns customer identity, stable tokens and provider mappings. The panel
owns proxy credentials, quota, expiry, status and inbound selection. With
`PROFILE_SOURCE=upstream`, selecting supported profiles in the panel needs no
Keyholder code change. No duplicate account database or background queue is needed.

```text
/s/{token} → customer/mapping → provider → validate profiles → URI or Xray output
CLI / Telegram management → host dispatcher → explicit panel/local operations
```

## Code map

| Path | Responsibility |
|---|---|
| `src/keyholder/main.py` | App lifecycle, shared HTTP client, sanitized logging |
| `src/keyholder/api/` | Public subscriptions and authenticated administration |
| `src/keyholder/backends/` | Provider adapters, authentication and bounded fetches |
| `src/keyholder/rendering/` | Profile parsing, validation, output and usage display |
| `src/keyholder/profile_types.py` | Supported families and compatibility defaults |
| `src/keyholder/{config,schemas,policies}.py` | Settings, request validation, legacy policy |
| `src/keyholder/{models,db,vault,security}.py` | SQLite, identity and token protection |
| `src/keyholder/cli.py` | Workstation CLI; `scripts/admin/` dispatches on the host |
| `scripts/{management_bot,monitor,recovery}.py` | Optional standalone operational tools |
| `migrations/`, `tests/contracts/` | Ordered DB upgrades and frozen API/output fixtures |
| `deploy/` | Optional deployment examples, services, Ansible and Worker |

Database tables: `customers` stores private name, nullable unique Telegram/phone,
status, token hash/ciphertext and timestamps; `customer_mappings` links identities
to backend/account; `registrations` enforces canonical registration; `backends`
stores nonsecret provider metadata; `application_data` preserves migration archives;
`alembic_version` records the schema. Contact fields never enter subscriptions or
Marzban. Changing a private customer name does not rename the upstream account.

## Work locally

Use Python 3.12+, a development branch, synthetic accounts and a disposable SQLite
DB. Follow the setup and verification commands in the [README](../README.md).
Do not use production credentials or databases in tests.

| Change | Edit and validate |
|---|---|
| API feature | `api/`, schemas, contract tests and API guide |
| Existing transport | Configure in the provider; verify both output formats |
| New family | `profile_types.py`, parser/renderers, real core/network checks |
| Database | New migration; test historical upgrades and recovery |
| Provider | Adapter, registry and mocked provider contract tests |
| Operator tool | Relevant script, CLI/bot flow and its documented deployment |

Tests use shared synthetic data in `tests/support.py` and the isolated API fixture
in `tests/conftest.py`. Test files should not import each other. Keep regressions
for stable URLs, token/credential protection, XHTTP `extra`, account selection,
migrations, recovery and alert deduplication. Use parametrized cases for distinct
input boundaries; avoid testing third-party behavior or copying implementation
constants into assertions. Frozen fixtures already cover exact legacy wire output.
Add a regression for a behavior change, not a separate test for every helper.
For a focused edit, run its test module first, then the full checks before review.

## Provider boundary

`BackendAdapter.configurations(username)` returns URI links. Disabled/missing
accounts raise `UpstreamUnavailable`; fetch/schema failures raise sanitized
`UpstreamError`. Optional `subscription_details()` returns `SubscriptionData`
with validated usage/status in the same request. Never store customer-specific
metadata in shared adapter state. Reuse pooled HTTP, bounds, deadlines and TLS
verification. Provisioning is separate from read-only subscription delivery.

Marzban supports inventory/provisioning through the CLI. The HTTP adapter accepts
plain/base64 URI exports and validated usage headers; it has no provisioning or
inventory API. Its source must enforce account availability. See [installation](getting-started.md)
for multiple-provider configuration.

## Compatibility and publication

Preserve `/s/{token}`, existing API fields/defaults, historical migrations and frozen
fixtures. Registration/retrieval returns the same token; mapping and panel changes
must not rotate it. Explicit rotation/revocation remains explicit. Preserve XHTTP
`extra` removal, certificate verification and credential redaction. Local revocation
stops delivery, not previously downloaded proxy access: enforce that in the panel.

Run one worker with SQLite. Shared rate limits, replicas, PostgreSQL and billing
are not implemented. `/health` checks the DB, not upstream or ISP reachability.

Public docs describe reusable behavior. Keep real inventories, personal guides,
network tests and credentials in ignored `.private/`; ignored does not mean encrypted.
Never publish private Git history. Export reviewed source into a fresh repository:

```sh
uv run python scripts/export_source.py --output /private/path/keyholder-source.tar.gz
```

The exporter excludes private files/Git metadata but is not a full secret scanner.
Scan export and original history privately with Gitleaks; verify installation,
packaging, migrations, license and author metadata before publishing. CI uses
synthetic data and never deploys production.

The experimental FF/FRAG delivery presets and their settings have been retired.
Remove `KEYHOLDER_FF_*` and `KEYHOLDER_FRAGMENTATION_*` entries from deployment
configuration when upgrading. Native protocols and personal MASQUE are unaffected;
Keyholder still ignores arbitrary upstream masks and cipher overrides.

## Upstream licensing

Keyholder's adapter communicates with a separately running Marzban HTTP API.
The public source and Keyholder image do not vendor Marzban or Marzban Node.
Their current upstream licenses are AGPLv3:
[Marzban](https://github.com/Gozargah/Marzban/blob/master/LICENSE) and
[Marzban Node](https://github.com/Gozargah/Marzban-node/blob/master/LICENSE).
Check the exact version you deploy or redistribute.

API integration alone does not automatically require relicensing Keyholder.
Separate programs can retain separate licenses, but HTTP or separate containers
alone do not establish independence: code reuse and the nature of the combination
matter. See the [GNU FAQ](https://www.gnu.org/licenses/gpl-faq.en.html#MereAggregation).
Keep the service boundary; review licensing before importing or adapting upstream code.

Preserve upstream copyright and license notices when distributing upstream copies.
For images/binaries, satisfy the applicable corresponding-source requirements;
a generic link to the latest repository is not necessarily sufficient. Modified
AGPL services must offer their corresponding source to remote users as required
by section 13. These obligations concern the covered upstream work, not an
automatic license change for every service that calls it.

Recovery bundles can contain upstream source and images as well as secrets. Keep
them private; Keyholder's MIT license does not cover their third-party contents.
The source exporter filters private files, not license compatibility. Review any
redistribution separately; attribution alone does not fulfill every AGPL obligation.
