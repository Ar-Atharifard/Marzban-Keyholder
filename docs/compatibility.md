# Compatibility commitments

`/s/{token}` is the stable customer path. URI/base64 and Xray JSON output remain
available. Existing API fields/defaults, legacy policies and historical migrations
are regression tested. Unsupported old profile names do not silently reactivate.

Changing a provider mapping or panel selections preserves the public token.
Repeated canonical registration and link retrieval do not generate a new token.
Rotation is explicit; revocation is terminal. Preserve the public domain/path,
database and vault key across host moves. Availability still depends on upstream
account status/quota/expiry and infrastructure; this is not an uptime guarantee.

Configuration now supports `upstream` profile authority; `marzban` remains an alias.
The old `MARZBAN_*` settings and `marzban-default` identity remain compatible.
Explicit backend configuration overrides legacy upstream settings. No migration
or token rotation is required merely to upgrade to the portable release.

Provider/CLI additions do not make every panel, Xray feature or client supported.
Publish tested capabilities and use new backend IDs for different account systems.
Changes to shared Docker/ingress settings require a deployment review even when
application API contracts are unchanged.

The optional `format=info` usage view and `subscription-userinfo` response header
are additive. When metadata exists, URI output also has one leading local-only
informational record; existing real profile URIs and their relative order remain
unchanged, and Xray JSON output is unchanged. Token validation, defaults and URLs
retain their semantics. Contract tests explicitly review these additions.
