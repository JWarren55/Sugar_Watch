"""Optional encrypted SMTP delivery for public email verification."""

import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.core.settings import settings


def normalize_email(value):
    if not isinstance(value, str):
        return None
    value = value.strip().casefold()
    if len(value) > 254 or not re.fullmatch(
        r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}",
        value,
    ):
        return None
    return value


@dataclass(frozen=True)
class EmailSettings:
    enabled: bool = False
    public_base_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = field(default="", repr=False)
    smtp_password: str = field(default="", repr=False)
    sender: str = field(default="", repr=False)
    tls_mode: str = "starttls"

    @classmethod
    def from_mapping(cls, values, app_settings=settings):
        enabled = values.get("EMAIL_SIGNUP_ENABLED", "false").strip().lower()
        if enabled not in ("true", "false"):
            raise ValueError("EMAIL_SIGNUP_ENABLED must be true or false.")
        enabled = enabled == "true"
        try:
            port = int(values.get("SMTP_PORT", "587"))
        except ValueError:
            raise ValueError("SMTP_PORT must be a port number.")
        config = cls(
            enabled=enabled,
            public_base_url=values.get("PUBLIC_BASE_URL", "").rstrip("/"),
            smtp_host=values.get("SMTP_HOST", "").strip(),
            smtp_port=port,
            smtp_user=values.get("SMTP_USER", "").strip(),
            smtp_password=values.get("SMTP_PASSWORD", ""),
            sender=values.get("SMTP_FROM", "").strip(),
            tls_mode=values.get("SMTP_TLS_MODE", "starttls").strip(),
        )
        if enabled:
            url = urlsplit(config.public_base_url)
            try:
                url.port
            except ValueError:
                raise ValueError("PUBLIC_BASE_URL has an invalid port.") from None
            if (
                url.scheme != "https"
                or not url.hostname
                or url.hostname not in app_settings.allowed_hosts
                or url.username
                or url.password
                or url.path
                or url.query
                or url.fragment
            ):
                raise ValueError(
                    "PUBLIC_BASE_URL must be an HTTPS origin on an allowed application host."
                )
            if (
                not config.smtp_host
                or any(c.isspace() for c in config.smtp_host)
                or not 1 <= port <= 65535
                or not config.smtp_user
                or not config.smtp_password
                or not normalize_email(config.sender)
            ):
                raise ValueError(
                    "Configure SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, and SMTP_FROM before enabling email signup."
                )
            if config.tls_mode not in ("starttls", "ssl"):
                raise ValueError(
                    "SMTP_TLS_MODE must be starttls or ssl; unencrypted delivery is not supported."
                )
        return config


email_settings = EmailSettings.from_mapping(os.environ)
