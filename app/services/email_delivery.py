"""Send plain verification mail; never log message bodies, credentials, or links."""

import smtplib
import ssl
from email.message import EmailMessage


class DeliveryError(Exception):
    pass


def send_verification(config, recipient, link):
    message = EmailMessage()
    message["Subject"] = "Verify your email for Sugar Watch"
    message["From"] = "Sugar Watch <" + config.sender + ">"
    message["To"] = recipient
    message.set_content(
        "You requested to join Sugar Watch.\n\n"
        "Open this link, then choose Verify my email:\n" + link + "\n\n"
        "This link expires in 30 minutes and can be used once. After verification, "
        "sign in with Google using this same email address.\n\n"
        "If you did not request this, ignore this message. Your email will not be approved unless you confirm.\n"
    )
    context = ssl.create_default_context()
    try:
        if config.tls_mode == "ssl":
            client = smtplib.SMTP_SSL(
                config.smtp_host, config.smtp_port, timeout=15, context=context
            )
        else:
            client = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15)
        with client:
            client.ehlo()
            if config.tls_mode == "starttls":
                client.starttls(context=context)
                client.ehlo()
            client.login(config.smtp_user, config.smtp_password)
            client.send_message(message)
    except (smtplib.SMTPException, OSError):
        raise DeliveryError(
            "Verification email could not be sent. Try again later."
        ) from None
