# Domestic entry

The domestic host terminates REALITY entries managed by the foreign Marzban panel.
Iranian public destinations exit locally; other destinations use an authenticated
SOCKS exit over a Noise-encrypted Rathole reverse tunnel. Quota remains Marzban's
ordinary per-user byte count. ISP domestic billing discounts must be verified separately.

An optional FRP backhaul uses mutual TLS on domestic TCP 443, with a source-restricted
SNI route to a loopback-only listener. Disable FRP TCP multiplexing so packet loss
on one connection does not stall unrelated TCP connections. Keep certificate
verification enabled and restrict exported ports to the required loopback endpoints.
Templates are in `deploy/domestic/frp/`; pin the binary and verify its release digest.

Keep customer data paths separate when comparing tunnels. The original domestic
entries can use Rathole directly; dedicated OWNER pilot entries can select FRP or
an Xray REALITY forward connector. Set a distinct authenticated loopback SOCKS
outbound per path. Resolve destinations with `IPOnDemand` before the Iranian IP
rule and the per-entry foreign fallback; an unconditional rule with `IPIfNonMatch`
would prevent DNS classification. Private destinations remain blocked.

The forward connector initiates from domestic to foreign, unlike the reverse
connectors. Its server uses REALITY TCP Vision and forwards to the existing foreign
SOCKS exit. The domestic client exposes authenticated loopback port 19987. It can
use an IPv6 underlay while customers enter over IPv4. Restrict the foreign listener
to the domestic source address. Config builders and hardened units are in
`scripts/forward_config.py` and `deploy/domestic/forward/`.

Only the shared DNS resolver needs the checked loopback endpoint when customer
paths are pinned. HAProxy external checks run the root-owned `backhaul_probe.py`
as its unprivileged service user, with credentials from root-owned
`/etc/keyholder-backhaul/probe.json` (root:haproxy 0640). The probe verifies real TLS
through each path, uses a second target if the first fails, and sends credentials
through stdin. Enable `external-check` and `insecure-fork-wanted` in HAProxy global;
never grant the probe root execution. Checks run every 10 seconds, requiring two
failures/recoveries. A local SOCKS greeting alone cannot validate a forward client.

The optional guard restarts a running Rathole listener only after three failed
minute checks, another path healthy and the panel lease valid, with a 30-minute
cooldown. Monitoring reports path failure and loss of redundancy. Backups and
optional Ansible restore tasks include both connector types, credentials and units;
review peer IPv6 addresses, source pinning and firewall rules on migration.

Enable XUDP on the internal SOCKS outbound (`mux.enabled: true`, `concurrency: -1`,
`xudpConcurrency: 8`). This carries application UDP inside the existing TCP tunnel;
ordinary TCP multiplexing stays disabled. It does not open public UDP ports.

Keep databases, subscription-token keys and bots on the foreign host. Stock Marzban
Node receives the full shared core before filtering `INBOUNDS`; this exposes its keys
to the domestic host. Use `tcp`, rather than its `raw` alias, for compatibility with
older Marzban live Vision account updates.

Use trusted DNS for split routing: ISP DNS may resolve filtered foreign names to
private filtering addresses. The shared core sends tagged DNS-over-HTTPS through
the authenticated SOCKS exit. Gate reaches the resolver through the checked backhauls; the foreign
host has a matching loopback SOCKS listener on 19980. Its tunnel target remains
19981. No public DNS listener is needed. Set matching REALITY private/public keys
explicitly and test the exported subscription, not just a hand-built client.

The subscription hostname can share domestic port 443 with REALITY. HAProxy routes
its TLS SNI through the tunnel to a subscription-only foreign Nginx listener. Use a
publicly trusted certificate; a Cloudflare Origin CA certificate is insufficient
for direct downloads. URLs, tokens and account IDs remain unchanged.

Keep TCP Vision as the primary entry. XHTTP `stream-one` and gRPC REALITY can share
443 using distinct validated target SNIs and their own loopback listeners. Add each
tag to the node's comma-separated `INBOUNDS` and the same domestic routing rules.
Preserve the subscription SNI route and the TCP default backend. Test the actual
exported profile before enabling it for users. The foreign CDN origin stays
independent so a domestic node failure does not remove that recovery path.

REALITY supports TCP/RAW, XHTTP and gRPC, not HTTPUpgrade. Check targets with the
installed `xray tls ping HOST`; validate TLS 1.3, HTTP/2 when required, and actual
authenticated browsing. A domestic SNI is not a guarantee against filtering.
Changing a target/SNI may require customers to refresh their existing subscription.

An optional fragmentation pilot is controlled by `KEYHOLDER_FRAGMENTATION_ACCOUNTS`
(backend/username identities) and `KEYHOLDER_FRAGMENTATION_KINDS`. It appends `FRAG`
variants of selected VLESS profiles, preserving originals. REALITY
uses TCP-stream slicing to preserve SNI routing; TLS uses ClientHello record splitting.
Both remain encrypted. URI clients must import `fm`; Xray JSON includes `finalmask`.
These presets avoid empty TLS records and `unsafe` fingerprints. Test on the actual
ISP before broadening access; fragmentation is not a reachability guarantee.

For dual-stack delivery, use the same hostname with A and AAAA records, bind
HAProxy on both families (`bind [::]:443 v6only` in addition to IPv4), and allow
TCP 443 in the IPv6 firewall. Test forced IPv4 and IPv6 before publishing AAAA.
Address choice/fallback is client-dependent. Public UDP need not be opened.

```sh
keyholder tls configure sub.example.org --email admin@example.org
keyholder tls status
keyholder tls issue  # retry issuance or renewal
keyholder system metrics
keyholder monitor status
```

The configure command prompts privately for a DNS token with Cloudflare Zone Read
and DNS Edit on that zone. The foreign host stores it privately and renews using
lego DNS-01. No DNS cutover is performed by these commands.

The domestic guard closes its customer gateway after five minutes without a
successful authenticated panel heartbeat (checked every 15 seconds). Heartbeat
recovery reopens it. Monitoring stays centralized through a source-restricted,
pinned SSH key supporting only status and a fixed recovery archive. The ordinary
encrypted recovery backup fetches that archive before capturing the foreign host.
Never replay captured firewall rules onto a new host without reviewing peer IPs.

Optional probe argument `--domestic-prefix 'IR | '` adds domestic/filtered-foreign
and UDP DNS canaries for matching profile names. Missing matching profiles fail monitoring;
two failed runs alert through the existing deduplicated proxy rule. These are
server-side checks, not a guarantee of reachability from every customer network.

Templates and units are in `deploy/domestic/`; routing construction, lease checking
and telemetry are small standard-library helpers under `scripts/`. The existing
foreign profiles remain independent emergency alternatives. Neither the relay nor
a reverse tunnel guarantees service during a complete international shutdown.

## Restore a replacement entry

The normal backup includes `nodes/domestic.tar`: exact node source, Xray assets,
Rathole binary, configuration, certificates and pinned dependency wheels. Virtual
environments and build caches are excluded. Restore the archive privately to an empty Ubuntu 22.04 amd64
host; never put it in Git or copy it to the laptop.

Copy `deploy/ansible/inventory/domestic.example.yml` to a private inventory, review
the target/security flags, then run from the project root:

```sh
.private/ansible-venv/bin/ansible-playbook -i .private/domestic-inventory.yml \
  deploy/ansible/playbooks/domestic.yml --ask-become-pass
```

Install the Ansible environment with the existing `deploy/ansible/recover` workflow
if it is missing. The domestic playbook restores application files and installs
pinned Python dependencies from captured wheels; it does not replay SSH/firewall rules or change DNS.
Activation requires the old node stopped and peer addresses reviewed. Adjust the
foreign tunnel connector, Marzban node address, firewall source IP and monitoring
SSH pin before cutover. For the restricted observer, set `domestic_console_ready`,
`domestic_foreign_ipv4` and `domestic_observer_public_key` in the private inventory,
then run `playbooks/domestic-observer.yml` with the same Ansible command. Read only
the PUBLIC key from `/etc/keyholder/domestic-monitor.key.pub` on the foreign host.
The observer playbook adds its own SSH allowance and verifies a fresh admin login;
it does not replace existing login rules. Verify the new gate host key through
authenticated SSH before updating the foreign pin. Keep the old foreign entry as
rollback until real traffic passes.

If prepared with activation disabled, set the three activation/handover flags only
after peer review, then run `playbooks/domestic-activate.yml` with the same command.
Do not rerun the empty-target restore over the staged service. Activation waits for
the heartbeat guard to open port 443; DNS cutover still follows real traffic tests.

Use one naming convention in the panel: `Route | Protocol | Transport`, with
optional `IPv6` and `ECH FALLBACK` suffixes. Include XHTTP mode when it distinguishes
two profiles. Keyholder preserves panel names and appends the ECH suffix itself;
names do not control credentials, accounting or subscription identity.
