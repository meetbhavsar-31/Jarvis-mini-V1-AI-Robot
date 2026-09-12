"""
jarvis/alerts/notifier.py

Free, no-paid-plan alerting for JARVIS. Two channels, both entirely free
forever (no card, no trial-then-paywall):

1. Telegram Bot API -- message straight to your phone via Telegram.
   Setup (5 min, free):
     a) In Telegram, message @BotFather -> /newbot -> follow prompts ->
        you get a bot token like "123456:ABC-DEF...".
     b) Message your new bot anything (so it can find your chat).
     c) Visit https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates in a
        browser -- find "chat":{"id": <NUMBER>} in the response, that's
        your chat id.
     d) Put both in your .env:
          TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
          TELEGRAM_CHAT_ID=987654321

2. ntfy.sh -- even simpler, no account/signup at all.
   Setup (2 min, free):
     a) Install the "ntfy" app (Android/iOS) or just use a browser.
     b) Pick any unique-ish topic name, e.g. "jarvis-mini-meet-8213".
     c) In the app, subscribe to that exact topic name.
     d) Put it in your .env:
          NTFY_TOPIC=jarvis-mini-meet-8213

You can configure one or both -- notify_emergency() sends to every channel
that has its env vars set, and silently skips any that don't.
"""

import os
import requests
from dotenv import load_dotenv
from jarvis.common.logger import setup_logger

load_dotenv()
logger = setup_logger()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").strip().rstrip("/")


def send_telegram_alert(message: str, title: str = "JARVIS") -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        text = f"🤖 {title}\n{message}"
        res = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=8)
        if res.status_code == 200:
            return True
        logger.error(f"Telegram alert failed: HTTP {res.status_code} - {res.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"Telegram alert error: {e}")
        return False


def send_ntfy_alert(message: str, title: str = "JARVIS", priority: str = "default", tags: str = "robot") -> bool:
    """priority: 'min'|'low'|'default'|'high'|'urgent'"""
    if not NTFY_TOPIC:
        return False
    try:
        url = f"{NTFY_SERVER}/{NTFY_TOPIC}"
        headers = {"Title": title, "Priority": priority, "Tags": tags}
        res = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=8)
        if res.status_code == 200:
            return True
        logger.error(f"ntfy alert failed: HTTP {res.status_code} - {res.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"ntfy alert error: {e}")
        return False


def notify_emergency(message: str, title: str = "JARVIS Alert", priority: str = "urgent") -> dict:
    """
    Fires the alert to every configured channel. Returns which channels
    actually succeeded, so callers/logs can tell if an alert genuinely went
    out or silently failed (e.g. bad token, no internet).
    """
    results = {
        "telegram": send_telegram_alert(message, title=title),
        "ntfy": send_ntfy_alert(message, title=title, priority=priority, tags="rotating_light"),
    }
    if not any(results.values()):
        if TELEGRAM_BOT_TOKEN or NTFY_TOPIC:
            logger.error(f"ALERT DISPATCH FAILED on all configured channels: {message}")
        else:
            logger.warning(f"No alert channel configured (TELEGRAM_BOT_TOKEN/NTFY_TOPIC unset) -- alert not sent: {message}")
    return results


def notify_info(message: str, title: str = "JARVIS") -> dict:
    """Lower-priority variant for non-emergency notices (e.g. reminders)."""
    return {
        "telegram": send_telegram_alert(message, title=title),
        "ntfy": send_ntfy_alert(message, title=title, priority="default", tags="bell"),
    }
