# Providers and multiple backends

`KEYHOLDER_BACKENDS` is a server-owned JSON list. It replaces legacy `MARZBAN_*`
settings when nonempty. Each ID identifies a separate account namespace, with
independent credentials and HTTP authentication state.

```dotenv
KEYHOLDER_BACKENDS=[{"id":"west","provider":"marzban","config_ref":"west","url":"https://panel.example.com","username":"admin","password":"replace-privately"},{"id":"source","provider":"http_subscription","config_ref":"source","url":"https://export.example.com/accounts/{username}","token":"replace-privately"}]
KEYHOLDER_PROFILE_SOURCE=upstream
```

Store the real credentials only in the private deployment environment. URLs cannot
contain userinfo. Redirects are refused; caller input cannot replace source hosts.
The template has exactly one literal `{username}` placeholder outside the authority.
Mapping references retain the v1 contract: 3–32 ASCII letters/digits/underscores.
Use provider-specific adapters when a panel needs different identifier translation.

After applying configuration and restarting only Keyholder, explicitly register
its metadata with `keyholder backend-register` or `POST /admin/backends/register`.
Startup does not mutate the database. Existing provider/config-reference identities
cannot silently be changed under an existing backend ID; use a new ID and explicit
customer remapping. Removing a configured adapter makes its mappings unavailable.

Use `keyholder --backend west create alice` and `keyholder --backend west link alice`.
The same username on two backends represents two different accounts. Customer IDs
and subscription tokens remain independent of provider URLs.

## Capabilities

Marzban reads `/api/user/{username}` and enforces active status. Explicit panel
management is supported only for Marzban. The HTTP subscription adapter accepts
plain or base64 URI lines, limits body size/link count and maps HTTP 403/404/410 to
unavailable. It has no inventory/provisioning/quota API. Its source must enforce
account availability; a service returning usable links for expired accounts does
not provide expiry enforcement. HTML pages, arbitrary JSON and redirects are not
subscription-source formats.

## Add a panel

Implement `BackendAdapter.configurations(username)` in `src/keyholder/backends/`.
Return URI links; translate disabled/expired/missing accounts to
`UpstreamUnavailable`, and transport/schema failures to sanitized `UpstreamError`.
Reuse the shared HTTP client, bounds and deadlines. Register the factory/provider
in `registry.py` and typed configuration. Add mocked provider contract tests.

Provisioning is a separate capability: do not force read-only adapters to implement
panel management. Extend operator dispatch only for providers that support it.
No runtime executable-plugin loader or multi-node orchestrator is required.

Adapters may optionally expose `subscription_details(username)` returning
`SubscriptionData(links, status, info)`. This obtains request-local usage and links
in one upstream call; existing `configurations` adapters remain compatible and
omit unavailable usage information. `SubscriptionInfo` validates byte counters and
Unix expiry. The Marzban adapter uses current `used_traffic`, `data_limit`, `expire`;
the HTTP adapter accepts a validated standard `subscription-userinfo` header.
No shared adapter field stores another customer's metadata.
