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
- Both transports passed isolated Xray → Nginx → Xray → verified HTTPS tests
  with synthetic credentials; temporary processes were removed. This does not
  establish ISP or Cloudflare delivery.
- All 89 local tests pass; renderer/API tests retain old fixtures/defaults and reject literal-origin
  addresses for the new CDN profiles. New names avoid retired-policy collisions.
- Activation still requires explicit approval for Marzban's core-update operation,
  which restarts Xray and can briefly disconnect current users. The Marzban container
  and Docker daemon do not need restarting.
- The owner selected `test1` for the initial pilot; no other Keyholder customer
  policy should change. If test1 has a Keyholder mapping, preserve its URL and prior selections. It is
  an active Marzban account with all five existing issued families, but the initial
  Keyholder lookup found no unambiguous mapping. Recheck before attaching; issue
  one new pilot Keyholder URL only if no mapping exists. No Marzban user creation
  or quota/expiry change is needed.

The code-only image was built locally from the verified deployed base using
`deploy/Dockerfile.code-update`; both dependency manifests exactly matched. The
base image ID is `9d90728e7cebccebffe0bec1027bb22102e89f58497fc9e4311b1cd07978726a`
and candidate image ID is `dcd10c0e0beca17eec1bef25e4e81d5f124324ed4e4b3b7feddc5b78adb6618e`.
Image import/renderer checks passed offline. No dependencies were installed on VPS.

Prepare a consistent Keyholder/Marzban backup,
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
