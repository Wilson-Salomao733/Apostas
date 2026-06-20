#!/usr/bin/env python3
"""Aposta única por opp_id — acionado manualmente via GitHub Actions."""

import logging
import os
import sys
import uuid
from configparser import ConfigParser

import requests

from betfair_api import BetfairAPI
from opportunity_scanner import OpportunityScanner

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


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
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=15,
    ).raise_for_status()


def main() -> int:
    opp_id = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("OPP_ID", "")).strip()
    if not opp_id:
        log.error("Informe opp_id: python bet_once.py <opp_id>")
        return 1

    token, chat_id = _telegram_cfg()

    opp = OpportunityScanner.load_pending(opp_id)
    if not opp:
        msg = (
            f"⚠️ Oportunidade <code>{opp_id}</code> não encontrada ou expirada.\n"
            "Rode primeiro o workflow <b>Apostas — Varredura</b>."
        )
        if token and chat_id:
            _send(token, chat_id, msg)
        log.error("Oportunidade não encontrada: %s", opp_id)
        return 1

    home, away = opp["home"], opp["away"]
    if token and chat_id:
        _send(token, chat_id, f"⏳ Apostando em <b>{home} x {away}</b>...")

    betfair = BetfairAPI()
    if not betfair.login():
        if token and chat_id:
            _send(token, chat_id, "❌ Falha no login Betfair")
        return 1

    try:
        customer_ref = f"GH_{uuid.uuid4().hex[:12].upper()}"
        result = betfair.place_orders(
            market_id=opp["market_id"],
            instructions=[{
                "instructionType": "LIMIT",
                "selectionId": int(opp["selection_id"]),
                "side": "BACK",
                "orderType": "LIMIT",
                "limitOrder": {
                    "size": round(float(opp["stake"]), 2),
                    "price": round(float(opp["odds"]), 2),
                    "persistenceType": "LAPSE",
                },
            }],
            customer_ref=customer_ref,
        )

        if not result or result.get("status") != "SUCCESS":
            err = result.get("errorCode", "Erro desconhecido") if result else "Sem resposta"
            if token and chat_id:
                _send(token, chat_id, f"❌ Falha: <code>{err}</code>")
            return 1

        reports = result.get("instructionReports", [])
        bet_id = reports[0].get("betId", customer_ref) if reports else customer_ref

        if token and chat_id:
            _send(
                token, chat_id,
                f"✅ <b>Aposta confirmada!</b>\n\n"
                f"⚽ {home} x {away}\n"
                f"📊 {opp['bet_type']} @ {opp['odds']:.2f}\n"
                f"💵 Stake: R$ {opp['stake']:.2f}\n"
                f"🆔 <code>{bet_id}</code>",
            )
        log.info("Aposta OK: %s", bet_id)
        return 0

    except Exception as e:
        if token and chat_id:
            _send(token, chat_id, f"❌ Erro: {e}")
        log.exception("Erro ao apostar")
        return 1


if __name__ == "__main__":
    sys.exit(main())
