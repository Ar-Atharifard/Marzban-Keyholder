# Titan transport expansion: activated test1 pilot

The original five live inbounds remain unchanged. The activated release adds two VLESS
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

## Activation and validation record

- Candidate files are private in `/opt/braavos-panel/transport-expansion`.
- The installed Marzban parser, host-settings schema and Xray startup-config test
  accepted the candidate with all five existing inbounds preserved.
- The full Nginx candidate passed syntax checks. Paths are generated only on VPS.
- Both transports passed isolated Xray → Nginx → Xray → verified HTTPS tests
  with synthetic credentials; temporary processes were removed. This does not
  establish ISP or Cloudflare delivery.
- All 89 local tests pass; renderer/API tests retain old fixtures/defaults and reject literal-origin
  addresses for the new CDN profiles. New names avoid retired-policy collisions.
- The owner approved activation. Only Keyholder was replaced; Marzban applied
  the new core configuration through its own API, restarting Xray once. The
  gateway was gracefully reloaded. The Marzban container and Docker daemon were
  not restarted.
- The owner selected both existing active Keyholder subscriptions attached to
  Marzban test1. The initial ambiguous username lookup was not proof of absence:
  inspection found two mappings, and the owner explicitly selected both. No new
  customer or URL was created and no token rotated. Only their policies gained
  the two new families. All customer IDs, statuses, token hashes and mappings
  compare unchanged against the snapshot; all other policies compare unchanged.
- A fresh guarded database-clone rehearsal verified both subscription formats,
  accepted all seven configs in installed Xray, and completed actual verified
  HTTPS requests with nonempty response bodies through each profile. Both new
  CDN transports passed through Cloudflare. Temporary containers were removed.
- The public panel HTML/assets and real authentication passed through Cloudflare.
  The owner confirmed the panel loaded. Workstation direct IPv4/IPv6 checks failed
  while VPS browser-style checks passed, so network-specific reachability is not
  guaranteed. Cloudflare BIC still rejects Python-style panel requests; this does
  not affect the validated browser login or Keyholder delivery.

The code-only image was built locally from the verified deployed base using
`deploy/Dockerfile.code-update`; both dependency manifests exactly matched. The
base image ID is `9d90728e7cebccebffe0bec1027bb22102e89f58497fc9e4311b1cd07978726a`
and candidate image ID is `5bde9df5a0f81e43c33914b3d57ff274f6fb06993ff3690caace9f19879c143c`.
Image import/renderer checks passed offline. The candidate API also passed a
private consistent production-database-clone rehearsal: identities/mappings and
all five existing upstream profiles remained valid in both formats. Compose
comparison confirmed that only the image changes; volume, environment, networking
and hardening match the deployed service. Marzban control API read prerequisites
passed. The image is deployed and healthy. No dependencies were installed on VPS.

Use `KEYHOLDER_ENV_FILE=/srv/keyholder/.env` explicitly with Compose; supplying
`--env-file` alone does not resolve the service `env_file` selector. Keep all
configuration output captured privately rather than printing resolved credentials.

Fresh consistent Keyholder/Marzban snapshots and original gateway/core/host
settings are retained root-only under `/var/backups/keyholder-pilot/<activation-time>`.
For a future rollout, take fresh snapshots and recheck source
hashes to avoid applying a stale candidate. Use Marzban's authenticated core-config
API rather than editing the active file behind its cached state. Its installed
implementation validates, writes the file, includes database users, restarts the
core and refreshes host templates. Its hosts API updates only the named new tags.
Adding VLESS inbounds can make them available to existing Marzban VLESS users by
its exclusion-list semantics; Keyholder still delivers them only to opted-in
customers. Do not alter users' quotas, passwords, expiry or exclusions incidentally.

The completed activation followed this order: preserve snapshots; deploy the tested
backward-compatible API image; apply Marzban candidate and only the two new titan host templates; load
Nginx routes with a graceful reload; add the two families only to both test1's current
policies; validate both formats, old token hash and all seven actual HTTPS paths.
Existing customer identities, mappings and tokens must compare unchanged.

Rollback: restore the two policies from `pilot-before-both.json` in the private
activation backup, restore the gateway file in place and
reload after syntax validation; restore the original core through the same API
(which again briefly reconnects users). Restore only host rows belonging to the
new tags if necessary; never overwrite the live user database merely to remove
these additions. The previous API image remains compatible with original policies.
No migration is needed. Both rollout and rollback leave customer URLs intact.

The owner should now refresh both existing test1 subscriptions and try WS/XHTTP on
MCI, Irancell and AUT. Record app/core version,
success/failure and approximate latency. This is a short acceptance test, not a
request for prolonged ISP troubleshooting. Expand only after that result.
