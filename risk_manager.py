"""Gestão de risco: apostas ativas, limites diários e dry-run."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from bet_ledger import daily_exposure_and_profit, settle_order_from_cleared
from combo_definitions import COMBO_DEFINITIONS, SINGLE_DEFINITIONS, resolve_combo_key
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


def _opp_field(opp: Any, key: str, default: Any = None) -> Any:
    if isinstance(opp, dict):
        return opp.get(key, default)
    return getattr(opp, key, default)


def _opportunity_exposure(opp: Any) -> float:
    explicit = _opp_field(opp, "leg_stakes") or []
    if explicit:
        return round(sum(float(value) for value in explicit), 2)
    legs = _opp_field(opp, "legs") or []
    leg_values = [leg.get("stake") for leg in legs]
    if legs and all(value is not None for value in leg_values):
        return round(sum(float(value) for value in leg_values), 2)
    return float(_opp_field(opp, "stake", 0) or 0)


def can_bet(opp: Any, strategy_key: str | None = None) -> tuple[bool, str]:
    """Verifica se uma aposta pode ser feita. opp pode ser Opportunity ou dict."""
    key = resolve_combo_key(
        strategy_key
        or _opp_field(opp, "bet_key")
        or "combo_u105_u45"
    )
    if key not in COMBO_DEFINITIONS and key not in SINGLE_DEFINITIONS:
        key = "combo_u105_u45"
    params = get_strategy_params(key)
    model_probability = _opp_field(opp, "model_probability")
    ev_pct = _opp_field(opp, "ev_pct")
    price_band = bool(params.get("authorize_on_price_band")) or key == "corners_105"
    if not price_band:
        if model_probability is None or ev_pct is None:
            return False, "Sem avaliação determinística de probabilidade/EV"
        if float(ev_pct) < float(params.get("min_ev_pct", 2.0)):
            return False, f"EV abaixo do mínimo ({params.get('min_ev_pct', 2.0):.1f}%)"

    daily = load_daily_pl()
    pl = float(daily.get("realized_pl", 0))
    if pl <= -params["daily_loss_limit"]:
        return False, f"Limite de perda diária atingido (R$ {params['daily_loss_limit']:.0f})"
    if pl >= params["daily_profit_target"]:
        return False, f"Meta de lucro diária atingida (R$ {params['daily_profit_target']:.0f})"

    open_count = open_bets_count(key)
    if key == "corners_105":
        open_count += open_bets_count("corners_under_105")
    if key == "combo_u45_u105":
        open_count += open_bets_count("under45")  # fallback conta junto
    if key == "combo_u105_u45":
        open_count += open_bets_count("corners_105")
        open_count += open_bets_count("under45")
    if open_count >= params["max_concurrent_bets"]:
        return False, f"Máximo de apostas abertas ({params['max_concurrent_bets']})"

    store = load_active_bets()
    open_bets = [bet for bet in store.get("bets", []) if bet.get("status") == "open"]
    total_exposure = sum(float(bet.get("stake", 0) or 0) for bet in open_bets)
    new_stake = _opportunity_exposure(opp)
    if pl - total_exposure - new_stake < -float(params["daily_loss_limit"]):
        return False, f"Risco aberto excederia a perda diária de R$ {params['daily_loss_limit']:.0f}"
    if total_exposure + new_stake > float(params.get("max_total_exposure", 8.0)):
        return False, "Exposição total máxima atingida"
    event_id = str(_opp_field(opp, "event_id", "") or "")
    event_name = (
        str(_opp_field(opp, "home", "")),
        str(_opp_field(opp, "away", "")),
    )
    event_exposure = sum(
        float(bet.get("stake", 0) or 0)
        for bet in open_bets
        if (
            event_id
            and str(bet.get("event_id", "")) == event_id
        ) or (
            not event_id
            and (str(bet.get("home", "")), str(bet.get("away", ""))) == event_name
        )
    )
    if event_exposure + new_stake > float(params.get("max_event_exposure", 4.0)):
        return False, "Exposição máxima por evento atingida"

    opp_id = _opp_field(opp, "opp_id")
    market_ids = {_opp_field(opp, "market_id")}
    legs = _opp_field(opp, "legs") or []
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


def record_bet(
    opp: Any,
    bet_id: str,
    dry_run: bool = False,
    leg_stakes: list[float] | None = None,
) -> None:
    store = load_active_bets()
    stake = _opportunity_exposure(opp)
    legs = [dict(leg) for leg in (_opp_field(opp, "legs") or [])]
    bet_ids = [value for value in str(bet_id).split(",") if value]
    if not legs:
        legs = [{
            "market_id": _opp_field(opp, "market_id"),
            "selection_id": _opp_field(opp, "selection_id"),
            "odds": float(_opp_field(opp, "odds", 0) or 0),
        }]
    stakes = leg_stakes or [stake / len(legs)] * len(legs)
    stake = round(sum(float(value) for value in stakes), 2)
    for index, leg in enumerate(legs):
        leg["bet_id"] = bet_ids[index] if index < len(bet_ids) else ""
        leg["stake"] = round(float(stakes[index]), 2)
    entry = {
        "opp_id": _opp_field(opp, "opp_id"),
        "bet_key": _opp_field(opp, "bet_key"),
        "market_id": _opp_field(opp, "market_id"),
        "selection_id": _opp_field(opp, "selection_id"),
        "event_id": _opp_field(opp, "event_id", ""),
        "home": _opp_field(opp, "home", ""),
        "away": _opp_field(opp, "away", ""),
        "league": _opp_field(opp, "league", ""),
        "odds": float(_opp_field(opp, "odds", 0) or 0),
        "combined_odds": float(_opp_field(opp, "combined_odds", 0) or 0),
        "stake": stake,
        "legs": legs,
        "leg_stakes": [round(float(value), 2) for value in stakes],
        "bet_id": bet_id,
        "status": "open",
        "placed_at": datetime.now(timezone.utc).isoformat(),
    }
    store.setdefault("bets", []).append(entry)
    save_active_bets(store)


def reconcile(betfair_api) -> int:
    """Liquida por bet ID usando o profit real de todas as pernas."""
    store = load_active_bets()
    settled = 0
    for bet in list(store.get("bets", [])):
        if bet.get("status") != "open":
            continue
        bet_ids = [value for value in str(bet.get("bet_id", "")).split(",") if value]
        if bet_ids and all(not value.startswith(("BOT_", "TG_")) for value in bet_ids):
            try:
                result = betfair_api.list_cleared_orders_all(
                    bet_ids=bet_ids,
                    bet_status="SETTLED",
                )
                cleared = result.get("clearedOrders", [])
                cleared_ids = {str(item.get("betId")) for item in cleared}
                if all(value in cleared_ids for value in bet_ids):
                    profit = round(sum(float(item.get("profit", 0) or 0) for item in cleared), 2)
                    settle_order_from_cleared(bet_ids, cleared)
                    record_settlement(bet, profit)
                    settled += 1
                    logger.info(
                        "Aposta liquidada pela API: %s x %s → R$ %+.2f",
                        bet.get("home", ""), bet.get("away", ""), profit,
                    )
                    continue
            except Exception as exc:
                logger.debug("Cleared orders indisponível para %s: %s", bet_ids, exc)

        # Compatibilidade com registros antigos sem betId real: apenas apostas simples.
        if len(bet.get("legs") or []) > 1:
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
    exposure, ledger_profit = daily_exposure_and_profit()
    return (
        f"P/L hoje: R$ {daily.get('realized_pl', 0):+.2f}\n"
        f"P/L ledger: R$ {ledger_profit:+.2f}\n"
        f"Exposição aberta: R$ {exposure:.2f}\n"
        f"Ganhas/Perdidas: {daily.get('bets_won', 0)}/{daily.get('bets_lost', 0)}\n"
        f"Apostas abertas: {open_n}"
    )
