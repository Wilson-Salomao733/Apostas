#!/usr/bin/env python3
"""Varredura única — envia oportunidades ao Telegram (GitHub Actions / cron manual)."""

import logging
import os
import sys
from configparser import ConfigParser

import requests

from api_football import APIFootball
from betfair_api import BetfairAPI
from opportunity_scanner import Opportunity, OpportunityScanner

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


def _load_keys() -> tuple[str, str]:
    football_key = os.getenv("API_FOOTBALL_KEY", "")
    groq_key = os.getenv("GROQ_API_KEY", "")
    if not football_key or not groq_key:
        cfg = ConfigParser()
        cfg.read("bot_config.ini")
        if not football_key:
            football_key = cfg.get("api_keys", "api_football_key", fallback="")
        if not groq_key:
            groq_key = cfg.get("api_keys", "groq_api_key", fallback="")
    return football_key, groq_key


def _telegram_cfg() -> tuple[str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        cfg = ConfigParser()
        cfg.read("bot_config.ini")
        token = token or cfg.get("telegram", "bot_token", fallback="")
        chat_id = chat_id or str(cfg.get("telegram", "chat_id", fallback=""))
    return token, chat_id


def _send(token: str, chat_id: str, text: str) -> None:
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=15,
    )
    resp.raise_for_status()


def _load_stake() -> float:
    cfg = ConfigParser()
    cfg.read("bot_config.ini")
    return float(cfg.get("manual", "stake", fallback="20.0"))


def main() -> int:
    token, chat_id = _telegram_cfg()
    if not token or not chat_id:
        log.error("Telegram não configurado")
        return 1

    football_key, groq_key = _load_keys()
    stake = _load_stake()

    _send(
        token, chat_id,
        "🔍 <b>Varredura iniciada</b> (GitHub Actions)\nAnalisando mercados...",
    )

    betfair = BetfairAPI()
    if not betfair.login():
        _send(token, chat_id, "❌ Falha no login Betfair")
        return 1

    scanner = OpportunityScanner(
        betfair, APIFootball(football_key), groq_key, stake=stake
    )
    opportunities = scanner.scan()

    if not opportunities:
        _send(
            token, chat_id,
            "😴 <b>Nenhuma oportunidade</b> encontrada agora.\n"
            "Tente novamente mais perto do horário dos jogos.",
        )
        return 0

    _send(
        token, chat_id,
        f"✅ <b>{len(opportunities)} oportunidade(s)</b>\n\n"
        "Para apostar, rode o workflow <b>Apostas — Confirmar Aposta</b> "
        "no GitHub com o <code>opp_id</code> abaixo.",
    )

    for opp in opportunities:
        risk_emoji = {"baixo": "🟢", "médio": "🟡"}.get(opp.risk, "⚪")
        text = (
            f"{risk_emoji} <b>{opp.bet_type}</b>\n\n"
            f"⚽ <b>{opp.home}</b> x <b>{opp.away}</b>\n"
            f"🏆 {opp.league}\n"
            f"📊 {opp.selection_label} @ <b>{opp.odds:.2f}</b>\n"
            f"💵 Stake: R$ {opp.stake:.0f} → Lucro: R$ {opp.potential_profit:.2f}\n"
            f"🤖 IA: {opp.confidence}%\n"
            f"💬 <i>{opp.reasoning}</i>\n\n"
            f"🆔 <code>opp_id</code>: <b>{opp.opp_id}</b>"
        )
        _send(token, chat_id, text)

    log.info("Varredura concluída: %d oportunidade(s)", len(opportunities))
    return 0


if __name__ == "__main__":
    sys.exit(main())
