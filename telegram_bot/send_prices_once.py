#!/usr/bin/env python3
"""Envia preços crypto no Telegram (cron 12h e 18h)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from telegram_actions import allowed_chat, format_prices, send, MAIN_INLINE


def main() -> int:
    chat = allowed_chat()
    if not chat:
        print("TELEGRAM_CHAT_ID não configurado")
        return 1
    send(chat, format_prices(scheduled=True), MAIN_INLINE)
    print("Preços enviados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
