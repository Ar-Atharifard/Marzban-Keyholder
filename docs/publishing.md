# Publishing a clean release

Public source belongs in Git. Personal notes, deployed configuration, diagnostics
and customer material belong in ignored `.private/`, `.audit/`, `.env` and runtime
storage. Docker and source/wheel distributions exclude private folders.

**Ignoring or deleting a file does not remove it from Git history.** If the
existing development repository contains private deployment history, do not push
its branches/tags to a public remote. Keep that repository private for provenance.
Publish a reviewed source export with fresh Git history instead. No history rewrite
or force push is needed, and production repositories remain untouched.

```bash
uv run python scripts/export_source.py --output /private/path/keyholder-source.tar.gz
```

The exporter refuses overwrite, sensitive tracked runtime filenames and symlinks,
and excludes private directories and Git metadata. It is not a complete secret
scanner. Before publication, scan both original history and exported source using
Gitleaks with redacted output; review findings privately. A checksum-verified
Gitleaks scan is also part of public CI. Optional `--private-patterns` accepts a
private JSON list of deployment strings that must not enter the release.

Extract the archive into a new directory, verify its contents and all tests, then
initialize a **new** repository there. Review owner/repository name and visibility
before the first push. Do not attach the private development remote or old branches.
Public Git author metadata is itself public; select the intended name/email.

Before release, check license/copyright, README links, clean installation, migrations,
CLI installation, wheel/sdist contents, compatibility tests and secret scanning.
Enable GitHub private vulnerability reporting, secret scanning and push protection.
CI should have read-only permissions and must not contain production deployment
secrets. Publishing source is separate from deploying code or publishing packages.
