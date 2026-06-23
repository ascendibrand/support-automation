"""Minimal Telegram alert sender — stdlib only, no extra pip dependency."""
from __future__ import annotations

import os
import urllib.parse
import urllib.request


def send_alert(message: str) -> bool:
    """Send `message` to the configured Telegram chat. Returns True on success."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("  [telegram] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set — skipping alert")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()

    try:
        with urllib.request.urlopen(url, data=data, timeout=10) as resp:
            return resp.status == 200
    except Exception as exc:
        print(f"  [telegram] ERROR sending alert: {exc}")
        return False
