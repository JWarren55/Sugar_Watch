"""Privately configure TLS SMTP verification mail; never send a test message."""

import getpass
import os
import shutil
import smtplib
import ssl
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import set_key

from app.core.email_settings import EmailSettings, normalize_email
from app.core.settings import settings


def main():
    print("Configure verification email. Do not use your regular Gmail password.")
    print("Use a dedicated mailbox with 2-Step Verification and an App Password.")
    provider = input("Sender: 1 = Gmail, 2 = another SMTP service [1]: ").strip() or "1"
    if provider not in ("1", "2"):
        raise ValueError("Choose 1 or 2.")
    sender = input("Sending email address: ").strip()
    if not normalize_email(sender):
        raise ValueError("Enter a complete sending email address.")
    sender = normalize_email(sender)
    if provider == "1":
        host, port, mode, username = "smtp.gmail.com", 587, "starttls", sender
        password = getpass.getpass("Gmail App Password (hidden): ").replace(" ", "")
    else:
        host = input("SMTP hostname: ").strip()
        port = int(input("SMTP port [587]: ").strip() or "587")
        mode = input("TLS mode (starttls or ssl) [starttls]: ").strip() or "starttls"
        username = input("SMTP username: ").strip()
        password = getpass.getpass("SMTP password or SMTP key (hidden): ")
    base = input("Public Sugar Watch URL (https://...): ").strip().rstrip("/")
    values = dict(
        EMAIL_SIGNUP_ENABLED="true",
        PUBLIC_BASE_URL=base,
        SMTP_HOST=host,
        SMTP_PORT=str(port),
        SMTP_TLS_MODE=mode,
        SMTP_USER=username,
        SMTP_PASSWORD=password,
        SMTP_FROM=sender,
    )
    EmailSettings.from_mapping(values, settings)
    context = ssl.create_default_context()
    print("Checking encrypted SMTP authentication; no email will be sent.")
    if mode == "ssl":
        client = smtplib.SMTP_SSL(host, port, timeout=15, context=context)
    else:
        client = smtplib.SMTP(host, port, timeout=15)
    try:
        with client:
            client.ehlo()
            if mode == "starttls":
                client.starttls(context=context)
                client.ehlo()
            client.login(username, password)
    except (OSError, smtplib.SMTPException):
        raise ValueError(
            "SMTP authentication failed. No settings were changed. Check the App Password and mailbox settings."
        ) from None
    target = ROOT / ".env"
    if target.is_symlink():
        raise ValueError("The .env file must be a regular local file.")
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix=".env.email-setup-", dir=ROOT)
        os.close(fd)
        temporary = Path(name)
        if target.exists():
            shutil.copyfile(target, temporary)
        os.chmod(temporary, 0o600)
        for key, value in values.items():
            set_key(temporary, key, value, quote_mode="always")
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    print(
        "PASS: SMTP authentication worked. Private settings saved; password not displayed."
    )
    print(
        "Activate or restart this installation to enable signup. No verification email was sent by setup."
    )
    print(
        "Also check that Google OAuth permits external users, rather than only listed test users."
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        print("Setup could not finish: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
