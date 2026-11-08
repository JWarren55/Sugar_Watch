"""Common development commands, run from any working directory."""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, allowed=(0,)):
    result = subprocess.run([sys.executable, *args], cwd=ROOT)
    if result.returncode not in allowed:
        raise SystemExit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("check", "lint", "format", "serve", "package")
    )
    command = parser.parse_args().command
    if command == "check":
        run("scripts/check_release.py")
    elif command == "lint":
        run(
            "-m", "ruff", "check", "app", "scripts", "tests", "main.py", "migrations.py"
        )
        run(
            "-m",
            "ruff",
            "format",
            "--check",
            "app",
            "scripts",
            "tests",
            "main.py",
            "migrations.py",
        )
        run("-m", "djlint", "app/templates", "--check", "--quiet")
    elif command == "format":
        run(
            "-m",
            "ruff",
            "format",
            "app",
            "scripts",
            "tests",
            "main.py",
            "migrations.py",
        )
        run(
            "-m",
            "ruff",
            "check",
            "--fix",
            "app",
            "scripts",
            "tests",
            "main.py",
            "migrations.py",
        )
        run("-m", "djlint", "app/templates", "--reformat", "--quiet", allowed=(0, 1))
    elif command == "serve":
        run("-m", "uvicorn", "main:app", "--reload", "--host", "127.0.0.1")
    elif command == "package":
        run("scripts/check_release.py")
        run("scripts/package_release.py")


if __name__ == "__main__":
    main()
