# Contributing

## Development environment

Use Python 3.12 and create the virtual environment described in the README.
Install optional formatting tools with `python -m pip install -r requirements-dev.txt`.
Keep real settings in the ignored root `.env`; use `.env.example` as a reference.

## Common commands

Run these with the project virtual environment active:

| Command | Purpose |
| --- | --- |
| `python scripts/dev.py serve` | Start the local development server. |
| `python scripts/dev.py check` | Run all isolated release checks. |
| `python scripts/dev.py lint` | Check Python and template formatting. |
| `python scripts/dev.py format` | Format Python and HTML templates. |
| `python scripts/dev.py package` | Check the app and build a source release. |

The scripts resolve the repository path themselves, so the command runner can
also be called by absolute path. Existing commands such as
`python scripts/check_release.py` remain supported.

## Where changes belong

- HTTP request handling: `app/routes/`.
- Integration clients, parsing, and nutrition calculations: `app/services/`.
- Account, request, and configuration rules: `app/core/`.
- Models, sessions, and recorded schema changes: `app/db/`.
- Shared form validation: `app/forms/`.
- Date, unit, and pagination helpers: `app/utils/`.
- Page markup and browser assets: `app/templates/` and `app/static/`.
- Meaningful regression checks: `tests/`.
- Reusable operational commands: `scripts/`; systemd and shell templates: `deploy/`.

See [architecture](docs/ARCHITECTURE.md) for request and data flow.

## Adding a feature

1. Add focused service logic and a small route handler.
2. Validate input, check account ownership, and preserve the standard CSRF rules.
3. Add or update the page and navigation when appropriate.
4. For storage changes, add an idempotent migration and test an existing schema.
5. Check meaningful behavior, including invalid data and cross-account requests.
6. Run the isolated checks, lint, and review `git diff --check`.
7. Commit related source changes with a descriptive message.

## Tests and sensitive data

Use `scripts/dev.py check` or `scripts/check_release.py` for the complete test
environment. These commands provide fictional settings and disposable databases.
The MySQL and encrypted-backup checks are separate operational checks; review
their requirements in [deployment](docs/DEPLOYMENT.md) before running them.

Never add actual health exports, tokens, keys, or database dumps to test fixtures.
The detailed personal project guide belongs in `docs/private/`, which is excluded
from Git and release archives. Public documentation should explain the software
without personal account information or session-specific setup notes.

## Release compatibility

`main.py` is a small compatibility entry point for `uvicorn main:app`.
`migrations.py` supports the existing `python -m migrations` command; the canonical
module is `python -m app.db.migrations`. The root `.env` location and the scripts
used by systemd are unchanged. Internal Python imports now use `app.*` paths.

Do not copy files over an active release. Build and verify a separate release,
then use the deployment process appropriate for the service's installation path.
