"""Sends task-completion emails over SMTP. Uses only the standard library
(smtplib/email) — no extra dependency to install.
"""
import os
import smtplib
from email.mime.text import MIMEText

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
MAIL_FROM = os.environ.get("MAIL_FROM", SMTP_USER)
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "")


def send_email(subject, body):
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and NOTIFY_EMAIL):
        print("[mailer] SMTP not fully configured, skipping email")
        return False

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = MAIL_FROM
    msg["To"] = NOTIFY_EMAIL

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(MAIL_FROM, [NOTIFY_EMAIL], msg.as_string())
        print(f"[mailer] sent: {subject!r}")
        return True
    except Exception as exc:
        print(f"[mailer] failed to send: {exc}")
        return False


def send_task_email(description, result, success=True):
    status = "done" if success else "failed"
    subject = f"Jarvis task {status}: {description[:60]}"
    body = (
        f"Task: {description}\n\n"
        f"Status: {'Completed' if success else 'Failed'}\n\n"
        f"Result:\n{result}"
    )
    return send_email(subject, body)
