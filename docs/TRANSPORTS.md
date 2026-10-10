# Titan transport expansion: prepared, not activated

The original five live inbounds remain unchanged. The candidate adds two VLESS
transport combinations; it does not claim seven unrelated wire protocols.

| Profile | Public route | Private origin | Purpose |
|---|---|---|---|
| Existing TCP REALITY | Existing IPv4:8443 | Existing Xray inbound | Direct REALITY fallback |
| Existing XHTTP REALITY | Existing IPv4:9443 | Existing Xray inbound | Different direct transport |
| Existing TCP REALITY IPv6 | Existing IPv6:10443 | Existing Xray inbound | Alternative address family |
| Existing Shadowsocks IPv6 | Existing IPv6:10444 | Existing Xray inbound | Different protocol and address family |
| Existing gRPC CDN | Existing titan route | Loopback:12084 | HTTP/2 through Cloudflare |
| New `ws_tls_cdn` | Titan HTTPS:443, private WS path | Loopback:12085 | WebSocket over HTTP/1.1 |
| New `xhttp_tls_cdn` | Titan HTTPS:443, private XHTTP path | Loopback:12086 | XHTTP packet-up through CDN |

New host templates advertise only `titan.javatechpack.ir`, verified TLS, no MUX,
and no direct IPv4 endpoint. REALITY remains the explicit IPv4 exception; it does
not hide the address from a client. No new sealord path or hostname template is
added. Existing sealord/gRPC routing remains for compatibility. CDN inbounds listen
only on loopback; their public TLS terminates at the existing Nginx gateway.

The owner reports MCI working with gRPC and Shadowsocks, Irancell with gRPC at
roughly one-second latency, and no working profile on the AUT network. These are
reports, not independently measured findings. No latency/DPI resistance guarantee
can be inferred from VPS tests. All CDN routes share titan and Cloudflare, so a
hostname/provider block can affect them together. No IPv6 service helps a network
without IPv6 reachability. A genuine additional infrastructure failure domain would
need another permitted hostname/provider or node, which is outside this change.

The Xray project documents [WebSocket transport](https://xtls.github.io/en/config/transports/websocket.html)
and [XHTTP modes/CDN behavior](https://github.com/XTLS/Xray-core/discussions/4113).
Packet-up is chosen for the first XHTTP CDN pilot, with ordinary HTTP proxying and
request/response buffering disabled. This uses the existing supported Xray core;
no unofficial fork, arbitrary fragmentation, ECH or heavyweight service is added.
Client support must be checked on the actual apps. XHTTP `extra` remains removed
from issued URI and JSON output.

## Readiness and activation gate

- Candidate files are private in `/opt/braavos-panel/transport-expansion`.
- The installed Marzban parser, host-settings schema and Xray startup-config test
  accepted the candidate with all five existing inbounds preserved.
- The full Nginx candidate passed syntax checks. Paths are generated only on VPS.
- Local renderer/API tests retain old fixtures/defaults and reject literal-origin
  addresses for the new CDN profiles. New names avoid retired-policy collisions.
- Activation still requires explicit approval for Marzban's core-update operation,
  which restarts Xray and can briefly disconnect current users. The Marzban container
  and Docker daemon do not need restarting.
- The owner selected `test1` for the initial pilot; no other Keyholder customer
  policy should change. The original test1 URL and five selections must survive.

Prepare a new locally built backend image, a consistent Keyholder/Marzban backup,
and fresh gateway/config/host-settings snapshots before activation. Recheck source
hashes to avoid applying a stale candidate. Use Marzban's authenticated core-config
API rather than editing the active file behind its cached state. Its installed
implementation validates, writes the file, includes database users, restarts the
core and refreshes host templates. Its hosts API updates only the named new tags.
Adding VLESS inbounds can make them available to existing Marzban VLESS users by
its exclusion-list semantics; Keyholder still delivers them only to opted-in
customers. Do not alter users' quotas, passwords, expiry or exclusions incidentally.

Activation order: preserve snapshots; deploy the tested backward-compatible API
image; apply Marzban candidate and only the two new titan host templates; load
Nginx routes with a graceful reload; add the two families only to test1's current
policy; validate both formats, old token hash and all seven actual HTTPS paths.
Existing customer identities, mappings and tokens must compare unchanged.

Rollback: restore test1's prior selection, restore the gateway file in place and
reload after syntax validation; restore the original core through the same API
(which again briefly reconnects users). Restore only host rows belonging to the
new tags if necessary; never overwrite the live user database merely to remove
these additions. The previous API image remains compatible with original policies.
No migration is needed. Both rollout and rollback leave customer URLs intact.

After origin/Cloudflare checks, the owner should refresh test1's existing
subscription and try WS/XHTTP on MCI, Irancell and AUT. Record app/core version,
success/failure and approximate latency. This is a short acceptance test, not a
request for prolonged ISP troubleshooting. Expand only after that result.
