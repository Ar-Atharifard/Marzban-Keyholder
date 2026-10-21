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

## Personal DNSTT

DNSTT is an optional owner recovery tool, outside customer subscriptions,
Marzban accounting and production alerts. It needs a separate client helper:

```text
Xray client → loopback helper → recursive DNS → DNSTT → owner-only loopback Xray
```

The owner Xray uses independent credentials; customer credentials must not work
there. Bind both local TCP endpoints to loopback. Never put an unauthenticated
SOCKS server behind the public DNS tunnel. DNSTT uses Noise encryption; the inner
REALITY connection provides authentication and encrypted proxy transport.

Build pinned upstream `www.bamsoftware.com/git/dnstt.git@v1.20260501.0` with Go 1.26+,
apply `deploy/dnstt/dependency-updates.patch`, test and scan dependencies, and record
binary hashes. The sample units are in `deploy/systemd/`. Set the DNSTT upstream
to the independent owner listener, not a Marzban inbound. DNS-only A/AAAA and NS
records expose the authoritative address; normal Cloudflare proxying cannot hide it.
Review any UDP 53 allowance using the firewall procedure in [Operations](operations.md).

Store root-owned 0600 owner export metadata using
`deploy/dnstt-client.example.json` at `/etc/keyholder/dnstt-personal-client.json`:

```sh
keyholder personal dnstt --save-link ./owner-dnstt.json
dnstt-client -doh https://RESOLVER/dns-query -pubkey-file server.pub t.example.com 127.0.0.1:7000
```

Import the exported `profile_uri`; run the helper separately. This is not one-click
customer delivery. Standard Xray clients cannot start DNSTT from a subscription URI.
Keep keys, owner config and binaries in encrypted recovery backups; personal service
activation after recovery is opt-in. Test browsing, not only idle delay. Throughput
and availability depend on the resolver. [DNSTT protocol](https://www.bamsoftware.com/software/dnstt/protocol.html).
