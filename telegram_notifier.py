"""
ArchiScrapping — Telegram Notification Module.
Sends real-time alerts to a Telegram chat or channel whenever new architect offers are found.
"""
import logging
import html
import time
from typing import List, Tuple, Optional
import requests

from config import settings
from database import Job

logger = logging.getLogger("archiscrapping.telegram")

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"


def is_telegram_configured() -> bool:
    """Check if Telegram bot token and chat ID are configured."""
    return bool(
        settings.telegram_enabled
        and settings.telegram_bot_token
        and settings.telegram_chat_id
    )


def send_telegram_message(text: str, parse_mode: str = "HTML") -> Tuple[bool, Optional[str]]:
    """
    Send a message to the configured Telegram chat.

    Returns:
        (success: bool, error_message: Optional[str])
    """
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False, "Telegram bot token or chat ID is not configured."

    url = TELEGRAM_API_BASE.format(token=settings.telegram_bot_token, method="sendMessage")
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        data = response.json()
        if response.status_code == 200 and data.get("ok"):
            return True, None
        error_desc = data.get("description", f"HTTP {response.status_code}")
        logger.error(f"Telegram send failed: {error_desc}")
        return False, error_desc
    except Exception as e:
        logger.error(f"Error connecting to Telegram API: {e}")
        return False, str(e)


def format_job_message(job: Job) -> str:
    """Format a single Job record into a sleek HTML Telegram message."""
    title = html.escape(job.title or "Untitled Position")
    company = html.escape(job.company or "Company not specified")
    city = html.escape(job.city or "Germany")
    state = f", {html.escape(job.state)}" if job.state else ""

    salary = job.salary_display
    salary_str = html.escape(salary) if salary else "<i>Not specified</i>"

    # Date posted
    if job.date_posted:
        date_str = job.date_posted.strftime("%d.%m.%Y")
    else:
        date_str = "Recently posted"

    # Job type
    job_type_str = f" • 🏷️ {html.escape(job.job_type)}" if job.job_type else ""

    # Source links
    source_links = []
    if job.sources:
        for s in job.sources:
            s_name = s.site_name.capitalize()
            if s.site_url:
                source_links.append(f'<a href="{html.escape(s.site_url)}">{s_name}</a>')
            else:
                source_links.append(s_name)
    sources_formatted = " | ".join(source_links) if source_links else "Aggregator"

    # Multi-source badge
    cross_post_badge = ""
    if job.source_count > 1:
        cross_post_badge = f"\n🔄 <b>Found on {job.source_count} sites!</b>"

    message = (
        f"🏛️ <b>New Architect Offer in Germany!</b>\n\n"
        f"💼 <b>{title}</b>\n"
        f"🏢 <b>Company:</b> {company}\n"
        f"📍 <b>Location:</b> {city}{state}{job_type_str}\n"
        f"💰 <b>Salary:</b> {salary_str}\n"
        f"📅 <b>Posted:</b> {date_str}{cross_post_badge}\n\n"
        f"🔗 <b>Apply / View:</b> {sources_formatted}"
    )
    return message


def notify_new_jobs(jobs: List[Job]) -> int:
    """
    Send notifications for newly discovered jobs.
    Implements gentle rate limiting and batching to avoid spamming / hitting Telegram rate limits.

    Returns:
        Number of notifications successfully sent.
    """
    if not is_telegram_configured():
        logger.debug("Telegram notifications are not configured; skipping.")
        return 0

    if not jobs:
        return 0

    logger.info(f"Preparing Telegram alerts for {len(jobs)} new jobs...")

    sent_count = 0
    max_individual = 10  # Send at most 10 individual messages per scrape batch

    # Send individual messages for the first batch
    for i, job in enumerate(jobs[:max_individual]):
        msg = format_job_message(job)
        success, err = send_telegram_message(msg)
        if success:
            sent_count += 1
        # Sleep slightly to respect Telegram's rate limits
        time.sleep(0.35)

    # If there are more than max_individual jobs, send a digest summary
    if len(jobs) > max_individual:
        remaining = len(jobs) - max_individual
        summary_msg = (
            f"🏛️ <b>+{remaining} more new architect positions found!</b>\n\n"
            f"Check the ArchiScrapping dashboard to filter and view all {len(jobs)} new offers."
        )
        send_telegram_message(summary_msg)
        time.sleep(0.35)

    logger.info(f"Telegram notifications finished: {sent_count} messages sent.")
    return sent_count


def test_telegram_connection() -> Tuple[bool, str]:
    """Send a test message to verify Telegram bot setup."""
    if not settings.telegram_bot_token:
        return False, "TELEGRAM_BOT_TOKEN is missing."
    if not settings.telegram_chat_id:
        return False, "TELEGRAM_CHAT_ID is missing."

    test_msg = (
        "🏛️ <b>ArchiScrapping Alert System</b>\n\n"
        "✅ <b>Telegram connection successful!</b>\n"
        "You will receive immediate alerts whenever a new architect position is found in Germany."
    )
    success, error = send_telegram_message(test_msg)
    if success:
        return True, "Test alert sent successfully to Telegram!"
    return False, f"Failed to send test message: {error}"
