"""Worker em background: varredura automática semi/full."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from api_football import APIFootball
from bet_placement import place_opportunity
from betfair_api import BetfairAPI
from config_loader import (
    get_active_strategy,
    get_api_keys,
    get_check_interval,
    get_daily_scan_config,
    get_manual_stake,
    load_mode,
)
from opportunity_scanner import Opportunity, OpportunityScanner
from risk_manager import can_bet, reconcile

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent
DAILY_SCAN_STATE_FILE = ROOT / "data" / "daily_market_scan.json"


class AutoWorker:
    def __init__(
        self,
        betfair: BetfairAPI,
        on_notify: Callable[[str, Optional[dict]], None],
        on_opportunity_semi: Callable[[Opportunity], None],
    ):
        self.betfair = betfair
        self.on_notify = on_notify
        self.on_opportunity_semi = on_opportunity_semi
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._notified_ids: set[str] = set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="auto-worker")
        self._thread.start()
        logger.info("Auto-worker iniciado")

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            mode = load_mode()
            if mode in ("semi", "auto"):
                try:
                    self._run_cycle(mode)
                    self._maybe_run_daily_scan(mode)
                except Exception as e:
                    logger.error(f"Erro no ciclo automático: {e}")
                    self.on_notify(f"❌ Erro no worker: {e}", None)
            interval = max(30, get_check_interval())
            self._stop.wait(interval)

    def _run_cycle(self, mode: str) -> None:
        try:
            reconcile(self.betfair)
        except Exception as e:
            logger.warning(f"Reconcile falhou: {e}")

        fk, gk = get_api_keys()
        # Auto: filtros estritos. Semi: filtros relaxados (só notifica).
        scanner = OpportunityScanner(
            self.betfair,
            APIFootball(fk),
            gk,
            stake=get_manual_stake(),
            active_strategy=get_active_strategy(),
            filter_mode=mode,
        )
        opps = scanner.scan()
        stats = scanner.last_stats
        logger.info(f"Ciclo {mode}: {len(opps)} opp(s) | filtros={mode} | stats={stats}")

        for opp in opps:
            if opp.opp_id in self._notified_ids and mode == "semi":
                continue
            if "⚠️" in opp.bet_type:
                continue

            ok, reason = can_bet(opp)
            if not ok:
                logger.info(f"Skip {opp.home} x {opp.away}: {reason}")
                continue

            if mode == "semi":
                self._notified_ids.add(opp.opp_id)
                self.on_opportunity_semi(opp)
            else:
                self._place_auto(opp)

        if len(self._notified_ids) > 200:
            self._notified_ids.clear()

    def _place_auto(self, opp: Opportunity) -> None:
        ok, msg = place_opportunity(self.betfair, opp.to_dict(), ref_prefix="BOT")
        self.on_notify(msg, None)

    def _maybe_run_daily_scan(self, mode: str) -> None:
        if mode != "auto":
            return
        cfg = get_daily_scan_config()
        if not cfg["enabled"]:
            return

        now = datetime.now()
        hour, minute = self._parse_daily_scan_time(str(cfg["time"]))
        scheduled_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        today = now.date().isoformat()
        state = self._load_daily_scan_state()

        if state.get("last_run_date") == today or now < scheduled_at:
            return

        self._save_daily_scan_state({
            "last_run_date": today,
            "started_at": now.isoformat(timespec="seconds"),
            "strategy": cfg["strategy"],
        })
        self._run_daily_scan(str(cfg["strategy"]), bool(cfg["send_empty"]))

    @staticmethod
    def _parse_daily_scan_time(value: str) -> tuple[int, int]:
        try:
            hour_s, minute_s = value.strip().split(":", 1)
            hour = min(max(int(hour_s), 0), 23)
            minute = min(max(int(minute_s), 0), 59)
            return hour, minute
        except Exception:
            return 9, 0

    @staticmethod
    def _load_daily_scan_state() -> dict:
        try:
            if DAILY_SCAN_STATE_FILE.exists():
                return json.loads(DAILY_SCAN_STATE_FILE.read_text())
        except Exception:
            pass
        return {}

    @staticmethod
    def _save_daily_scan_state(data: dict) -> None:
        DAILY_SCAN_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        DAILY_SCAN_STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _run_daily_scan(self, strategy: str, send_empty: bool) -> None:
        self.on_notify(
            "🔎 <b>Varredura diária iniciada</b>\n"
            "Modo auto continua ativo. Vou enviar oportunidades para confirmação manual.",
            None,
        )

        fk, gk = get_api_keys()
        scanner = OpportunityScanner(
            self.betfair,
            APIFootball(fk),
            gk,
            stake=get_manual_stake(),
            active_strategy=strategy,
            filter_mode="semi",
        )
        opps = scanner.scan()
        stats = scanner.last_stats
        sent = 0

        for opp in opps:
            if "⚠️" in opp.bet_type:
                continue
            ok, reason = can_bet(opp)
            if not ok:
                logger.info(f"Varredura diária skip {opp.home} x {opp.away}: {reason}")
                continue
            self._notified_ids.add(opp.opp_id)
            self.on_opportunity_semi(opp)
            sent += 1

        if sent:
            self.on_notify(
                f"✅ <b>Varredura diária concluída</b>\n"
                f"{sent} oportunidade(s) enviada(s) para análise manual.",
                None,
            )
            return

        if send_empty:
            markets = stats.get("markets_total", 0)
            self.on_notify(
                "😴 <b>Varredura diária concluída</b>\n"
                f"Nenhuma oportunidade aprovada. Mercados analisados: ~{markets}",
                None,
            )

    def run_scan_once(self) -> tuple[list[Opportunity], dict]:
        """Varredura manual sob demanda — filtros relaxados (como semi)."""
        fk, gk = get_api_keys()
        scanner = OpportunityScanner(
            self.betfair,
            APIFootball(fk),
            gk,
            stake=get_manual_stake(),
            active_strategy=get_active_strategy(),
            filter_mode="manual",
        )
        return scanner.scan(), scanner.last_stats
