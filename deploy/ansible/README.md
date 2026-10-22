# Deploy and recover

Run on the **laptop**, from the repository root. Targets are empty Ubuntu 22.04
amd64 servers. This restores an existing captured deployment; public source alone
cannot restore customer state. No OS upgrade or automatic public DNS change runs.

```sh
./deploy/ansible/run host .private/host.yml
./deploy/ansible/run foreign .private/foreign.yml
python3 scripts/transfer_node.py replacement-foreign replacement-gate
./deploy/ansible/run domestic .private/domestic.yml
./deploy/ansible/run observer .private/domestic.yml
./deploy/ansible/run activate-domestic .private/domestic.yml
```

Copy the matching templates from `inventory/` privately. Prepare each fresh host
with `host` first; verify its initial SSH fingerprint through its console. Set the
console/empty-host/rule-review flags only when true. Review TCP service ports and
source networks. Host preparation adds `khadmin`, its public key and passwordless
sudo, pins the host identity for port 2222, checks a fresh key/sudo connection,
then closes the old SSH port and disables password/root login. A ten-minute rollback
is armed until the final fresh connection succeeds. Do not close the console.
The command refuses existing application data, containers, firewall rules or an
unfinished host checkpoint. It does not reset an existing server's security.
For a Cloudflare-only foreign origin, set `host_cloudflare_origin_ports: [80, 443, 2053]`;
the play fetches the official IPv4/IPv6 networks and validates them before activation.
Do not also allow those ports from `any`. Keep this setting empty on the domestic host.

After host preparation, update that inventory's SSH user/port to `khadmin`/2222.
Use the same private key. `foreign` installs missing prerequisites, pauses for B2
credentials **on the target**, downloads/verifies the encrypted bundle and restores
exact images, databases and configuration. Rehearsal mode isolates services and
checks reboot persistence; bots/timers remain off. `recover INVENTORY` remains a
compatibility alias. `foreign INVENTORY --finish` resumes completed VM restores;
`--check` checks a running restored VM without reboot or configuration changes.
Do not rerun full restore over partially populated application data.

For a real replacement, review the local address map and peer address map before
activation. Endpoint mapping updates tunnel endpoints, forward source pins,
domestic HAProxy peer ACLs and literal panel-node addresses, preserving keys and
users. It does not assign IPs, rewrite DNS names, change host networking or trust
new monitoring host keys automatically. Foreign production activation requires
the old panel/writers stopped, reviewed security/peers and assigned replacement IPs.
Keep jobs disabled until customer traffic and cutover are verified.

Restore the foreign host first. Add verified SSH aliases for both replacements.
`transfer_node.py` streams its captured domestic archive directly to the domestic
host, verifies SHA-256 and refuses overwrite; no laptop secret file or B2 key on
the domestic server is needed. `domestic` restores the node and all captured
backhauls from that archive, with activation disabled initially. Install the
restricted observer using the foreign observer **public** key, and update the
foreign SSH host pin using the new domestic host's verified public key. Stop the
old node identity before `activate-domestic`; its guard waits for an authenticated
panel heartbeat before opening customer 443. Preserve the independent foreign path.

See [the recovery procedure](../../docs/disaster-recovery.md) for backup configuration,
cutover and acceptance checks. Neither a fresh-host bootstrap nor a complete domestic
restore has been accepted on a new VM yet; local tests and syntax checks do not
replace that rehearsal. The existing foreign restore/reboot rehearsal passed earlier.
