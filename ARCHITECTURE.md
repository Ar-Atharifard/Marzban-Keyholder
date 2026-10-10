# Keyholder boundaries

`main.py` owns the FastAPI factory, lifecycle, one pooled HTTPX client, single-process rate limiter, sanitized errors and route-template logging. Startup neither creates tables nor migrates data. Public Swagger, ReDoc and OpenAPI HTTP endpoints are disabled.

`api/public.py` resolves a subscription bearer token by SHA-256, checks local status, loads its mapping, fetches links through a trusted adapter, reads the compatible policy and renders a subscription. The mapping and policy are materialized and the database read transaction is
closed before awaiting the upstream. The fetch has a total deadline. `/health` checks database connectivity only. No GET mutates stored policies or customer identity.

`api/admin.py` authenticates an environment bearer key with constant-time digest comparison. It manages local customers, mappings, policies, statuses and token rotation. It never provisions upstream users. Revocation is terminal. Policy PATCH replaces the whole policy; it is not a merge. ECH settings endpoints are retired.

`models.py` and `db.py` own SQLAlchemy persistence. Customers, backend references and mappings are distinct records. Raw subscription tokens are never stored. `ApplicationData` retains dormant ECH data and migration archives for recovery; there is no runtime settings API. SQLite connection setup enables foreign keys and WAL. Schema and explicit data evolution belong to Alembic.

`policies.py` provides conservative read compatibility for legacy policy JSON: retain supported selections, discard retired fields, and never grant new families implicitly. Both public subscriptions and admin views use it. Invalid stored policies produce an empty selection. API input validation remains strict. Migration `0002` archives original/applied policies and enables all five profiles for existing customers as approved by the owner. It preserves all identities. Read compatibility does not independently expand explicitly stored selections. Downgrade preflights every policy and refuses to overwrite subsequent administrator changes. Historical migrations must not import live defaults.

`backends/base.py` defines the read-only adapter boundary and sanitized errors. `backends/marzban.py` owns panel authentication and response validation. Its only panel operations are login and fetching a mapped user. Redirects and environment proxy settings are disabled; HTTPS verification is enabled. Responses and link counts are bounded. Concurrent expired-token requests share refresh state. Only `marzban-default` is registered. Database backend rows do not enable arbitrary URLs or automatically instantiate new providers.

`rendering/profiles.py` converts supported VLESS and Shadowsocks links into immutable provider-neutral profiles. It validates addresses, UUIDs, REALITY keys/short IDs, transport metadata and the supported cipher. It selects seven supported profile families, retaining the original five as defaults and requiring explicit opt-in for the new titan TLS CDN WebSocket/XHTTP families, preserves allowed upstream fields and does not synthesize new endpoints. `extra` is never copied into an XHTTP profile. ECH generation is retired.

`rendering/renderers.py` rebuilds base64 URI subscriptions or an Xray client JSON array. JSON RAW is normalized to TCP. XHTTP and gRPC omit incompatible flow; MUX is off. IPv6 URI literals are bracketed. gRPC TLS links represent the external gateway, not the plain loopback inbound. TLS does not independently prove CDN use. Selection uses `format=uri|xray` or the opt-in `Keyholder-Xray` User-Agent marker.

`rate_limit.py` owns bounded single-process fixed-window limiting. Each public token has its own SHA-256 bucket. Admin requests use a separate immediate-peer bucket; arbitrary forwarded headers cannot choose identity. Keep one worker until a reviewed distributed-limiting design is needed. No Redis service is required now.

`scripts/backup_database.py` is an explicitly invoked operator tool using SQLite's online backup API. It is never run by the application. Tests rehearse backup and restore with synthetic data. Production backup storage and scheduling are separate operator decisions.

The same-VPS deployment uses host networking and loopback ports 18000 for Keyholder and 8000 for Marzban. Public routing, TLS and firewall management remain separate. Preserve the public domain and Keyholder database through panel/VPS migration. Moving Keyholder away from Marzban requires a future secured synchronization design with snapshot freshness, atomic publication and revocation rules. No snapshots, background synchronization, stale serving or multi-node orchestration exist today.
