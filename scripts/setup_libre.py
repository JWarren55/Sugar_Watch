"""Interactively configure Libre locally. Never run with credentials in arguments."""

import getpass
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from sqlalchemy import text

from libre_sync import SyncConfig, SyncError, _payload, fetch_readings


def choose(items, label):
    if not items:
        raise SyncError(f"No {label} available. Complete account setup first.")
    for index, (_, description) in enumerate(items, 1):
        print(f"  {index}. {description}")
    while True:
        value = input(f"Choose {label} number: ").strip()
        if value.isdigit() and 1 <= int(value) <= len(items):
            return items[int(value) - 1][0]
        print("Enter a number from the list.")


def save_config(path, values):
    # Atomic replacement with private permissions, including on an existing file.
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".libre-sync-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            for key, value in values.items():
                stream.write(f"{key}={json.dumps(str(value), ensure_ascii=False)}\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    if not sys.stdin.isatty():
        raise SyncError(
            "Run setup in your own interactive terminal so the password stays hidden."
        )
    print("Libre setup: no database changes or scheduled jobs will be made.")
    if (
        input("Does the new LibreLinkUp account show your shared readings? [yes/no]: ")
        .strip()
        .lower()
        != "yes"
    ):
        raise SyncError(
            "Accept the sharing invitation and confirm readings in LibreLinkUp first."
        )
    email = input("New LibreLinkUp follower account email: ").strip()
    password = getpass.getpass("LibreLinkUp password (hidden): ")
    region = input("Account region [us]: ").strip().lower() or "us"
    version = input("Installed LibreLinkUp app version (for example 4.16.0): ").strip()
    # Validate endpoint choices before credentials leave the machine.
    provisional = SyncConfig.from_mapping(
        dict(
            LIBRELINKUP_EMAIL=email,
            LIBRELINKUP_PASSWORD=password,
            LIBRELINKUP_REGION=region,
            LIBRELINKUP_VERSION=version,
            LIBRELINKUP_PATIENT_ID="pending",
            LIBRELINKUP_USER_ID="1",
        )
    )
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
        base = f"https://api-{provisional.region}.libreview.io"
        headers = {"product": "llu.ios", "version": version}
        data = _payload(
            client.post(
                base + "/llu/auth/login",
                headers=headers,
                json={"email": email, "password": password},
            )
        )
        if not isinstance(data, dict) or data.get("redirect"):
            raise SyncError(
                "Account region does not match. Rerun with the correct region."
            )
        import hashlib

        try:
            headers.update(
                Authorization="Bearer " + data["authTicket"]["token"],
                **{
                    "account-id": hashlib.sha256(
                        data["user"]["id"].encode()
                    ).hexdigest()
                },
            )
        except (KeyError, TypeError, AttributeError):
            raise SyncError(
                "Complete verification and consent in the official LibreLinkUp app."
            )
        connections = _payload(client.get(base + "/llu/connections", headers=headers))
        if not isinstance(connections, list):
            raise SyncError("LibreLinkUp connection response is unsupported.")
        items = [
            (
                c["patientId"],
                " ".join((c.get("firstName", ""), c.get("lastName", ""))).strip()
                or "Shared connection",
            )
            for c in connections
            if isinstance(c, dict) and isinstance(c.get("patientId"), str)
        ]
        print("Select your shared Libre connection:")
        patient = choose(items, "connection")

        # Read only. Do not import main.py, create tables, or run migrations here.
        from database import engine
        from settings import settings

        with engine.connect() as db:
            accounts = db.execute(
                text("SELECT id, email FROM users WHERE active = 1 ORDER BY id")
            ).all()
        items = [
            (row.id, row.email) for row in accounts if settings.permits_email(row.email)
        ]
        print("Select the Sugar Watch account that should receive your readings:")
        user_id = choose(items, "Sugar Watch account")
        values = dict(
            LIBRELINKUP_EMAIL=email,
            LIBRELINKUP_PASSWORD=password,
            LIBRELINKUP_REGION=region,
            LIBRELINKUP_VERSION=version,
            LIBRELINKUP_PATIENT_ID=patient,
            LIBRELINKUP_USER_ID=str(user_id),
        )
        rows = fetch_readings(SyncConfig.from_mapping(values), client)
    print(f"Connection test passed: {len(rows)} readings retrieved; nothing imported.")
    path = Path.home() / ".config/sugar-watch/libre-sync.env"
    if (
        path.exists()
        and input("Replace the existing local Libre configuration? [yes/no]: ")
        .strip()
        .lower()
        != "yes"
    ):
        print("Existing configuration kept. Nothing saved.")
        return 0
    save_config(path, values)
    print(f"Private configuration saved to {path} (owner read/write only).")
    print("SETUP PASSED. No readings imported and no hourly timer enabled.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled. No readings imported.", file=sys.stderr)
        raise SystemExit(1)
    except SyncError as exc:
        print(f"Setup stopped: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except Exception:
        print(
            "Setup stopped: connection or database check failed. No readings imported. Credentials and provider details are omitted.",
            file=sys.stderr,
        )
        raise SystemExit(1)
