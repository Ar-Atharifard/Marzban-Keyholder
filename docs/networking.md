# Subscription delivery and DNSTT

Test subscription downloads separately from proxy connectivity. Preserve existing
`/s/{token}` URLs and customer identities.

## Diagnose delivery

| Failure | Check |
|---|---|
| `ECONNREFUSED 127.0.0.1:10808` | Downloader's local proxy listener is running on that port |
| Direct timeout | DNS, IPv4/IPv6 routes, TLS/SNI/ECH; compare a working proxy |
| HTTP error / HTML | Gateway, browser challenges, upstream status and content type |
| Slow backend | Secret-safe request timings, Marzban latency, health and resource pressure |
| Import error after HTTP 200 | Base64/URI format and client/core transport support |

DNS resolution or a browser loading a decoy does not prove the downloader can
reach HTTPS. Browsers, downloaders and proxy cores have different ECH/TLS support.
Never bypass certificate checks, publish tokens in logs or use plaintext HTTP.

In v2rayNG 2.2.6, **Enable local proxy**, matching **Local proxy port** and disabling
**dynamic local proxy port** temporarily can diagnose a refused listener. Restart
the profile before retrying. The updater tries its local proxy then direct access;
a working VPN indicator alone does not prove the loopback listener exists.
[Versioned source](https://github.com/2dust/v2rayNG/blob/2.2.6/V2rayNG/app/src/main/java/com/v2ray/ang/handler/AngConfigManager.kt).

## Optional Cloudflare Worker

`deploy/cloudflare-subscription/worker.mjs` forwards only GET/HEAD `/s/{token}` to
one fixed HTTPS `UPSTREAM_ORIGIN`. It preserves content and usage metadata, rejects
redirects, strips credentials/cookies and disables caching. No DB or VPS service is
added. Existing links remain valid; alternate hostnames must be distributed separately.
This adds hostname diversity, not independent hosting or guaranteed filter resistance.

1. Run `node --test deploy/cloudflare-subscription/worker.test.mjs`. CI additionally
   runs `runtime.test.mjs` with pinned workerd and a synthetic upstream. Locally set
   `WORKERD_BIN` to run that test. `cache: 'no-store'` conflicts with `cf.cacheTtl`.
2. Deploy via Wrangler using the provided config, or paste the module in the dashboard.
   Set `UPSTREAM_ORIGIN` to your canonical HTTPS origin only, without path/token.
3. Disable invocation logs/traces; dashboard pasting does not apply Wrangler settings.
   Keep the free plan; its account-wide request allowance is finite.
4. Test `/s/invalid` for 404, then a real authorized subscription privately. Check
   content, metadata, revoked-account behavior, direct and proxy modes on target ISPs.
   A browser success or synthetic 404 alone is insufficient.

Do not redirect canonical links or cache bearer responses. Rollback deletes only
the Worker. [Cloudflare limits](https://developers.cloudflare.com/workers/platform/limits/),
[logging](https://developers.cloudflare.com/workers/observability/logs/workers-logs/).

## DNSTT

```text
Xray client → loopback DNSTT helper → recursive DNS → DNSTT server → Marzban REALITY
```

DNSTT encrypts the tunnel with Noise; the inner protocol authenticates customers.
Never expose unauthenticated SOCKS behind it. Marzban retains quota, expiry, status
and destination blocking. For production, use a dedicated loopback-only VLESS
REALITY inbound tagged `VLESS DNSTT`; select it per user in Marzban. Its traffic
shares that user's quota. A disabled host entry keeps it out of ordinary
subscriptions: clients cannot start the required helper from a normal URI.
Its authoritative IP/domain remain discoverable; performance depends on the resolver.

Create DNS-only `ns1.example.com` A and delegated `t.example.com` NS records.
Check authority/recursion, assigned public address and free UDP 53. Bind the specific
public address; preserve systemd-resolved. Cloudflare's HTTP proxy cannot proxy DNS.

Build pinned source `www.bamsoftware.com/git/dnstt.git@v1.20260501.0` with Go 1.26+.
Apply `deploy/dnstt/dependency-updates.patch` (`patch -p1`), run `go test ./...` and
`govulncheck ./...`, then build client/server with
`CGO_ENABLED=0 go build -buildvcs=false -trimpath`. Record versions and hashes.

Install the server at `/usr/local/libexec/keyholder/dnstt-server`, generate keys
on-server using `-privkey-file`/`-pubkey-file`, and protect
`/etc/keyholder/dnstt.key` as root-only 0600. Configure the example environment
and hardened `deploy/systemd/keyholder-dnstt.service` (Ubuntu 22.04 credentials).
Share only the public key. Add only the required UDP 53 allowance using the
[firewall safety procedure](operations.md); no SSH/Docker/Xray restart is required.

Desktop helper (choose a tested resolver; DoH/DoT also exist upstream):

```sh
dnstt-client -udp RESOLVER_IP:53 -pubkey-file server.pub t.example.com 127.0.0.1:7000
# Alternative: replace -udp with -doh https://RESOLVER/dns-query
```

For managed exports, install the root-owned 0600 client metadata file from
`deploy/dnstt-client.example.json` at `/etc/keyholder/dnstt-client.json`. Set its
actual tunnel domain, DNSTT public key, tested DoH endpoint and inbound tag.
`keyholder user dnstt USER --save-link USER-dnstt.json` retrieves the enabled user's
private `profile_uri` plus public helper settings; existing files are never replaced.
Import that URI and run the matching helper separately. Deselecting `VLESS DNSTT`
in Marzban stops new tunnel authentication without affecting other selected inbounds.
Disabled hosts control advertisement, not access; inbound selection controls access.

This is a manual desktop workflow, not one-click customer delivery. Standard
v2rayN does not start the helper; Android DNSTT+SSH apps cannot use this REALITY
backend. Never use administrator SSH credentials. A second VPS does not remove
the client-side helper requirement unless it acts as a separate ordinary proxy entry.

DNS tunnels have limited throughput. Test browsing under load and resolver errors,
not just idle ping; respect resolver backoff.

Validate authenticated browsing, invalid-user rejection and domestic blocking;
compare authority/recursive paths and multiple ISPs. A DNS reply or local listener
is not a passed tunnel test. Start payload 1232; change only after measured size loss.
Avoid testing by switching the workstation's only working connection.

Recovery must preserve keys, binary, environment and unit, with liveness monitoring.
Review bind address and DNS on a new host; restore/activate the unit explicitly.
Rollback stops only DNSTT and removes its additive UDP 53 rule. Existing profiles
and DNS must remain intact. [Upstream protocol](https://www.bamsoftware.com/software/dnstt/protocol.html).
