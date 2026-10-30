"""Run isolated release checks without loading laptop or server credentials."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
checks = (
    "check_security.py",
    "check_deployment.py",
    "check_production.py",
    "check_features.py",
    "check_history_features.py",
    "check_history_migration.py",
    "check_storage_migration.py",
)
env = dict(os.environ)
env.update(
    APP_ENV="test",
    ALLOWED_EMAILS="",
    ALLOWED_HOSTS="localhost,127.0.0.1,testserver",
    DATABASE_URL="sqlite://",
    SECRET_KEY="isolated-release-check-secret",
    GOOGLE_CLIENT_ID="release-check-not-a-real-client",
    GOOGLE_CLIENT_SECRET="release-check-not-a-real-secret",
    PYTHONPATH=str(ROOT),
    PYTHONDONTWRITEBYTECODE="1",
)
for check in checks:
    print(f"Checking {check}", flush=True)
    subprocess.run([sys.executable, str(ROOT / "tests" / check)], cwd=ROOT, env=env, check=True)
print("PASS: all isolated release checks")
