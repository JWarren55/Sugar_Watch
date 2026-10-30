"""Load validated application settings without exposing credentials."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    secret_key: str = field(repr=False)
    database_url: str = field(repr=False)
    production: bool
    allowed_hosts: tuple[str, ...]
    allowed_emails: tuple[str, ...] = field(default=(), repr=False)
    session_max_age: int = 8 * 60 * 60
    max_body_bytes: int = 1024 * 1024

    @classmethod
    def from_mapping(cls, values):
        # Fail early rather than starting with missing security settings.
        secret = values.get("SECRET_KEY", "").strip()
        database_url = values.get("DATABASE_URL", "").strip()
        environment = values.get("APP_ENV", "development").lower()
        if environment not in ("development", "test", "production"):
            raise ValueError("APP_ENV must be development, test, or production.")
        production = environment == "production"
        if not secret:
            raise ValueError("SECRET_KEY is required in the environment or .env.")
        if production and len(secret) < 32:
            raise ValueError(
                "Production SECRET_KEY must contain at least 32 characters."
            )
        if not database_url:
            raise ValueError("DATABASE_URL is required in the environment or .env.")
        raw_hosts = values.get("ALLOWED_HOSTS", "")
        hosts = tuple(host.strip() for host in raw_hosts.split(",") if host.strip())
        if production and (
            not hosts
            or any("*" in host or "://" in host or "/" in host for host in hosts)
        ):
            raise ValueError(
                "Production ALLOWED_HOSTS must name the application's hosts."
            )
        emails = tuple(
            email.strip().casefold()
            for email in values.get("ALLOWED_EMAILS", "").split(",")
            if email.strip()
        )
        if production and not emails:
            raise ValueError("Production ALLOWED_EMAILS must name approved Google accounts.")
        if any(
            email.count("@") != 1
            or not all(email.split("@"))
            or "*" in email
            or any(c.isspace() for c in email)
            for email in emails
        ):
            raise ValueError("ALLOWED_EMAILS must contain exact email addresses, not patterns.")
        return cls(
            secret,
            database_url,
            production,
            hosts or ("localhost", "127.0.0.1", "testserver"),
            emails,
        )

    def permits_email(self, email):
        return isinstance(email, str) and (
            not self.allowed_emails or email.strip().casefold() in self.allowed_emails
        )


settings = Settings.from_mapping(os.environ)
