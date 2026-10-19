# Sugar Watch

## Description
A FastAPI application for tracking glucose, nutrition, exercise, medication, mood, and health measurements.

## Tools

- Python

### Python pip installs

#### Web application
- fastapi
- uvicorn
- jinja2
- python-multipart

#### Google authentication
- authlib
- itsdangerous
- httpx
- python-dotenv

### MySQL database
- sqlalchemy
- pymysql

### Run locally

```
source .venv/bin/activate
uvicorn main:app --reload
```

## Timeline

### Core
- Account login
- Input data
    - From Dexcom
    - Nutrition
    - Exercise
    - Mood
        - Feeling
        - Hunger
        - Head clarity
- Explore analysis
    - Plots
    - Averages
    - Standard Deviation
    - Blood Sugar Timeline
    - Nutrition percentages
    - Fasting effect and interval
    - Mood timeline

### Connection
- Viewer Account
    - Allowed and restricted data

### Data Science
- Baseline Model
    - Predict glucose
- What if? Model
    - predict after food, exercise, and medication

### Extra
- Personalize dashboard
- Camera to Chat GPT to estimate nutrition of food

### Using Mysql
- mysql -u sugar_watch_app -p
- USE sugar_watch;

## Progress Report 1 verification

Open http://127.0.0.1:8000/ for the registered Google sign-in callback.

See [the report checklist](docs/PROGRESS_REPORT_1.md) for verified features,
database evidence, and a demonstration walkthrough.

Run from the project root:

```bash
PYTHONPATH=. .venv/bin/python tests/check_features.py
PYTHONPATH=. .venv/bin/python tests/check_mysql.py
```

The feature checks use an isolated SQLite database. The MySQL check rolls back
its demonstration inserts. Install the recorded environment with
`pip install -r requirements.txt`.


## Code style

Use short, one-line comments to explain each main step:
`#` in Python, `//` in JavaScript, and `<!-- -->` in HTML.
Python and JavaScript use four-space indentation. Page scripts live in `static/`.

Optional formatting tools:

```bash
pip install -r requirements-dev.txt
ruff check .
ruff format .
djlint templates --reformat
```
