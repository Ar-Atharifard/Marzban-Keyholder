# Security

Do not put secrets, customer URLs or exploitable details in a public issue.
Use the repository's private vulnerability-reporting feature when enabled. If it
is unavailable, ask the maintainer for a private reporting channel using an issue
containing no sensitive details. Public-release maintainers should enable private
vulnerability reporting, secret scanning and push protection before publication.

Keep admin routes private, use HTTPS across untrusted networks, and retain TLS
verification. Store the database and vault key securely and back them up together.
Subscription paths are bearer credentials: disable access/error path logging,
caching and browser challenges for them. Rotate compromised tokens explicitly.

The latest maintained release receives security fixes; support for historical
branches is not promised. The service is designed for one worker and trusted
server-owned upstream configuration. An HTTP source must enforce account validity;
it is not a replacement for a panel's quota/expiry checks.
