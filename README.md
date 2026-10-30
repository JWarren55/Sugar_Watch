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


## Server deployment

See [Ubuntu VM deployment and GitHub updates](docs/DEPLOYMENT.md).
