"""Email delivery abstraction for transactional auth mail.

v0.6 ships two backends: :class:`LoggingEmailSender` (writes to stderr;
the default for local dev) and :class:`SMTPEmailSender` (anonymous or
authenticated SMTP). Hosted transactional services (SES, Postmark,
Resend) can be added later by implementing :class:`EmailSender` — the
protocol is deliberately tiny.

Selection is env-driven. ``LUPLO_EMAIL_BACKEND`` picks the backend:

- unset / ``"logging"`` → :class:`LoggingEmailSender` (dev default)
- ``"smtp"`` → :class:`SMTPEmailSender` (reads ``LUPLO_SMTP_*`` vars)
"""

from __future__ import annotations

import os
import smtplib
import sys
from email.message import EmailMessage
from typing import Protocol


class EmailSender(Protocol):
    """Minimum surface for delivering a single transactional email."""

    async def send(self, *, to: str, subject: str, body: str) -> None:
        """Deliver an email. Raise on unrecoverable errors only."""
        ...


class LoggingEmailSender:
    """Development sender — writes the email to stderr and returns.

    The message body is preserved verbatim so reset links can be
    copy-pasted from the terminal during local testing. Never use in
    production: the plaintext token ends up in log aggregators.
    """

    async def send(self, *, to: str, subject: str, body: str) -> None:
        sys.stderr.write("\n--- [LoggingEmailSender] ---\n")
        sys.stderr.write(f"To:      {to}\n")
        sys.stderr.write(f"Subject: {subject}\n\n")
        sys.stderr.write(body)
        sys.stderr.write("\n--- /email ---\n\n")
        sys.stderr.flush()


class SMTPEmailSender:
    """Thin SMTP sender for plain or authenticated relays.

    Env configuration:
      - ``LUPLO_SMTP_HOST`` (required)
      - ``LUPLO_SMTP_PORT`` (default ``587``)
      - ``LUPLO_SMTP_USER`` (optional; login auth when set)
      - ``LUPLO_SMTP_PASSWORD`` (optional)
      - ``LUPLO_SMTP_FROM`` (required — the ``From:`` address)
      - ``LUPLO_SMTP_STARTTLS`` (``"1"`` by default — disable only for
        local dev relays on loopback)
    """

    def __init__(
        self,
        host: str,
        port: int,
        from_addr: str,
        user: str | None = None,
        password: str | None = None,
        use_starttls: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.from_addr = from_addr
        self.user = user
        self.password = password
        self.use_starttls = use_starttls

    @classmethod
    def from_env(cls) -> SMTPEmailSender:
        host = os.environ.get("LUPLO_SMTP_HOST")
        if not host:
            raise RuntimeError("LUPLO_SMTP_HOST is required for SMTPEmailSender")
        from_addr = os.environ.get("LUPLO_SMTP_FROM")
        if not from_addr:
            raise RuntimeError("LUPLO_SMTP_FROM is required for SMTPEmailSender")
        port = int(os.environ.get("LUPLO_SMTP_PORT", "587"))
        user = os.environ.get("LUPLO_SMTP_USER") or None
        password = os.environ.get("LUPLO_SMTP_PASSWORD") or None
        use_starttls = os.environ.get("LUPLO_SMTP_STARTTLS", "1") != "0"
        return cls(
            host=host,
            port=port,
            from_addr=from_addr,
            user=user,
            password=password,
            use_starttls=use_starttls,
        )

    async def send(self, *, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.from_addr
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        with smtplib.SMTP(self.host, self.port, timeout=30) as client:
            if self.use_starttls:
                client.starttls()
            if self.user and self.password:
                client.login(self.user, self.password)
            client.send_message(msg)


def email_sender_from_env() -> EmailSender:
    """Construct the active :class:`EmailSender` from environment config."""
    backend = os.environ.get("LUPLO_EMAIL_BACKEND", "logging").strip().lower()
    if backend == "smtp":
        return SMTPEmailSender.from_env()
    return LoggingEmailSender()
