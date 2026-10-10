# Permanent subscription and API compatibility policy

The customer-facing contract is `https://keyholder.javatechpack.ir/s/{token}`.
Retain this hostname, HTTPS, path, token syntax and the Keyholder database through
all panel, backend, image and VPS changes. DNS/domain ownership and database
recovery are part of this contract, not properties source code can guarantee alone.

A customer token is generated independently of their Marzban username, UUID,
password, upstream link or inbound port. Keyholder stores its hash and mapping.
Rename, policy changes and remapping retain the hash; pause/resume retains the URL.
A code update does not regenerate tokens. Moving the same database to another
instance retains access; migrations must preserve identities and hashes.

Only explicit token rotation changes a customer's URL. Revocation permanently
disables delivery; deletion/database loss makes hashes unavailable. Do not do any
of these during normal upgrades. If a URL is lost, its hash cannot reconstruct it;
recover the customer's saved URL or use a deliberately approved rotation.

## Rendering contract

- Plain `/s/{token}` defaults to standard-base64 newline-separated proxy URI lines.
- `format=uri` explicitly selects that format.
- `format=xray` returns an array of Xray client configurations.
- Existing `Keyholder-Xray` User-Agent opt-in remains supported.
- XHTTP-only `extra` removal remains mandatory in URI and Xray output.
- Invalid format values return 422; unavailable/disabled subscriptions retain their
  established error behavior. Responses stay `no-store` and never echo tokens.

Stable links do not mean static configurations: changing policy or Marzban endpoint
can change the downloaded servers. Clients refresh the **same** URL. Keep current
formats compatible; any future incompatible representation needs a new opt-in
format/API version while the old format stays supported. Add protocols deliberately
with client compatibility review, rather than changing existing fields silently.

## Release gates

`tests/contracts/` freezes synthetic examples for both subscription formats and
the current OpenAPI paths/schemas. `tests/test_contracts.py` compares these and
exercises the original URL across rename, policy changes, mapping replacement,
pause/resume, application restart and database backup/relocation. Historical
migration tests separately prove hash/mapping preservation.

Do not regenerate snapshots merely to make a failing test green. Treat failures as
compatibility reviews. New unrelated endpoints/schemas can be added without deleting
or changing the existing frozen operations. Contract tests cannot certify every
client version or prevent unauthorized DNS/deployment/database changes.

Before an infrastructure move: verify a consistent database snapshot/restoration,
retain old and new hosts during validation, preserve domain/path and TLS, check both
formats and actual proxy delivery, then change DNS. Never instruct customers to use
raw Marzban subscription addresses as a replacement for the stable Keyholder URL.

## Remaining guarantees to operationalize

Encrypted off-host backups and recovery drills are essential: backups on the same
VPS do not survive provider/disk loss. Domain renewal/ownership, certificate expiry,
canary delivery and alerting need deliberate operating procedures. Future CI should
make contract tests mandatory; local tests alone do not enforce deployment policy.
