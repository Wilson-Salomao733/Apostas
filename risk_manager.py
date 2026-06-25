"""Gestão de risco: apostas ativas, limites diários e dry-run."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config_loader import get_strategy_params

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
ACTIVE_BETS_FILE = ROOT / "data" / "active_bets.json"
DAILY_PL_FILE = ROOT / "data" / "daily_pl.json"


def _today() -> str:
    return date.today().isoformat()


def _load_json(path: Path, default: Any) -> Any:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def load_active_bets() -> dict:
    return _load_json(ACTIVE_BETS_FILE, {"bets": []})


def save_active_bets(store: dict) -> None:
    _save_json(ACTIVE_BETS_FILE, store)


def open_bets_count(strategy_key: str | None = None) -> int:
    store = load_active_bets()
    bets = [b for b in store.get("bets", []) if b.get("status") == "open"]
    if strategy_key:
        bets = [b for b in bets if b.get("bet_key") == strategy_key]
    return len(bets)


def load_daily_pl() -> dict:
    data = _load_json(DAILY_PL_FILE, {"date": _today(), "realized_pl": 0.0, "bets_won": 0, "bets_lost": 0})
    if data.get("date") != _today():
        data = {"date": _today(), "realized_pl": 0.0, "bets_won": 0, "bets_lost": 0}
        _save_json(DAILY_PL_FILE, data)
    return data


def get_daily_pl() -> float:
    return float(load_daily_pl().get("realized_pl", 0.0))


def record_settlement(bet: dict, profit: float) -> None:
    daily = load_daily_pl()
    daily["realized_pl"] = round(float(daily.get("realized_pl", 0)) + profit, 2)
    if profit >= 0:
        daily["bets_won"] = int(daily.get("bets_won", 0)) + 1
    else:
        daily["bets_lost"] = int(daily.get("bets_lost", 0)) + 1
    _save_json(DAILY_PL_FILE, daily)

    store = load_active_bets()
    for b in store.get("bets", []):
        if b.get("opp_id") == bet.get("opp_id"):
            b["status"] = "settled"
            b["profit"] = profit
            b["settled_at"] = datetime.now(timezone.utc).isoformat()
    save_active_bets(store)


def can_bet(opp: Any, strategy_key: str | None = None) -> tuple[bool, str]:
    """Verifica se uma aposta pode ser feita. opp pode ser Opportunity ou dict."""
    key = strategy_key or getattr(opp, "bet_key", None) or opp.get("bet_key", "under45")
    params = get_strategy_params(key)

    daily = load_daily_pl()
    pl = float(daily.get("realized_pl", 0))
    if pl <= -params["daily_loss_limit"]:
        return False, f"Limite de perda diária atingido (R$ {params['daily_loss_limit']:.0f})"
    if pl >= params["daily_profit_target"]:
        return False, f"Meta de lucro diária atingida (R$ {params['daily_profit_target']:.0f})"

    open_count = open_bets_count(key)
    if open_count >= params["max_concurrent_bets"]:
        return False, f"Máximo de apostas abertas ({params['max_concurrent_bets']})"

    store = load_active_bets()
    opp_id = getattr(opp, "opp_id", None) or opp.get("opp_id")
    market_ids = {getattr(opp, "market_id", None) or opp.get("market_id")}
    legs = getattr(opp, "legs", None) or opp.get("legs") or []
    for leg in legs:
        market_ids.add(leg.get("market_id"))
    for b in store.get("bets", []):
        if b.get("status") != "open":
            continue
        if b.get("market_id") in market_ids:
            return False, "Já existe aposta aberta neste mercado"
        for bl in b.get("legs") or []:
            if bl.get("market_id") in market_ids:
                return False, "Já existe aposta aberta neste mercado"

    return True, ""


def record_bet(opp: Any, bet_id: str, dry_run: bool = False) -> None:
    store = load_active_bets()
    stake = float(getattr(opp, "stake", None) or opp.get("stake", 20))
    legs = getattr(opp, "legs", None) or opp.get("legs") or []
    entry = {
        "opp_id": getattr(opp, "opp_id", None) or opp.get("opp_id"),
        "bet_key": getattr(opp, "bet_key", None) or opp.get("bet_key"),
        "market_id": getattr(opp, "market_id", None) or opp.get("market_id"),
        "selection_id": getattr(opp, "selection_id", None) or opp.get("selection_id"),
        "home": getattr(opp, "home", None) or opp.get("home", ""),
        "away": getattr(opp, "away", None) or opp.get("away", ""),
        "league": getattr(opp, "league", None) or opp.get("league", ""),
        "odds": float(getattr(opp, "odds", None) or opp.get("odds", 0)),
        "combined_odds": float(getattr(opp, "combined_odds", None) or opp.get("combined_odds", 0) or 0),
        "stake": stake,
        "legs": legs,
        "bet_id": bet_id,
        "status": "open",
        "placed_at": datetime.now(timezone.utc).isoformat(),
    }
    store.setdefault("bets", []).append(entry)
    save_active_bets(store)


def reconcile(betfair_api) -> int:
    """Verifica mercados fechados e atualiza P/L. Retorna quantidade liquidada."""
    store = load_active_bets()
    settled = 0
    for bet in list(store.get("bets", [])):
        if bet.get("status") != "open":
            continue
        try:
            result = betfair_api.get_market_result(bet["market_id"])
        except Exception as e:
            logger.debug(f"Reconcile skip {bet['market_id']}: {e}")
            continue
        if not result or result.get("market_status") != "CLOSED":
            continue

        sel_id = int(bet["selection_id"])
        won = False
        for runner in result.get("runners", []):
            if runner.get("selection_id") == sel_id and runner.get("result") == "WIN":
                won = True
                break

        stake = float(bet["stake"])
        odds = float(bet["odds"])
        profit = round(stake * (odds - 1) * 0.95, 2) if won else -stake
        record_settlement(bet, profit)
        settled += 1
        logger.info(
            f"Aposta liquidada: {bet['home']} x {bet['away']} → "
            f"{'WIN' if won else 'LOSE'} R$ {profit:+.2f}"
        )
    return settled


def status_summary() -> str:
    daily = load_daily_pl()
    open_n = open_bets_count()
    return (
        f"P/L hoje: R$ {daily.get('realized_pl', 0):+.2f}\n"
        f"Ganhas/Perdidas: {daily.get('bets_won', 0)}/{daily.get('bets_lost', 0)}\n"
        f"Apostas abertas: {open_n}"
    )
