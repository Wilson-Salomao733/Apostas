"""Worker em background: varredura automática semi/full."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from api_football import APIFootball
from bet_placement import place_opportunity
from betfair_api import BetfairAPI
from config_loader import (
    get_active_strategy,
    get_api_keys,
    get_check_interval,
    get_manual_stake,
    load_enabled_sports,
    load_mode,
)
from opportunity_scanner import Opportunity, OpportunityScanner
from risk_manager import can_bet, reconcile

logger = logging.getLogger(__name__)


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
        strategy = get_active_strategy()
        sports = load_enabled_sports()
        stake = get_manual_stake()
        scanner = OpportunityScanner(
            self.betfair,
            APIFootball(fk),
            gk,
            stake=stake,
            active_strategy=strategy,
            enabled_sports=sports,
        )
        opps = scanner.scan()
        stats = scanner.last_stats
        logger.info(f"Ciclo {mode}: {len(opps)} opp(s) | stats={stats}")

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

    def run_scan_once(self) -> tuple[list[Opportunity], dict]:
        """Varredura manual sob demanda."""
        fk, gk = get_api_keys()
        scanner = OpportunityScanner(
            self.betfair,
            APIFootball(fk),
            gk,
            stake=get_manual_stake(),
            active_strategy=get_active_strategy(),
            enabled_sports=load_enabled_sports(),
        )
        opps = scanner.scan()
        return opps, scanner.last_stats
