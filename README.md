# Sugar Watch

Sugar Watch is a FastAPI application for recording glucose readings, nutrition,
exercise, medication, mood, and health measurements. Data is stored in MySQL,
and users authenticate with Google OpenID Connect.

## Features

- Google sign-in with optional account restrictions and required production allowlists.
- Health profiles with Imperial and Metric display preferences.
- Food definitions, favorites, meal logging, and recorded nutrition totals.
- Meal photo nutrition estimates with editable results and a personal OpenAI API key.
- Timestamped glucose, exercise, medication, mood, and measurement histories.
- Glucose charts for the past 6, 12, or 24 hours, displayed in local time.
- LibreView CSV imports and automatic LibreLinkUp glucose collection every five minutes.
- USDA FoodData Central search with nutrition review and saved food imports.
- Apple Health sleep, activity, vital, and workout uploads through an iPhone exporter.
- Paginated records with editing, soft deletion, restoration, and confirmed permanent deletion.
- Account ownership checks, CSRF protection, and production session security.

## Requirements

- Python 3.12
- MySQL
- Google OAuth credentials for a Web application
- Optional: LibreLinkUp sharing credentials and a USDA FoodData Central API key

## Local setup

Create a virtual environment and install the dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

On Windows, activate the environment with `.venv\Scripts\Activate.ps1`.

Configure `.env` with a MySQL connection URL, a random session secret, and the
Google client ID and secret. Register this local OAuth redirect URI:

```text
http://127.0.0.1:8000/auth/google/callback
```

Start the development server:

```bash
python -m uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`. Startup creates missing database tables and applies
recorded storage migrations. Back up existing data before upgrading.

`ALLOWED_EMAILS` accepts comma-separated exact Google email addresses. An empty
list permits verified Google accounts in development; production requires an
explicit list. Each account can access only its own records.

## Testing

Run the isolated application, security, and migration checks:

```bash
python scripts/check_release.py
```

The release checks use disposable SQLite databases and mocked provider responses.
They do not connect to the configured MySQL database. GitHub Actions runs the
same checks on pushes and pull requests.

`tests/check_mysql.py` separately checks the configured MySQL database using
transactions that are rolled back; auto-increment counters may advance.

## Deployment

See [deployment configuration](docs/DEPLOYMENT.md) for production settings,
service configuration, backups, and upgrades. Credentials and database exports
must remain outside version control.

## Project structure

Application code lives in `app/`, with routes, services, database code, shared
validation, templates, and browser assets in separate folders. Operational
commands remain in `scripts/`; tests and deployment templates have their own
folders. See [architecture](docs/ARCHITECTURE.md) and
[contributing](CONTRIBUTING.md) for the development workflow.

Run `python scripts/dev.py --help` to see the common development commands.

## Planned functionality

Prediction models and shared viewer access are not yet implemented.


## Acknowledgments and resources

- The LibreLinkUp connector was informed by Timo Schlüter's
  [nightscout-librelink-up](https://github.com/timoschlueter/nightscout-librelink-up)
  project, published under the [MIT License](https://github.com/timoschlueter/nightscout-librelink-up/blob/main/LICENSE.md).
  Sugar Watch uses an unofficial LibreLinkUp interface and is not affiliated with Abbott.
- Food and nutrient data are provided by
  [USDA FoodData Central](https://fdc.nal.usda.gov/) under
  [CC0](https://creativecommons.org/publicdomain/zero/1.0/).
  See the [API guide](https://fdc.nal.usda.gov/api-guide/) and
  [API key signup](https://fdc.nal.usda.gov/api-key-signup/).
- Built with [FastAPI](https://fastapi.tiangolo.com/),
  [SQLAlchemy](https://www.sqlalchemy.org/),
  [MySQL](https://www.mysql.com/), and
  [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect).

See [third-party notices](THIRD_PARTY_NOTICES.md) for the Libre integration reference license.

Apple Health uploads use [Health Auto Export](https://www.healthyapps.dev/) JSON
exports and a revocable account-scoped token. Its automatic REST API destination
requires Premium features and is subject to iOS background and unlocked-device
limits. See [exporter setup](https://help.healthyapps.dev/en/health-auto-export/automations/rest-api/)
and [deployment configuration](docs/DEPLOYMENT.md).

Apple Health uses free native Apple Health exports for history and workouts,
with a guided Apple Shortcuts setup for routine sample uploads. No paid export
app is required. iPhone permissions and setup are required; a signed one-tap
shortcut is not distributed. See the Apple Health page and deployment guide.
