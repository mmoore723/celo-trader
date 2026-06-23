"""
alerts.py — Email and logging alert system for critical bot events.

Alerts fire for:
  - API connection failures
  - Daily loss limit hit
  - Critical errors (exceptions in the main loop)
  - Insufficient buying power
  - Market data delay detected

Email uses Python's built-in smtplib so no extra dependencies.
If SMTP credentials are not configured, alerts are logged to console only.
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from config import (
    ALERT_EMAIL, ALERT_SMTP_HOST, ALERT_SMTP_PORT,
    ALERT_SMTP_USER, ALERT_SMTP_PASS,
)

logger = logging.getLogger("celo_trader.alerts")


def send_alert(subject: str, body: str) -> None:
    """
    Send an alert email to ALERT_EMAIL.
    Respects the email_alerts_enabled toggle from Risk Settings.
    Falls back silently to log-only if SMTP is not configured or alerts disabled.
    """
    logger.warning("ALERT: %s | %s", subject, body)

    # Check live settings — if email alerts toggled off, log only
    try:
        from config import get_settings
        if not get_settings().get("email_alerts_enabled", False):
            return
    except Exception:
        return  # if config unavailable, don't crash bot trying to send email

    if not all([ALERT_EMAIL, ALERT_SMTP_USER, ALERT_SMTP_PASS]):
        return  # SMTP not configured

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[CeloTrader] {subject} — {datetime.utcnow().strftime('%H:%M UTC')}"
        msg["From"]    = ALERT_SMTP_USER
        msg["To"]      = ALERT_EMAIL

        text_body = f"{body}\n\nTime: {datetime.utcnow().isoformat()}"
        msg.attach(MIMEText(text_body, "plain"))

        with smtplib.SMTP(ALERT_SMTP_HOST, ALERT_SMTP_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(ALERT_SMTP_USER, ALERT_SMTP_PASS)
            server.sendmail(ALERT_SMTP_USER, ALERT_EMAIL, msg.as_string())

        logger.info("Alert email sent to %s", ALERT_EMAIL)

    except Exception as e:
        logger.error("Failed to send alert email: %s", e)
