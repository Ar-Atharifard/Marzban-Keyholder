# Performance and reliability review — October 12, 2026

## Verified state

- Production is Marzban/Xray + Nginx + Keyholder. No Hiddify runtime is involved.
- Keyholder uses one worker, shared bounded HTTP connections, SQLite WAL and a
  unique canonical registration per upstream username. Subscription reads close
  their database transaction before awaiting Marzban. User selections are read
  live; no backend policy edit or code change is needed when selecting inbounds.
- API memory was approximately 76 MiB, gateway 9 MiB, Marzban container 164 MiB.
  The VPS had 327 MiB available RAM, 115 MiB swap used and 8.7 GiB disk free.
  These are point-in-time observations, not capacity guarantees.
- BBR, `fq`, and TCP MTU probing are already enabled. Increasing buffers or adding
  more workers is not established as an improvement on this server.
- Nginx uses HTTP/2, streaming forwarding, bounded connection timeouts and long
  proxy-session timeouts. Subscription and panel access logs are disabled to avoid
  recording bearer URLs. Keyholder returns `Cache-Control: no-store`.
- The owner reports Cloudflare Full (strict), HTTP/2, HTTP/3, HTTP/2 to Origin,
  WebSockets and gRPC enabled, with no Cache Rules. These dashboard values were
  reported by the owner, not inspected through a Cloudflare API credential.
- All five original ECH CDN profiles passed a clean test from current Irancell
  IPv4. Ordinary Titan/Keyholder HTTPS requests timed out. Existing IPv4 REALITY,
  an HTTP/3 XHTTP candidate, and the exact community F&F preset did not pass.
  These findings are specific to this network, time and diagnostic Xray core.

## Highest-priority improvements

### 1. Preserve non-browser delivery in Cloudflare

Add an explicit Cache Rule with this expression and **Cache eligibility: Bypass**:

```text
(http.host eq "titan.javatechpack.ir") or
(http.host eq "keyholder.javatechpack.ir" and starts_with(http.request.uri.path, "/s/"))
```

This guards proxy traffic and bearer subscriptions against future cache changes.
Apex/other decoy assets can retain normal caching. No such rule was created by the
agent; Cloudflare dashboard access is required. Validate an authorized canary
subscription and every transport after the rule. Rollback disables only this rule;
no origin or customer URL change is involved.

Do not attach browser challenges, JavaScript optimization or interactive login
checks to subscription/transport requests. Scope necessary exceptions narrowly;
retain normal site and panel protection. Keep gRPC and WebSockets enabled and
HTTP/2 to Origin on. HTTP/3 may remain enabled for ordinary web traffic; its presence
alone does not make the tested proxy HTTP/3 path usable. Maintain ECH support.
If the browser/client downloader does not support ECH, a backend change cannot
change its TLS ClientHello; direct subscription update remains a separate issue
from ECH support in the proxy core.

Primary references:
[Cache defaults](https://developers.cloudflare.com/cache/concepts/default-cache-behavior/),
[HTTP/2 to Origin](https://developers.cloudflare.com/speed/optimization/protocol/http2-to-origin/),
[gRPC](https://developers.cloudflare.com/network/grpc-connections/),
[WebSockets](https://developers.cloudflare.com/network/websockets/),
[ECH](https://developers.cloudflare.com/ssl/edge-certificates/ech/).

### 2. Add tested transport patterns and measure them

Streaming XHTTP over HTTP/2 passed isolated VLESS and Trojan HTTPS tests from
Irancell. It changes the upload request pattern compared with packet-up. Keep
existing profiles while adding these alternatives. Measure authenticated success
rate and median/tail latency on each carrier; TCP ping or a successful TLS handshake
alone is insufficient. A larger number of profiles does not mean independent
network diversity. Different UUID/password protocols over the same HTTP transport
share important failure modes.

Keep client TLS certificate verification, native ECH/Chrome on the working DNS
CDN routes, and the XHTTP `extra` removal invariant. Do not distribute failed
HTTP/3/F&F experiments, unknown cipher labels, arbitrary origin IPs or mandatory
Aether/WARP setup as though they were Marzban-accounted profiles.

### 3. Protect and recover the single origin

Cloudflare-only origin access on CDN HTTPS ports, or Authenticated Origin Pulls,
can reduce origin bypass. Preserve SSH and explicitly allowed REALITY/IPv6 ports.
This is **not implemented**: firewall/mTLS changes need a separate reviewed
allowlist and owner approval, because a mistake can stop all CDN delivery.
Validate Cloudflare-origin reachability first; keep an SSH session open and a
rollback command ready. Full (strict) already verifies the origin certificate;
Authenticated Origin Pulls additionally verifies the connecting client.

[Full strict](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/),
[Authenticated Origin Pulls](https://developers.cloudflare.com/ssl/origin-configuration/authenticated-origin-pull/).

Backups currently live on the same VPS. Encrypted off-host backups and an isolated
restore drill are the most useful next recovery improvements. Provider, retention,
encryption-key custody, acceptable data loss and recovery time are owner decisions.
Do not upload plaintext databases or the vault key, and do not rotate public
subscription tokens as an incidental security maintenance step.

### 4. Maintain domestic-destination coverage

The active server rules block private networks, `geosite:category-ir`, `.ir`, and
`geoip:ir`, with `IPIfNonMatch` resolving otherwise-unmatched names. Repeated route
tests blocked known Iranian .ir/.com sites, a literal Iranian IP and an unfamiliar
hostname resolving to that IP, while routing a foreign site directly.

Geodata needs a documented trusted-source update procedure, validation, backup
and a planned Xray restart to load new data. No update timer was installed.
Encrypted/opaque connections to foreign literal IPs, unlisted Iranian-owned
services overseas and traffic outside the proxy are coverage limits. This is a
server destination policy, not a guaranteed classification of all content.

[Xray routing](https://xtls.github.io/en/config/routing.html).

## Scaling and operational improvements

1. Add lightweight scheduled health/backup verification before any monitoring
   stack. Check service health, disk headroom, memory pressure, DB integrity,
   canonical mappings, core/listener availability and an authenticated canary.
   Alert destinations and schedule need owner decisions. Never log subscription
   tokens, complete upstream configurations or HTTP-library exception text.
2. Record errors and request latency from existing secret-safe Keyholder logs.
   Optimize only measured bottlenecks. At present, filtering/network behavior has
   greater impact than loopback HTTP or SQLite overhead. If concurrent refreshes
   become a real load issue, deduplicate in-flight upstream requests; avoid a
   long cache TTL that delays panel disable/quota/selection changes.
3. Keep the API single-worker and bounded on this VPS. Adding Redis, queues,
   databases or more ASGI workers has no demonstrated benefit at current scale.
   Review Marzban memory/pid limits under representative load before imposing a
   cap: an overly small cap can kill the proxy core. Swap is currently modest.
4. Retain a known-good immutable image and tested backup. Define backup/release
   retention before automated cleanup; do not run blanket Docker prune or delete
   recovery archives casually. Continue building locally and deploying isolated
   releases, preserving the dirty historical production Git workspace.
5. Review panel login rate limiting: the current `$server_name` bucket is global,
   so abuse can throttle the administrator too. A trusted Cloudflare client-IP
   rate bucket plus a global ceiling is a possible improvement. Only trust
   Cloudflare IP headers from verified Cloudflare peers; never trust arbitrary
   public headers. This has not been changed.
6. Meaningful independent IPv4 resilience may require another origin/provider or
   another permitted CDN. Multiple profiles on one IP/CDN cannot remove that shared
   failure mode. Budget, provider and changes to the Titan-only policy are business
   decisions. No node, account, paid service or broad orchestration was created.
7. Keep server ports/routing stable while investigating. The gateway already
   listens on 443 and 2053 for Titan. Removing the 2053 origin rule is an optional
   simplification, not a proven speed improvement; coordinate dashboard and origin
   changes, validate every profile, and retain the prior rule for rollback.
8. Maintain a tested client/core support matrix. ECH and transport import behavior
   depend on the actual core and URI importer, not only the desktop app version.
   Do not claim server-side success proves all existing customer clients work.

## What has not been silently changed

No Cloudflare dashboard rule, paid service, DNS record, firewall, SSH configuration,
backup schedule, monitoring service, client application setting, legacy customer
URL, quota, expiry or credential has been changed by this optimization review.
The authorized transport rollout and documented server routing policy are separate
from these proposed improvements.
