# Sugar Watch

Sugar Watch is a FastAPI application for recording glucose readings, nutrition,
exercise, medication, mood, and health measurements. Data is stored in MySQL,
and users authenticate with Google OpenID Connect.

## Features

- Google sign-in with optional account restrictions and required production allowlists.
- Health profiles with Imperial and Metric display preferences.
- Food definitions, favorites, meal logging, and recorded nutrition totals.
- Timestamped glucose, exercise, medication, mood, and measurement histories.
- Paginated records with editing, soft deletion, restoration, and confirmed permanent deletion.
- Account ownership checks, CSRF protection, and production session security.

## Requirements

- Python 3.12
- MySQL
- Google OAuth credentials for a Web application

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

The release checks use disposable SQLite databases and mocked Google responses.
They do not connect to the configured MySQL database. GitHub Actions runs the
same checks on pushes and pull requests.

`tests/check_mysql.py` separately checks the configured MySQL database using
transactions that are rolled back; auto-increment counters may advance.

## Deployment

See [deployment configuration](docs/DEPLOYMENT.md) for production settings,
service configuration, backups, and upgrades. Credentials and database exports
must remain outside version control.

## Planned functionality

Dexcom import, charts, prediction models, and shared viewer access are not yet
implemented.
