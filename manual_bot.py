#!/usr/bin/env python3
"""
Bot manual de apostas — varredura sob demanda via Telegram.
Só aposta quando você clica em confirmar.
"""

import json
import logging
import os
import signal
import sys
import threading
import time
import uuid
from configparser import ConfigParser
from datetime import datetime
from typing import Optional

import requests

from api_football import APIFootball
from betfair_api import BetfairAPI
from database import BetDatabase
from opportunity_scanner import Opportunity, OpportunityScanner

# ─── Logging ──────────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

OFFSET_FILE = "data/telegram_offset.txt"


def _load_keys() -> tuple[str, str]:
    football_key = os.getenv("API_FOOTBALL_KEY", "")
    groq_key = os.getenv("GROQ_API_KEY", "")
    if not football_key or not groq_key:
        cfg = ConfigParser()
        for path in ["bot_config.ini", "/app/bot_config.ini"]:
            if os.path.exists(path):
                cfg.read(path)
                break
        if not football_key:
            football_key = cfg.get("api_keys", "api_football_key", fallback="")
        if not groq_key:
            groq_key = cfg.get("api_keys", "groq_api_key", fallback="")
    return football_key, groq_key


def _load_telegram() -> tuple[str, str, bool]:
    cfg = ConfigParser()
    for path in ["bot_config.ini", "/app/bot_config.ini"]:
        if os.path.exists(path):
            cfg.read(path)
            break
    token = cfg.get("telegram", "bot_token", fallback="")
    chat_id = str(cfg.get("telegram", "chat_id", fallback=""))
    enabled = cfg.getboolean("telegram", "enabled", fallback=True)
    return token, chat_id, enabled and bool(token and chat_id)


def _load_stake() -> float:
    cfg = ConfigParser()
    for path in ["bot_config.ini", "/app/bot_config.ini"]:
        if os.path.exists(path):
            cfg.read(path)
            break
    return float(cfg.get("manual", "stake", fallback="20.0"))


class ManualBetBot:
    """Bot Telegram com varredura manual e confirmação de aposta."""

    MAIN_KEYBOARD = {
        "keyboard": [
            [{"text": "🔍 Varredura de Apostas"}],
            [{"text": "💰 Saldo Betfair"}, {"text": "📋 Menu"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }

    def __init__(self):
        logger.info("=" * 60)
        logger.info("  Manual Bet Bot — Modo assistido")
        logger.info("=" * 60)

        self.token, self.chat_id, self.enabled = _load_telegram()
        if not self.enabled:
            raise RuntimeError("Telegram não configurado em bot_config.ini")

        self.stake = _load_stake()
        football_key, groq_key = _load_keys()

        self.betfair = BetfairAPI()
        self.betfair.login()
        self.db = BetDatabase()
        self.api_football = APIFootball(football_key)
        self.scanner = OpportunityScanner(
            self.betfair, self.api_football, groq_key, stake=self.stake
        )

        self.running = False
        self._scanning = False
        signal.signal(signal.SIGINT, self._stop)
        signal.signal(signal.SIGTERM, self._stop)

    def _stop(self, signum, frame):
        logger.info("Encerrando bot manual...")
        self.running = False

    # ─── Telegram API ─────────────────────────────────────────────────────────

    def _api(self, method: str, payload: dict) -> dict:
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        resp = requests.post(url, json=payload, timeout=30, proxies={"http": None, "https": None})
        resp.raise_for_status()
        return resp.json()

    def send(self, text: str, reply_markup: Optional[dict] = None) -> None:
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        self._api("sendMessage", payload)

    def _answer_callback(self, callback_id: str, text: str = "") -> None:
        self._api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def _load_offset(self) -> int:
        try:
            if os.path.exists(OFFSET_FILE):
                with open(OFFSET_FILE) as f:
                    return int(f.read().strip())
        except Exception:
            pass
        return 0

    def _save_offset(self, offset: int) -> None:
        os.makedirs("data", exist_ok=True)
        with open(OFFSET_FILE, "w") as f:
            f.write(str(offset))

    # ─── Handlers ─────────────────────────────────────────────────────────────

    def _handle_message(self, text: str) -> None:
        text = (text or "").strip()

        if text in ("/start", "📋 Menu", "menu", "/menu"):
            self.send(
                "⚽ <b>Bot de Apostas — Modo Manual</b>\n\n"
                "Eu <b>não aposto sozinho</b>. Só busco oportunidades quando você pedir.\n\n"
                "• <b>🔍 Varredura de Apostas</b> — busca jogos (Under 4.5, Over 1.5, Over 2.5, Favorito)\n"
                "• <b>💰 Saldo Betfair</b> — mostra saldo disponível\n\n"
                "Quando aparecer uma oportunidade, clique em <b>Apostar</b> para confirmar.",
                reply_markup=self.MAIN_KEYBOARD,
            )
            return

        if text in ("🔍 Varredura de Apostas", "/scan", "scan", "varredura"):
            self._start_scan()
            return

        if text in ("💰 Saldo Betfair", "/saldo", "saldo"):
            self._send_balance()
            return

        self.send(
            "Use os botões abaixo ou envie:\n"
            "• <code>varredura</code>\n"
            "• <code>saldo</code>",
            reply_markup=self.MAIN_KEYBOARD,
        )

    def _handle_callback(self, data: str, callback_id: str) -> None:
        if data.startswith("bet:"):
            opp_id = data.split(":", 1)[1]
            self._answer_callback(callback_id, "Processando aposta...")
            self._place_confirmed_bet(opp_id)
            return

        if data.startswith("skip:"):
            self._answer_callback(callback_id, "Oportunidade ignorada.")
            return

    def _start_scan(self) -> None:
        if self._scanning:
            self.send("⏳ Já existe uma varredura em andamento. Aguarde...")
            return

        self._scanning = True
        self.send(
            "🔍 <b>Varredura iniciada</b>\n\n"
            "Analisando mercados na Betfair (ligas principais)...\n"
            "Isso pode levar 1–3 minutos. ⏳",
            reply_markup=self.MAIN_KEYBOARD,
        )

        def run():
            try:
                opportunities = self.scanner.scan()
                if not opportunities:
                    self.send(
                        "😴 <b>Nenhuma oportunidade encontrada agora.</b>\n\n"
                        "Tente novamente mais perto do horário dos jogos das ligas principais.",
                        reply_markup=self.MAIN_KEYBOARD,
                    )
                    return

                self.send(
                    f"✅ <b>{len(opportunities)} oportunidade(s) encontrada(s)</b>\n"
                    "Revise cada uma e clique em <b>Apostar</b> se concordar.",
                    reply_markup=self.MAIN_KEYBOARD,
                )
                for opp in opportunities:
                    self._send_opportunity(opp)
            except Exception as e:
                logger.error(f"Erro na varredura: {e}", exc_info=True)
                self.send(f"❌ Erro na varredura: {e}", reply_markup=self.MAIN_KEYBOARD)
            finally:
                self._scanning = False

        threading.Thread(target=run, daemon=True).start()

    def _send_opportunity(self, opp: Opportunity) -> None:
        risk_emoji = {"baixo": "🟢", "médio": "🟡", "medio": "🟡"}.get(opp.risk, "⚪")
        kickoff = ""
        if opp.kickoff:
            try:
                kickoff = datetime.fromisoformat(opp.kickoff.replace("Z", "+00:00")).strftime("%d/%m %H:%M")
            except Exception:
                kickoff = opp.kickoff[:16]

        text = (
            f"{risk_emoji} <b>{opp.bet_type}</b>\n\n"
            f"⚽ <b>{opp.home}</b> x <b>{opp.away}</b>\n"
            f"🏆 {opp.league}\n"
        )
        if kickoff:
            text += f"🕐 Início: {kickoff}\n"
        text += (
            f"\n📊 <b>{opp.selection_label}</b> @ <b>{opp.odds:.2f}</b>\n"
            f"💵 Stake: R$ {opp.stake:.2f} → Lucro pot.: R$ {opp.potential_profit:.2f}\n"
            f"🤖 Confiança IA: <b>{opp.confidence}%</b>\n"
            f"💬 <i>{opp.reasoning}</i>"
        )

        keyboard = {
            "inline_keyboard": [[
                {"text": f"✅ Apostar R$ {opp.stake:.0f}", "callback_data": f"bet:{opp.opp_id}"},
                {"text": "❌ Ignorar", "callback_data": f"skip:{opp.opp_id}"},
            ]]
        }
        self.send(text, reply_markup=keyboard)

    def _send_balance(self) -> None:
        try:
            funds = self.betfair.get_account_funds()
            available = funds.get("availableToBetBalance", 0)
            exposure = funds.get("exposure", 0)
            self.send(
                f"💰 <b>Saldo Betfair</b>\n\n"
                f"Disponível: <b>R$ {float(available):.2f}</b>\n"
                f"Exposição: R$ {float(exposure):.2f}",
                reply_markup=self.MAIN_KEYBOARD,
            )
        except Exception as e:
            self.send(f"❌ Erro ao consultar saldo: {e}", reply_markup=self.MAIN_KEYBOARD)

    def _place_confirmed_bet(self, opp_id: str) -> None:
        opp = OpportunityScanner.load_pending(opp_id)
        if not opp:
            self.send(
                "⚠️ Oportunidade expirada ou inválida. Faça uma nova varredura.",
                reply_markup=self.MAIN_KEYBOARD,
            )
            return

        home, away = opp["home"], opp["away"]
        self.send(f"⏳ Colocando aposta em <b>{home} x {away}</b>...", reply_markup=self.MAIN_KEYBOARD)

        try:
            customer_ref = f"MAN_{uuid.uuid4().hex[:12].upper()}"
            result = self.betfair.place_orders(
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
                self.send(f"❌ Falha ao apostar: <code>{err}</code>", reply_markup=self.MAIN_KEYBOARD)
                return

            reports = result.get("instructionReports", [])
            bet_id = reports[0].get("betId", customer_ref) if reports else customer_ref

            self.send(
                f"✅ <b>Aposta confirmada!</b>\n\n"
                f"⚽ {home} x {away}\n"
                f"📊 {opp['bet_type']} @ {opp['odds']:.2f}\n"
                f"💵 Stake: R$ {opp['stake']:.2f}\n"
                f"🆔 ID: <code>{bet_id}</code>",
                reply_markup=self.MAIN_KEYBOARD,
            )
            logger.info(f"Aposta manual colocada: {bet_id} | {home} x {away}")

        except Exception as e:
            logger.error(f"Erro ao apostar: {e}", exc_info=True)
            self.send(f"❌ Erro: {e}", reply_markup=self.MAIN_KEYBOARD)

    # ─── Loop ─────────────────────────────────────────────────────────────────

    def run(self) -> None:
        self.running = True
        self.send(
            "🟢 <b>Bot Manual de Apostas online</b>\n\n"
            "Aguardando seu comando. Toque em <b>🔍 Varredura de Apostas</b> quando quiser buscar jogos.",
            reply_markup=self.MAIN_KEYBOARD,
        )
        logger.info("Bot manual aguardando comandos Telegram...")

        while self.running:
            try:
                offset = self._load_offset()
                resp = requests.get(
                    f"https://api.telegram.org/bot{self.token}/getUpdates",
                    params={"timeout": 30, "offset": offset},
                    timeout=35,
                    proxies={"http": None, "https": None},
                )
                if resp.status_code != 200:
                    time.sleep(5)
                    continue

                updates = resp.json().get("result", [])
                for update in updates:
                    self._save_offset(update["update_id"] + 1)

                    cb = update.get("callback_query")
                    if cb:
                        chat = str(cb.get("message", {}).get("chat", {}).get("id", ""))
                        if chat == self.chat_id:
                            self._handle_callback(cb.get("data", ""), cb["id"])
                        continue

                    msg = update.get("message", {})
                    chat = str(msg.get("chat", {}).get("id", ""))
                    if chat != self.chat_id:
                        continue
                    self._handle_message(msg.get("text", ""))

            except requests.exceptions.ReadTimeout:
                continue
            except Exception as e:
                logger.error(f"Erro no polling: {e}")
                time.sleep(5)

        self.send("🛑 Bot manual encerrado.", reply_markup=self.MAIN_KEYBOARD)


if __name__ == "__main__":
    bot = ManualBetBot()
    bot.run()
