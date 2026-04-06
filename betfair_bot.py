#!/usr/bin/env python3
"""
Smart Goals Bot — Multi-estratégia
Estratégias disponíveis:
  over15   → Over 1.5 Gols (win rate ~72-78%)
  favorite → Apostar no favorito, mercado MATCH_ODDS (win rate ~62-70%)
  over25   → Over 2.5 Gols + IA (estratégia original)

Troca de estratégia:
  • Via Telegram: envie "estratégia 1" ou "estratégia 2"
  • Via Dashboard: POST /api/strategy {"strategy": "over15"}
  • Via arquivo:   escreva o nome em data/active_strategy.txt
"""

import logging
import os
import signal
import sys
import time
from configparser import ConfigParser
from datetime import datetime

from api_football import APIFootball
from betfair_api import BetfairAPI
from database import BetDatabase
from groq_analyzer import GroqAnalyzer
from strategy_over15 import StrategyOver15
from strategy_favorite import StrategyFavorite
from strategy_over25 import StrategyOver25
from strategy_under_max import StrategyUnderMax
from strategy_under45 import StrategyUnder45
from telegram_notifier import TelegramNotifier

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
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ─── Chaves de API ────────────────────────────────────────────────────────────
# Prioridade: variável de ambiente → bot_config.ini → vazio
def _load_api_keys() -> tuple:
    football_key = os.getenv("API_FOOTBALL_KEY", "")
    groq_key     = os.getenv("GROQ_API_KEY", "")

    if not football_key or not groq_key:
        _cfg = ConfigParser()
        for path in ["bot_config.ini", "/app/bot_config.ini"]:
            if os.path.exists(path):
                _cfg.read(path)
                break
        if not football_key:
            football_key = _cfg.get("api_keys", "api_football_key", fallback="")
        if not groq_key:
            groq_key = _cfg.get("api_keys", "groq_api_key", fallback="")

    if not football_key:
        logger.warning("⚠️  API_FOOTBALL_KEY não encontrada. Stats não disponíveis.")
    if not groq_key:
        logger.error("❌  GROQ_API_KEY não encontrada. Bot não conseguirá analisar jogos.")

    return football_key, groq_key

API_FOOTBALL_KEY, GROQ_API_KEY = _load_api_keys()

STRATEGY_FILE = "data/active_strategy.txt"

STRATEGY_LABELS = {
    "over15":     "Estratégia 1 — Over 1.5 Gols",
    "favorite":   "Estratégia 2 — Favorito (Match Odds)",
    "under_max":  "Estratégia 3 — Under Máximo",
    "under45":    "Estratégia 4 — Under 4.5 Fixo (1.25–1.45)",
    "over25":     "Estratégia Over 2.5 + IA",
}


def _read_strategy_file() -> str:
    try:
        if os.path.exists(STRATEGY_FILE):
            with open(STRATEGY_FILE) as f:
                return f.read().strip()
    except Exception:
        pass
    return "over15"


def _write_strategy_file(name: str):
    os.makedirs("data", exist_ok=True)
    with open(STRATEGY_FILE, "w") as f:
        f.write(name)


class SmartGoalsBot:
    """Bot principal com suporte a múltiplas estratégias e troca dinâmica."""

    def __init__(self, config_file: str = "config.ini", bot_config_file: str = "bot_config.ini"):
        logger.info("=" * 60)
        logger.info("  Smart Goals Bot — Multi-Estratégia")
        logger.info("=" * 60)

        self.config_file     = config_file
        self.bot_config_file = bot_config_file

        self.config = ConfigParser()
        self.config.read(config_file)
        self.bot_config = ConfigParser()
        self.bot_config.read(bot_config_file)

        self.check_interval = int(self.bot_config.get("bot", "check_interval", fallback="120"))
        self.running = False

        # Componentes compartilhados entre estratégias
        logger.info("Inicializando API Betfair...")
        self.betfair = BetfairAPI(config_file)
        self.betfair.login()

        logger.info("Inicializando banco de dados...")
        self.db = BetDatabase()

        logger.info("Inicializando Telegram...")
        try:
            self.telegram = TelegramNotifier(bot_config_file)
        except Exception:
            self.telegram = None

        logger.info("Inicializando API-Football...")
        self.api_football = APIFootball(API_FOOTBALL_KEY)
        remaining = self.api_football.get_requests_remaining()
        logger.info(f"Requisições API-Football disponíveis hoje: {remaining}/95")

        logger.info("Inicializando Groq AI...")
        self.groq = GroqAnalyzer(GROQ_API_KEY, min_confidence=65)

        # Carregar estratégia inicial
        self._active_strategy_name = _read_strategy_file()
        self.strategy = self._build_strategy(self._active_strategy_name)

        # Sinais de parada
        signal.signal(signal.SIGINT,  self._handle_stop)
        signal.signal(signal.SIGTERM, self._handle_stop)

        logger.info("Bot inicializado com sucesso!")
        self._notify_start()

    # ─── Construção de estratégias ────────────────────────────────────────────

    def _build_strategy(self, name: str):
        """Instancia a estratégia pelo nome."""
        name = name.strip().lower()

        # Recarrega bot_config para pegar valores atualizados
        self.bot_config = ConfigParser()
        self.bot_config.read(self.bot_config_file)

        if name == "over15":
            logger.info("📊 Estratégia carregada: Over 1.5 Gols")
            return StrategyOver15(
                betfair_api=self.betfair, api_football=self.api_football,
                groq_analyzer=self.groq, config=self.bot_config,
                db=self.db, telegram=self.telegram,
            )
        elif name == "favorite":
            logger.info("📊 Estratégia carregada: Favorito (Match Odds)")
            return StrategyFavorite(
                betfair_api=self.betfair, api_football=self.api_football,
                groq_analyzer=self.groq, config=self.bot_config,
                db=self.db, telegram=self.telegram,
            )
        elif name == "under_max":
            logger.info("📊 Estratégia carregada: Under Máximo")
            return StrategyUnderMax(
                betfair_api=self.betfair, api_football=self.api_football,
                groq_analyzer=self.groq, config=self.bot_config,
                db=self.db, telegram=self.telegram,
            )
        elif name == "under45":
            logger.info("📊 Estratégia carregada: Under 4.5 Fixo")
            return StrategyUnder45(
                betfair_api=self.betfair, api_football=self.api_football,
                groq_analyzer=self.groq, config=self.bot_config,
                db=self.db, telegram=self.telegram,
            )
        else:  # over25 ou padrão
            logger.info("📊 Estratégia carregada: Over 2.5 + IA")
            return StrategyOver25(
                betfair_api=self.betfair, api_football=self.api_football,
                groq_analyzer=self.groq, config=self.bot_config,
                db=self.db, telegram=self.telegram,
            )

    def _switch_strategy(self, new_name: str):
        """Troca a estratégia em tempo real."""
        if new_name == self._active_strategy_name:
            return

        old_label = STRATEGY_LABELS.get(self._active_strategy_name, self._active_strategy_name)
        new_label = STRATEGY_LABELS.get(new_name, new_name)

        logger.info(f"🔄 Trocando estratégia: {old_label} → {new_label}")
        _write_strategy_file(new_name)
        self._active_strategy_name = new_name
        self.strategy = self._build_strategy(new_name)

        if self.telegram and self.telegram.enabled:
            self.telegram.send_message(
                f"🔄 <b>Estratégia trocada!</b>\n\n"
                f"❌ Anterior: {old_label}\n"
                f"✅ Atual: <b>{new_label}</b>\n"
                f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            )

    # ─── Loop principal ───────────────────────────────────────────────────────

    def _handle_stop(self, signum, frame):
        logger.info("Sinal de parada recebido. Encerrando...")
        self.running = False

    def _notify_start(self):
        if not self.telegram or not self.telegram.enabled:
            return
        label = STRATEGY_LABELS.get(self._active_strategy_name, self._active_strategy_name)
        self.telegram.send_message(
            f"🤖 <b>Smart Goals Bot INICIADO</b>\n\n"
            f"📊 Estratégia: <b>{label}</b>\n"
            f"⏰ Intervalo: {self.check_interval}s\n"
            f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
            f"Comandos disponíveis:\n"
            f"• <code>estratégia 1</code> → Over 1.5 Gols\n"
            f"• <code>estratégia 2</code> → Favorito\n"
            f"• <code>estratégia 3</code> → Under Máximo\n"
            f"• <code>estratégia 4</code> → Under 4.5 Fixo\n"
            f"• <code>status</code> → Ver estado atual"
        )

    def run(self):
        self.running = True
        label = STRATEGY_LABELS.get(self._active_strategy_name, self._active_strategy_name)
        logger.info(f"Bot rodando | Estratégia: {label} | Ciclo: {self.check_interval}s")

        cycle_count = 0
        while self.running:
            try:
                cycle_count += 1
                logger.info(
                    f"─── Ciclo #{cycle_count} | {datetime.now().strftime('%H:%M:%S')} "
                    f"| [{STRATEGY_LABELS.get(self._active_strategy_name, self._active_strategy_name)}] ───"
                )

                # 1. Verificar comandos Telegram
                if self.telegram:
                    new_strat = self.telegram.check_commands()
                    if new_strat:
                        self._switch_strategy(new_strat)

                # 2. Verificar arquivo de estratégia (mudança via dashboard)
                file_strat = _read_strategy_file()
                if file_strat != self._active_strategy_name:
                    self._switch_strategy(file_strat)

                # 3. Executar ciclo da estratégia ativa
                self.strategy.run_cycle()

                # 4. Log de status a cada 10 ciclos
                if cycle_count % 10 == 0:
                    status = self.strategy.get_status()
                    logger.info(
                        f"STATUS | [{status.get('strategy_label','?')}] "
                        f"Ativas: {status['active_bets']} | "
                        f"Hoje: {status['bets_today']} apostas | "
                        f"P&L: R${status['net_today']:+.2f} | "
                        f"API: {status['api_requests_remaining']}/95"
                    )

                time.sleep(self.check_interval)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Erro inesperado no ciclo: {e}", exc_info=True)
                time.sleep(30)

        self._shutdown()

    def _shutdown(self):
        try:
            status = self.strategy.get_status()
            logger.info("=" * 60)
            logger.info("Bot encerrado.")
            logger.info(f"  Apostas: {status['bets_today']}")
            logger.info(f"  P&L: R${status['net_today']:+.2f}")
            logger.info("=" * 60)

            if self.telegram and self.telegram.enabled:
                self.telegram.send_message(
                    f"🛑 <b>Bot ENCERRADO</b>\n\n"
                    f"📊 Estratégia: {status.get('strategy_label','?')}\n"
                    f"🎯 Apostas hoje: {status['bets_today']}\n"
                    f"💰 Resultado: R${status['net_today']:+.2f}"
                )
        except Exception as e:
            logger.error(f"Erro no shutdown: {e}")


if __name__ == "__main__":
    bot = SmartGoalsBot()
    bot.run()
