from email.message import EmailMessage
import logging
from typing import Any, Dict, Optional
import aiosmtplib
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def send_slack_alert(
    message: str,
    webhook_url: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
) -> bool:
    """Dispatches a notification message to a Slack incoming webhook."""
    url = webhook_url or settings.SLACK_WEBHOOK_URL
    if not url:
        return False

    payload: Dict[str, Any] = {
        "text": message,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*API Alert:*\n{message}"}
            }
        ]
    }

    if details:
        payload["blocks"].append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```{details}```"}
        })

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Failed to dispatch Slack alert: {e}")
        return False


async def send_email_alert(
    subject: str,
    body: str,
    to_email: Optional[str] = None
) -> bool:
    """Dispatches an alert email via SMTP using aiosmtplib."""
    to_addr = to_email or settings.SMTP_TO
    if not settings.SMTP_HOST or not to_addr:
        return False

    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = to_addr
    message["Subject"] = subject
    message.set_content(body)

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER or None,
            password=settings.SMTP_PASSWORD or None,
            start_tls=settings.SMTP_USE_TLS
        )
        return True
    except Exception as e:
        logger.error(f"Failed to dispatch email alert: {e}")
        return False
