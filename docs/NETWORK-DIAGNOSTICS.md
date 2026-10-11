# Connection and subscription checks — October 12, 2026

## Subscription update delay

The owner uses v2rayN 7.25.4's update **without proxy**, which eventually succeeds
but takes roughly 5–10 seconds. Backend request logs usually show 22–40 ms;
three measured server-loopback downloads took 145/91/100 ms for 7,320 bytes.
Direct workstation probes had fast DNS/TCP but stalled before an HTTP response.
A matching .NET SocketsHttpHandler probe reached its ten-second deadline twice.
This establishes a slow/unreliable network delivery path, not a five-second
subscription renderer. It does not prove the precise ISP rule or explain every
successful client attempt without the client's own timing logs.

v2rayN has a five-second direct connection deadline and ten-second direct fetch
deadline, plus a fallback downloader. These deadlines explain why a stalled
network path can appear as a 5–10-second update. Increasing Keyholder workers or
caching user selections would not fix this path and could make panel edits stale.

The broad `.ir` destination block also prevented Keyholder downloads through the
proxy. The owner approved an exact-host exception for
`full:keyholder.javatechpack.ir`, routed DIRECT before Iranian destination rules.
The private-IP rule and all Iranian domain/IP rules are retained. Both tested
streaming CDN paths now deliver `/s/invalid` as the expected HTTP 404 in about
one second. No real token was sent through public diagnostic probes.

Direct download remains dependent on ISP reachability and the downloader's TLS
support; ECH inside a proxy profile does not add ECH to the client's downloader.
The server exception enables the existing **update via proxy** option when a
working profile is connected. The customer URL is unchanged.

Routing recovery: `/var/lib/marzban/keyholder-routing-recovery-20261011T223835Z`.
Pre-change backup: `/var/backups/keyholder/20261011T223740.858352Z`.
Restore the previous core through Marzban API after checking subsequent changes;
this briefly restarts Xray. Never overwrite a newer core blindly.

## REALITY investigation

Both original IPv4 REALITY profiles pass authenticated, certificate-verified HTTPS
from the VPS (TCP 0.129 s, XHTTP 0.100 s). Their keypairs match, and no client
version/time restriction explains the failure. On current Irancell IPv4, TCP
connects to 8443/9443 in about 0.11 s, but authenticated traffic times out.

The Microsoft SNI also stalls in an ordinary TLS probe. On the same ports,
NLnet SNI gets a TLS response immediately, though its certificate does not match
the unchanged Microsoft fallback target. This indicates handshake-sensitive
filtering, not a closed TCP port. It does not prove that Microsoft is the only
cause: isolated authenticated NLnet target tests also fail on this network while
passing from the VPS. Firefox/Safari/Chrome fingerprints and bounded valid TCP
fragmentation did not recover the two direct paths.

The owner approved testing shared port 443 with Nginx SNI forwarding, retaining
existing ports and HTTPS services. Port 443 tests passed existing HTTPS routing checks but all five authenticated
candidates timed out from Irancell: Microsoft TCP, NLnet TCP, NLnet XHTTP, RIPE
TCP and SURF TCP. The gateway was restored and temporary listeners removed.
Certificate-verified origin checks returned panel HTTP 200 and invalid-token
HTTP 404. Ordinary Python requests from the VPS see existing Cloudflare 403 on
panel/apex, also observed before the experiment; this is not a gateway regression.
The experiment preserved source IPs using a loopback-only PROXY-protocol relay.
No shared-port configuration or failed target was retained. Synthetic
listeners/accounts are removed after each diagnostic. No credential rotation,
quota change, production database migration or customer URL change is required.

Primary sources:
- [v2rayN timeout constants](https://raw.githubusercontent.com/2dust/v2rayN/7.25.4/v2rayN/ServiceLib/Global.cs)
- [v2rayN downloader](https://raw.githubusercontent.com/2dust/v2rayN/7.25.4/v2rayN/ServiceLib/Services/DownloadService.cs)
- [Xray REALITY](https://xtls.github.io/en/config/transports/reality.html)
- [Nginx SNI forwarding](https://nginx.org/en/docs/stream/ngx_stream_ssl_preread_module.html)

The nonzero TLS-record fragmentation test also failed, in addition to raw TCP
segmentation. These results do not establish a reliable server-only fix for this
network's direct REALITY path. Keep existing direct profiles for other networks
and use verified ECH CDN profiles where this path is filtered. Changing the origin
address/provider would require a separate decision and still would not guarantee
reachability. Exact censorship classification remains an inference, not proven
knowledge of ISP rules.

An isolated no-SNI REALITY candidate also timed out for TCP and XHTTP; its
listeners were removed. None of the tested direct candidates is advertised as a
working fix. Original REALITY configurations remain unchanged for other networks.
