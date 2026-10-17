# Contributing

Read `docs/development.md` before changing code or contracts.
Use synthetic test data. Never submit customer links, real credentials, databases,
private deployment configuration or personal troubleshooting notes.

Keep changes focused, with meaningful regression tests and updated documentation.
Run pytest, Ruff, mypy and `git diff --check`. Explain behavior, validation and
compatibility in the pull request. Provider adapters need mocked contract tests;
new transports additionally need installed-core and real-network validation.

Do not mix application changes with unreviewed infrastructure deployment. New
services, databases or background jobs require a demonstrated requirement.
Contributions are distributed under the project's MIT license.
