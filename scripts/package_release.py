"""Build a source-only release bundle; never include local accounts or data."""

import hashlib
import io
import json
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = {
    "routes",
    "templates",
    "static",
    "scripts",
    "tests",
    "deploy",
    "docs",
    ".github",
}
FILES = {
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    ".env.example",
}


def selected(path):
    parts = path.parts
    if any(p in {"__pycache__", ".git", ".venv", "backups", "dist"} for p in parts):
        return False
    if path.name.startswith(".env") and path.name != ".env.example":
        return False
    if path.suffix.lower() in {
        ".pyc",
        ".sql",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".csv",
        ".gpg",
        ".pem",
        ".key",
    }:
        return False
    if ".sql." in path.name.lower() or path.suffix.lower() in {
        ".cnf",
        ".conf",
        ".p12",
        ".pfx",
    }:
        return False
    if path.name.endswith(".env"):
        return False
    return (len(parts) == 1 and (path.name in FILES or path.suffix == ".py")) or parts[
        0
    ] in DIRECTORIES


def main():
    names = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
        )
        .decode()
        .split("\0")
    )
    paths = sorted({name for name in names if name and selected(Path(name))})
    files = []
    for name in paths:
        path = ROOT / name
        if path.is_symlink():
            raise RuntimeError("Release bundles cannot contain symbolic links.")
        if path.is_file():
            files.append(name)
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT)
        .decode()
        .strip(),
        "working_tree_changes": bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)
        ),
        "files": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in files
        },
    }
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    output = destination / (
        "sugar-watch-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        + ".tar.gz"
    )
    with tarfile.open(output, "w:gz") as bundle:
        for name in files:
            bundle.add(
                ROOT / name, arcname="sugar-watch-release/" + name, recursive=False
            )
        content = json.dumps(manifest, indent=2).encode()
        info = tarfile.TarInfo("sugar-watch-release/RELEASE.json")
        info.size = len(content)
        info.mode = 0o644
        bundle.addfile(info, io.BytesIO(content))
    print(output)
    print(
        "Source bundle only. Database, backups, virtualenv, and local Libre login are excluded."
    )


if __name__ == "__main__":
    main()
