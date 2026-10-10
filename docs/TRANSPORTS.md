# Active transport configurations

Both current Marzban users select all ten profiles. The previous WS/XHTTP pilot
has ended with the owner's approval. Keyholder follows current supported panel
selections on every fetch, so later user edits require no backend policy/code change.

| Profile | Protocol / transport | Public delivery | Origin |
|---|---|---|---|
| `tcp_reality` | VLESS TCP REALITY | Existing IPv4:8443 | Existing inbound |
| `xhttp_reality` | VLESS XHTTP REALITY | Existing IPv4:9443 | Existing inbound |
| `tcp_reality_ipv6` | VLESS TCP REALITY | Existing IPv6:10443 | Existing inbound |
| `shadowsocks_ipv6` | Shadowsocks standard AEAD | Existing IPv6:10444 | Existing inbound |
| `grpc_cdn` | VLESS gRPC TLS | Titan / Cloudflare | Loopback:12084 |
| `ws_tls_cdn` | VLESS WebSocket TLS | Titan / Cloudflare | Loopback:12085 |
| `xhttp_tls_cdn` | VLESS XHTTP packet-up TLS | Titan / Cloudflare | Loopback:12086 |
| `trojan_grpc_cdn` | Trojan gRPC TLS | Titan / Cloudflare | Loopback:12087 |
| `vmess_httpupgrade_cdn` | VMess AEAD HTTPUpgrade TLS | Titan / Cloudflare | Loopback:12088 |
| `trojan_reality_ipv6` | Trojan TCP REALITY | IPv6-only:11443 | New inbound |

The original seven inbounds remain unchanged. Existing proxy credentials,
quota/expiry/status were preserved while granting the new families to both users.
The user-specific Shadowsocks AEAD method is preserved, including ChaCha20-Poly1305;
no unsupported 2022 variant or compatibility service is introduced.

New CDN templates use only `titan.javatechpack.ir`, verified TLS and disabled MUX.
New gateway routes enforce Titan and return 404 for Sealord. Existing Sealord
routing remains untouched, but Keyholder's configured CDN allowlist delivers only
Titan. All CDN Xray listeners bind loopback and rely on Nginx/Cloudflare TLS.
Direct IPv4 is used only by the preserved REALITY profiles. The third addition
binds the existing public IPv6 address; there is no new plain direct IPv4 profile.
REALITY still reveals its direct endpoint to the client; it is not an IP-hiding CDN.

## REALITY target

The new IPv6 Trojan profile uses `www.nlnet.nl:443`. A bounded VPS probe checked its
certificate/TLS 1.3/H2 and measured roughly 96 ms. Installed Xray's own TLS probe
confirmed TLS 1.3 and X25519MLKEM768; actual REALITY-to-HTTPS traffic passed in an
isolated loopback test and through the live IPv6 inbound for both users. Existing
Microsoft targets remain unchanged to preserve working configurations.

The [official REALITY documentation](https://xtls.github.io/en/config/transports/reality.html)
explains target/SNI compatibility and recommends a target in the same ASN when
possible. NLnet is a validated alternative, not a claim of optimal ASN camouflage
or superior Iranian-network reachability. Public targets can change; retest before
switching existing target/SNI pairs. Do not pick a target solely for obscurity.

## Validation and operating constraints

The installed Marzban parser, host schema and Xray startup checks accept all ten
inbounds. Nginx syntax validation passed before a graceful reload. After applying
the new core and user permissions, runtime registration was refreshed through
Marzban's core-config API, which reloads authoritative DB users. Startup acceptance
alone did not establish live connectivity; actual traffic checks were required.

Guarded private DB-clone checks for each current user confirmed URI and Xray output
contain ten profiles, the installed core accepts each generated client config,
and all ten complete certificate-verified HTTPS requests with nonempty responses.
The CDN paths were tested through Cloudflare. Temporary clients/containers were
removed; no production token was used in printed commands or logs. XHTTP `extra`
removal passed for URI queries and JSON `xhttpSettings`.

The original fixtures/defaults and existing API operations remain contract tested.
VMess uses alterId zero and AEAD; insecure TLS, direct Trojan IPv4 and literal-IP
CDN endpoints are rejected. These are protocol/transport combinations, not ten
independent protocols. Sharing gRPC or Cloudflare creates shared failure domains.

The owner reports MCI working with gRPC/Shadowsocks, Irancell with slow gRPC, and
no working profile on AUT. VPS checks cannot guarantee Iranian ISP performance,
DPI resistance or client-version compatibility. Refresh the same subscriptions
and test the additions on the actual networks. IPv6 profiles require IPv6 access.
Titan-only CDN profiles remain vulnerable to a shared hostname/provider block.
Adding another provider/node requires a separate business/infrastructure decision.

## Recovery

Private original core/gateway/host/user snapshots are under
`/var/backups/keyholder-registry/<timestamp>`; later full recovery sets are under
`/var/backups/keyholder-final` and `keyholder backup`'s reported directory. Candidate
transport files are under `/opt/braavos-panel/next-protocols/<timestamp>`.

Remove additions by restoring the saved core via Marzban's authenticated API,
restoring Nginx in place and reloading only after syntax validation, and restoring
only affected new host rows. A core reload briefly reconnects proxy sessions.
Preserve live databases and canonical tokens; never restore a whole user DB merely
to remove protocol additions. Retest the retained seven paths and subscriptions.
See [operations](OPERATIONS.md) for image/schema rollback and vault-key custody.
