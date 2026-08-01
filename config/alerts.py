"""
config/alerts.py — Email/SMTP alert settings.

Split out of the old single config.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import os

ALERT_EMAIL       = os.getenv("ALERT_EMAIL", "")
ALERT_SMTP_HOST   = os.getenv("ALERT_SMTP_HOST", "smtp.gmail.com")
ALERT_SMTP_PORT   = int(os.getenv("ALERT_SMTP_PORT", "587"))
ALERT_SMTP_USER   = os.getenv("ALERT_SMTP_USER", "")
ALERT_SMTP_PASS   = os.getenv("ALERT_SMTP_PASS", "")
