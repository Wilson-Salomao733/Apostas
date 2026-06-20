#!/usr/bin/env python3
"""Processa cliques e mensagens do Telegram (poll a cada 5 min)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from telegram_actions import poll_once


def main() -> int:
    n = poll_once()
    print(f"Updates processados: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
