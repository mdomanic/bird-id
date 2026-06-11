"""Notifications: Windows desktop toast and optional email."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path

from config import settings


def _notify_desktop(title: str, message: str, image_path: Path | None) -> None:
    try:
        from winotify import Notification
    except ImportError:
        return  # not on Windows, or winotify not installed — silently skip
    try:
        toast = Notification(app_id="Bird ID", title=title, msg=message)
        if image_path and image_path.exists():
            # winotify shows an icon from a local absolute path.
            toast.icon = str(image_path.resolve())
        toast.show()
    except Exception as exc:  # never let a notification failure break the watcher
        print(f"[notifier] desktop toast failed: {exc}")


def _notify_email(title: str, message: str, image_path: Path | None) -> None:
    if not (settings.email_to and settings.smtp_host and settings.smtp_username):
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = title
        msg["From"] = settings.smtp_username
        msg["To"] = settings.email_to
        msg.set_content(message)
        if image_path and image_path.exists():
            msg.add_attachment(
                image_path.read_bytes(),
                maintype="image",
                subtype="jpeg",
                filename=image_path.name,
            )
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
    except Exception as exc:
        print(f"[notifier] email failed: {exc}")


def notify(title: str, message: str, image_path: Path | None = None) -> None:
    """Send a notification via all configured channels."""
    print(f"[notify] {title} - {message}")
    _notify_desktop(title, message, image_path)
    _notify_email(title, message, image_path)
