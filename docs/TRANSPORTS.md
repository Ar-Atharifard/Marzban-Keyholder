# Active transport configurations

The five current Marzban users select twelve inbounds across eleven profile families, rendering nineteen configurations. The previous WS/XHTTP pilot
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
| `trojan_reality_ipv6` | Trojan TCP REALITY | IPv6-only:11443 | Existing inbound |
| `xhttp_tls_cdn` | VLESS XHTTP stream-up TLS | Titan / Cloudflare | Loopback:12089 |
| `trojan_xhttp_cdn` | Trojan XHTTP stream-up TLS | Titan / Cloudflare | Loopback:12090 |

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

## Historical initial expansion validation and operating constraints

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

## Native ECH and MCI IPv4 investigation (October 11, 2026)

An IPv4-only MCI hotspot test reached ordinary external websites but Titan and
Keyholder HTTPS stalled after TLS. The same Cloudflare edge answered its own
website; Titan worked with accepted native ECH. All five CDN transports then
carried verified HTTPS with synthetic runtime-only credentials and native ECH.
The matching ordinary-TLS gRPC control timed out. Alternate Cloudflare IPs/ports,
HTTP versions and the tested TCP ClientHello fragmentation patterns did not fix
ordinary Titan TLS. These observations suggest hostname-sensitive filtering;
they do not identify ISP internals or prove ECH is the only possible workaround.

Production delivery uses:

```dotenv
KEYHOLDER_CDN_ECH_CONFIG=cloudflare-ech.com+https://8.8.8.8/dns-query
```

This is a public ECH lookup, not a secret. Xray obtains current ECH metadata through
certificate-verified DoH and refreshes it according to DNS TTL. The exact suggested
`cloudflare-ech.com+udp://1.1.1.1` failed on this connection: public UDP replies did
not contain usable ECH metadata. Google DoH at its certificate-valid literal IPv4
address supplied metadata and all five authenticated proxy tests passed. No fixed
ECH key, background polling service or custom DNS resolver was added. CDN addresses
remain Titan hostnames; no transient scanned Cloudflare edge IP is hardcoded.
The resolver is operator-configurable and itself remains a reachability dependency.

Chrome fingerprint is used. TLS certificate checks stay enabled; arbitrary upstream
ECH, cipher suites, FinalMask and XHTTP `extra` remain excluded. Transport-specific
ALPN is preserved. No Marzban users, quotas, expiry, inbounds or credentials need to
change for this delivery setting. Native ECH is applied only to allowlisted TLS
address/SNI pairs, including VLESS gRPC/WS/XHTTP, Trojan gRPC and VMess HTTPUpgrade.

Refresh the existing subscription using a working connection (for example the
previously working IPv4/IPv6 APN), then test the saved new profiles on IPv4-only MCI.
A blocked subscription-download hostname does not become reachable until the client
uses a working proxy or another route; ECH in delivered profiles does not change the
application's separate HTTP subscription downloader. No subscription URL replacement
is needed. Exact installed v2rayNG version must be checked; current upstream source
imports ECH as `ech` in common URI queries, including standard VMess URIs.

Both IPv4 REALITY profiles pass origin-side authenticated HTTPS, with matching
key pairs and clocks. IPv4-only MCI failures require separate client/path tests;
changing the target arbitrarily is not justified by these findings. The three
IPv6-only profiles inherently require IPv6 connectivity under the owner's policy.

The supplied community guide also recommends client-specific F&F, WARP-in-WARP
and MASQUE/H2. Its reported carrier/firewall mapping is unverified. The installed
Xray feature names/configuration must be checked rather than copying client UI
labels into JSON. In particular zero-length TLS handshake fragmentation is tolerated
by some servers but rejected by Go TLS/REALITY. WARP/MASQUE introduce external
providers and different client/account integration; they are not automatically
Marzban-managed customer inbounds and were not added to this ten-profile deployment.
Irancell settings need an actual Irancell connection before any global rollout.

Primary references: [Xray native TLS/ECH](https://xtls.github.io/en/config/transports/tls.html),
[Xray FinalMask](https://xtls.github.io/en/config/transports/finalmask.html),
[v2rayNG common URI parsing](https://github.com/2dust/v2rayNG/blob/master/V2rayNG/app/src/main/java/com/v2ray/ang/fmt/FmtBase.kt),
[v2rayNG VMess parsing](https://github.com/2dust/v2rayNG/blob/master/V2rayNG/app/src/main/java/com/v2ray/ang/fmt/VmessFmt.kt).

ECH rollback affects only Keyholder delivery: recreate the API with the previous
immutable image and restore the previous environment (or clear CDN_ECH_CONFIG for
a compatible current image). Preserve live DBs and vault key; no migration or
Marzban/Nginx reload is required. Existing connections are unaffected; API recreation
briefly interrupts subscription requests. Verify API health, unchanged registration
rows, both rendered formats and actual CDN traffic after any release or rollback.

### Deployment results and direct subscription access

Code release `248804f` is active, with immutable image identity
`sha256:99f70ac196811264514bdee61543afdf790bd99e56580cd856a2b1e3211d7e2a`.
All three canonical registrations retain exactly their IDs, hashes, encrypted
retrievable tokens and mappings. Marzban plans/proxy credentials, core/gateway
files and proxy containers were compared unchanged. Live checks confirm ten
profiles per user, native ECH on five CDN profiles in both formats, no-store
responses and removal of XHTTP `extra`. Candidate private-clone tests carried
HTTPS through all ten transports for each of the three users. Workstation MCI
checks passed all five CDN transports with dynamic DoH; an additional renderer
check observed one transient gRPC reset, followed by a successful gRPC request to
the subscription endpoint. Reachability remains variable; do not promise every
attempt succeeds on every network.

The owner clarified that the desktop client is **v2rayN 7.25.4**, rather than
v2rayNG. Its standard VMess and common URI parsers accept `ech`, so the ECH-enabled
VMess URI format is supported. Its separate subscription downloader uses .NET
SocketsHttpHandler and has no ECH lookup/configuration in that code path. Profile
ECH settings apply to the proxy core, not to this independent downloader. See
[v2rayN 7.25.4 download implementation](https://github.com/2dust/v2rayN/blob/7.25.4/v2rayN/ServiceLib/Services/DownloadService.cs)
and [URI parsing](https://github.com/2dust/v2rayN/blob/7.25.4/v2rayN/ServiceLib/Handler/Fmt/BaseFmt.cs).

A direct IPv4 Go TLS test to Keyholder, with no proxy, returned the expected
HTTP 404 for the non-secret `/s/invalid` route and confirmed ECH was accepted.
The otherwise matching request without ECH timed out. A native-ECH gRPC proxy
also reached this endpoint from MCI IPv4. Keyholder therefore has no proxy
requirement: network interference affects ordinary hostname-visible HTTPS,
while direct ECH-aware HTTPS works. No route/authentication change at the server
can retrofit ECH into a client's TLS downloader. Keep the canonical URL. Initial
refresh can use the working IPv4/IPv6 APN; subsequent proxy-assisted downloads
can use an established ECH profile. Alternatively direct downloads require an
ECH-capable downloader. Do not switch to plaintext HTTP or disable certificate
checks to work around this problem. A separately tested download domain would be
an optional mirror/business decision, not an automatic customer URL migration.

Additional REALITY findings: Microsoft-target inbounds have matching keys and
server/workstation clocks. Both pass origin-side HTTPS. On MCI, Chrome, Firefox
and Safari authenticate REALITY but subsequent HTTP and HTTPS traffic stalls;
Edge did not authenticate in the tested runs. Supported nonzero TLS-record
fragmentation and smaller client TCP segments did not restore traffic. Temporary
Microsoft/NLnet REALITY listeners on unused ports also failed after authentication.
Ordinary, unauthenticated Microsoft HTTPS through the original REALITY fallback
ports completed TLS then stalled, while the normal Microsoft route returned 200.
This supports direct-path network filtering, not a demonstrated Marzban credential
fault. No existing target, port or customer profile was changed by the investigation.
Temporary users/listeners were removed. Zero diagnostic user counters were not
used as proof of dropped payload, because enabled counter policy was not established.
The two IPv4 REALITY paths remain unresolved on this MCI connection.

## Managed Cloudflare IPv6 alternatives (October 11, 2026)

The five Titan CDN inbounds can each have a second Marzban host entry using
`2a06:98c1:3121::7:443`, with Titan as both TLS SNI and HTTP Host/gRPC authority.
This is a Cloudflare edge address, not the VPS origin. All five transports passed
certificate-verified HTTPS tests from the IPv6-capable VPS without ECH. This
establishes server and transport compatibility; it does not establish reachability
on every Iranian access network. An IPv4-only APN cannot use these alternatives.

These are five address-family alternatives, not five new protocols or inbounds.
Marzban host settings control their presence, names and address; Marzban user
inbound selections still control access. Existing DNS/ECH entries stay intact.
Keyholder accepts literal CDN IPv6 addresses only inside Cloudflare's published
IPv6 ranges, with explicit allowed TLS SNI and matching HTTP identity. Arbitrary
IPv6 origins and all literal IPv4 CDN destinations remain rejected. Update this
checked-in range list only against https://www.cloudflare.com/ips-v6.
The IPv6 entries use Chrome, certificate validation, no ECH, no custom cipher
suites and no final mask. XHTTP `extra` remains omitted in both output formats.

The supplied community guide is not a guarantee of current ISP behavior. Two
methods are deliverable through this architecture: native ECH over CDN and
Cloudflare IPv6 CDN. Its `semi-python` cipher label is not a cipher-suite name
recognized by stock Xray 26.9.30: the TLS parser accepts colon-separated Go TLS
cipher names and silently ignores unknown names. Do not claim this label works
because configuration validation succeeds. `tlshello-0-len` is also a client UI
preset, not the structured Xray final-mask configuration. No unverified F&F
preset, WARP account, MASQUE account, Worker service or mandatory client setup is
installed. WARP/MASQUE recovery instructions from Aether cannot simply be added
as authenticated Marzban profiles with its quotas and user management.

Deployment validation: release `35180a5` now delivers fifteen entries to each of
three current canonical registrations. Every generated entry passed installed
Xray validation and authenticated foreign HTTPS from the VPS. The original ten
entries and all customer URLs/credentials were preserved. For VLESS/Trojan host
settings, Marzban 0.8.4 needs address `[2a06:98c1:3121::7]` to emit valid URI
brackets; VMess host settings need the bare address for its JSON payload. Both
normalize to the same IPv6 endpoint. Manage these alternatives in Marzban's host
settings for the corresponding five Titan inbounds; disabling the added host
entry removes just that IPv6 alternative on the next subscription refresh.

A temporary MCI experiment also tested supported structured zero-length TLS
record fragmentation with the native Go (`unsafe`) TLS fingerprint on WebSocket
and XHTTP, with ECH absent and without the unrecognized `semi-python` preset.
Both timed out. This was an approximation, not a verified test of the guide's
complete client-specific F&F implementation; no Irancell test was available.
Temporary accounts were removed and no final mask was deployed. MCI IPv4 ECH
checks still succeeded on WS, XHTTP and VMess; both gRPC checks showed transient
resets in this run. VPS validation passed for all profiles. This is not a claim
that every method is reliable on every carrier or APN.

Code-only rollback: use release `248804f` and its pinned image. To remove the
host expansion, restore the root-only `previous-hosts.json` from
`/var/lib/marzban/routing-recovery-20261011` through Marzban's authenticated
`PUT /api/hosts`; this does not restart Xray. The domestic routing policy is a
separate change and has its own rollback described in OPERATIONS.md.

## IPv4 streaming CDN expansion (October 12, 2026)

Two additional Titan inbounds use XHTTP `stream-up` over TLS HTTP/2: VLESS and
Trojan. Streaming upload produces a different HTTP request pattern from the
existing `packet-up` profile and avoids repeated upload POSTs. This is a transport
alternative, not proof that its TLS handshake bypasses every firewall. Both
isolated candidates passed certificate-verified HTTPS from the owner's current
IPv4-only Irancell connection, with native ECH and Chrome. Existing packet-up,
gRPC, WebSocket, HTTPUpgrade and REALITY profiles are preserved.

The gateway must forward the new routes with `grpc_pass` to their plaintext,
loopback-only XHTTP listeners. Ordinary `proxy_pass` HTTP/1.1 is not substituted
for the validated HTTP/2 streaming path. The server uses explicit `stream-up`,
and Marzban advertises that mode. XHTTP `extra` remains excluded from URI and JSON
subscriptions. Trojan XHTTP is the additive `trojan_xhttp_cdn` profile family;
existing family values/defaults, endpoints, token handling, URL paths and database
schema remain unchanged. The policy capacity increases from ten to eleven
families. Production's `profile_source=marzban` follows each user's panel selection
without backend database or per-user source changes.

Irancell diagnostics: all five existing native-ECH CDN transports passed a clean
run. Original IPv4 REALITY and an XHTTP HTTP/3 candidate failed. The initial
parallel exploratory probes shared a SOCKS port and are excluded from evidence;
clean repeats used separate ports. The guide's exact F&F settings were located in
PattNG's `my-releases` branch, `res/values/arrays.xml`. `semi-python` is a UI preset
that expands to explicit TLS cipher names; `tlshello-0-len` expands to two precise
structured fragment masks. Earlier approximate fragmentation was not the whole
method. Exact-mask tests with and without the cipher preset timed out at the
example Cloudflare address. No failed candidate is added to subscriptions.
WARP/MASQUE still require separate provider/client integration and are not
represented as Marzban-accounted customer profiles.

Primary preset source:
https://github.com/patterniha/PattNG/blob/my-releases/V2rayNG/app/src/main/res/values/arrays.xml

Completed rollout: five current users retain their original customer IDs, tokens,
mappings, credentials, quota and expiry. Each canonical URL renders nineteen
configurations. Both production-rendered additions passed HTTPS on Irancell IPv4
and a bounded 3 MiB upload (single observations: 1.33 seconds VLESS, 0.90 seconds
Trojan). All nineteen passed VPS HTTPS checks. Temporary runtime accounts were
confirmed absent, and the private rehearsal clone was removed. Exact F&F also
failed using the DNS-selected Titan edge; it remains diagnostic-only.

Recovery materials: `/var/lib/marzban/streaming-recovery-20261012` and the private
pre-change backup `20261011T214219.848765Z`. API rollback uses release `35180a5`;
transport rollback restores previous user selections, core and host templates,
then Nginx in place with syntax validation and graceful reload. Applying core
configuration briefly restarts Xray, while the API release replaces only its own
container. No production migration or subscription rotation was required.
