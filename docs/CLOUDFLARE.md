# Cloudflare settings for the Marzban-only gateway

The zone is `javatechpack.ir`. Never share real subscription URLs, tokens or
credentials when inspecting events or reporting settings. Use `/s/invalid` for
public routing checks; expected origin response is Keyholder JSON with HTTP 404.

## DNS and origin routing

Keep the existing proxied A records for Keyholder, titan and sealord pointing to
Braavos. Keyholder uses normal HTTPS origin port 443. Existing titan/sealord
Origin Rules rewrite the origin port to 2053; retain those rules during this
transition. Nginx supports both ports, and existing gRPC location semantics remain
unchanged. Keep Network → gRPC enabled. Do not change customer-facing URLs.

## Origin certificate verification

The gateway has an independent Cloudflare Origin CA certificate covering
`*.javatechpack.ir` and the apex, expiring in October 2041. It is valid for
Cloudflare-to-origin verification; it is not a publicly trusted certificate for
direct clients. Its key and certificate live outside the Hiddify installation.

The reported zone mode is Full. To tighten only Keyholder:

1. Open the zone → Rules → Configuration Rules → Create rule.
2. Name it `Keyholder origin TLS`.
3. Match Hostname equals `keyholder.javatechpack.ir` (expression below).
4. Set SSL encryption mode to Full (strict), then deploy.
5. Retest public `/s/invalid`. A 525/526 response requires investigating origin
   SNI, routing or certificate verification rather than weakening TLS permanently.

```text
http.host eq "keyholder.javatechpack.ir"
```

Keep the existing titan/sealord Configuration Rules. Their precise SSL modes
should be recorded before changing them. Do not silently change the entire
zone's mode, which might affect other domains.

Reference: [Full (strict)](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/).

## Automated subscription clients

The owner disabled Bot Fight Mode after enabling Keyholder Full (strict). No
custom security rules were reported. Bot Fight Mode can
challenge nonbrowser clients and cannot be bypassed by a path-specific custom
Skip rule. The owner must choose between disabling this zone-wide feature and
designing a separate direct-TLS/DNS arrangement for Keyholder. Disabling it does
not mean disabling all Cloudflare security. Do not replace it with a global Allow
rule or silently disable unrelated protections.

Dashboard: Security → Settings → filter Bot traffic → Bot Fight Mode. If the
decision is to disable it, turn it off and retest with a normal subscription
client as well as a browser. Super Bot Fight Mode has different skip behavior;
do not confuse these two products.

A Python-urllib probe still receives 403 while v2rayNG and browser probes reach
Keyholder with the expected 404. Inspect Security → Analytics → Events for hostname Keyholder and
path `/s/invalid`, recording only the action and service/rule name. Check Browser
Integrity Check and Security Level settings as additional possible causes; do
not attribute a 403 to a specific service without event evidence.

Reference: [Bot Fight Mode limitation](https://developers.cloudflare.com/bots/get-started/bot-fight-mode/).

## Cache bypass

The owner reported no Cache Rules. Keyholder and Nginx send `no-store`, and
initial public client checks showed Cloudflare `DYNAMIC`. For an explicit
subscription safeguard, open Caching → Cache Rules → Create rule, match this
expression, and choose Cache eligibility → Bypass cache:

```text
(http.host eq "keyholder.javatechpack.ir" and starts_with(http.request.uri.path, "/s/"))
```

Do not cache customer subscription responses or redirect tokens to another URL.
Future cache rules must not override this bypass. Never enter a real token in a
rule expression. Confirm delivery is not a cache HIT after any rule change.

Reference: [Create a Cache Rule](https://developers.cloudflare.com/cache/how-to/cache-rules/create-dashboard/).

## Remaining customer validation

After settings are confirmed, the owner should refresh an existing Keyholder
link in their actual client and report success or the error without sending the
link. On-server tests exercise real mapped Marzban configurations and installed
Xray; they do not establish compatibility with every customer client version.
