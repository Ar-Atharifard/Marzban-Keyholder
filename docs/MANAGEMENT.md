# Daily management

Open `https://edge.javatechpack.ir/dashboard/` and sign in with the existing Marzban
administrator account. The owner confirmed the dashboard loads. Marzban's login
is the public panel protection; no Cloudflare Access or secret-path protection is
claimed. `keyholder panel` provides an SSH tunnel if public access fails.

Nginx serves the recovered Java-learning HTML homepage at the configured domain
and subdomain roots. Panel routes, subscriptions and protocol routes retain their
own routing. The homepage is static and adds no application service.

## New customer

1. Create the user in Marzban with deliberate quota, expiry and inbound selection,
   or use `keyholder user-create alice --quota-gb 20 --days 30 --protocols vless vmess trojan shadowsocks`.
2. For a panel-created user, run `keyholder create alice`. This atomically attaches
   or retrieves its canonical Keyholder identity.
3. Share the returned subscription once. Retrieve it any time with `keyholder link alice`.
4. Edit selected inbounds, expiry or quota in Marzban (or through the CLI). The same
   subscription reflects supported configurations on the next refresh.

Use `keyholder doctor`, `users`, `list`, `show`, `check`, `sync`, `user-update`,
`user-inbounds`, `disable`, `enable`, `remap` and `backup` as documented in the
[CLI guide](../scripts/admin/README.md). `list --history` includes revoked records;
those are historical identities, not additional live Marzban users.

The two current panel users each have one canonical subscription. The owner
approved rotating their former URLs and retiring duplicate subscriptions. Future
routine changes must preserve the replacement URLs. Explicit rotation/revocation
is the only local invalidation operation; account expiry/quota affects delivery,
not token lifetime. The database stores encrypted recoverable tokens plus hashes.

## Remaining operational decisions

| Priority | Improvement | Decision needed |
|---|---|---|
| Next | Encrypted scheduled off-host backups and restore drills | Destination, retention, acceptable data loss/downtime |
| Next | Delivery alerts beyond DB health | Alert destination and probe interval |
| Next | Private canonical Git remote and CI | Host, repository access and deployment process |
| Later | Per-operator identity and sanitized mutation audit | Additional administrator requirements |
| Later | Small authenticated customer-management UI | Phone/browser workflow and access model |
| Later | Billing/plans/additional nodes | Business requirements and budget |

Marzban owns plans, limits, credentials and inbounds. Keyholder owns public identity,
mapping and safe rendering. Avoid duplicating panel quota/expiry into Keyholder.
