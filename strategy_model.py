"""Modelo determinístico de execução, probabilidade e valor esperado."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionQuality:
    allowed: bool
    reason: str
    back_price: float = 0.0
    back_size: float = 0.0
    lay_price: float = 0.0
    lay_size: float = 0.0
    spread_pct: float = 0.0


def execution_quality(
    book: dict,
    selection_id: int,
    stake: float,
    max_spread_pct: float = 10.0,
    min_back_size: float = 10.0,
) -> ExecutionQuality:
    """Valida se há uma oferta executável; totalMatched não é requisito."""
    if book.get("status") != "OPEN":
        return ExecutionQuality(False, "market_not_open")
    if book.get("complete") is False:
        return ExecutionQuality(False, "incomplete_book")
    runner = next(
        (item for item in book.get("runners", []) if item.get("selectionId") == selection_id),
        None,
    )
    if not runner or runner.get("status") != "ACTIVE":
        return ExecutionQuality(False, "runner_not_active")
    backs = runner.get("ex", {}).get("availableToBack", [])
    lays = runner.get("ex", {}).get("availableToLay", [])
    if not backs:
        return ExecutionQuality(False, "no_back_offer")
    back_price = float(backs[0].get("price", 0) or 0)
    back_size = float(backs[0].get("size", 0) or 0)
    lay_price = float(lays[0].get("price", 0) or 0) if lays else 0.0
    lay_size = float(lays[0].get("size", 0) or 0) if lays else 0.0
    if back_price <= 1.01 or back_price >= 1000:
        return ExecutionQuality(False, "aberrant_price", back_price, back_size, lay_price, lay_size)
    required_size = max(float(min_back_size), float(stake) * 2)
    if back_size < required_size:
        return ExecutionQuality(False, "insufficient_back_size", back_price, back_size, lay_price, lay_size)
    if lay_price <= back_price:
        return ExecutionQuality(False, "no_valid_lay", back_price, back_size, lay_price, lay_size)
    spread = ((lay_price - back_price) / back_price) * 100
    if spread > float(max_spread_pct):
        return ExecutionQuality(
            False, "spread_too_wide", back_price, back_size, lay_price, lay_size, spread
        )
    return ExecutionQuality(
        True, "ok", back_price, back_size, lay_price, lay_size, spread
    )


def break_even_probability(odds: float, commission_rate: float = 0.065) -> float:
    """Probabilidade mínima para EV zero, com comissão apenas no ganho."""
    net_win = max(0.0, (float(odds) - 1) * (1 - float(commission_rate)))
    return 1 / (1 + net_win) if net_win else 1.0


def expected_value_pct(
    odds: float,
    probability: float,
    commission_rate: float = 0.065,
) -> float:
    net_win = (float(odds) - 1) * (1 - float(commission_rate))
    return 100 * (float(probability) * net_win - (1 - float(probability)))


def poisson_under_probability(expected_total: float, maximum: int) -> float:
    expected = max(0.05, float(expected_total))
    term = math.exp(-expected)
    cumulative = term
    for value in range(1, int(maximum) + 1):
        term *= expected / value
        cumulative += term
    return min(max(cumulative, 0.0), 1.0)


def market_fair_probability(book: dict, selection_id: int) -> float | None:
    """Probabilidade sem margem a partir do midpoint BACK/LAY dos runners."""
    probabilities: dict[int, float] = {}
    for runner in book.get("runners", []):
        backs = runner.get("ex", {}).get("availableToBack", [])
        lays = runner.get("ex", {}).get("availableToLay", [])
        if not backs or not lays:
            continue
        back = float(backs[0].get("price", 0) or 0)
        lay = float(lays[0].get("price", 0) or 0)
        if back <= 1.01 or lay <= back or lay >= 1000:
            continue
        midpoint = (back + lay) / 2
        probabilities[int(runner.get("selectionId", 0))] = 1 / midpoint
    total = sum(probabilities.values())
    if total <= 0 or int(selection_id) not in probabilities:
        return None
    return probabilities[int(selection_id)] / total


def _goals_expectation(home: dict, away: dict) -> float | None:
    values = [
        float(home.get("avg_scored_total") or 0),
        float(home.get("avg_conceded_total") or 0),
        float(away.get("avg_scored_total") or 0),
        float(away.get("avg_conceded_total") or 0),
    ]
    positive = [value for value in values if value > 0]
    return sum(positive) / 2 if len(positive) == 4 else None


def _corners_expectation(corners: dict) -> float | None:
    home = corners.get("home") or {}
    away = corners.get("away") or {}
    values = [float(home.get("avg_total") or 0), float(away.get("avg_total") or 0)]
    return sum(values) / 2 if all(value > 0 for value in values) else None


def assess_value(
    profile: dict[str, Any],
    odds: float,
    book: dict,
    selection_id: int,
    home_stats: dict,
    away_stats: dict,
    corner_stats: dict,
) -> dict[str, Any]:
    """Avalia valor sem LLM. Sem modelo independente, recomenda observar."""
    commission = float(profile.get("commission_rate", 0.065))
    market_probability = market_fair_probability(book, selection_id)
    key = str(profile.get("model_key") or profile.get("key", ""))
    market_type = str(profile.get("market_type", ""))
    model_probability = None
    source = "market_midpoint"

    if "corner" in key or "CORNR" in market_type:
        expectation = _corners_expectation(corner_stats)
        if expectation is not None:
            model_probability = poisson_under_probability(expectation, 10)
            source = f"poisson_corners_lambda_{expectation:.2f}"
    elif key == "under45" or market_type == "OVER_UNDER_45":
        expectation = _goals_expectation(home_stats, away_stats)
        if expectation is not None:
            model_probability = poisson_under_probability(expectation, 4)
            source = f"poisson_goals_lambda_{expectation:.2f}"

    if model_probability is None:
        model_probability = market_probability

    if model_probability is None:
        return {
            "confidence": 0,
            "recommend": False,
            "reasoning": "Sem probabilidade independente nem midpoint confiável.",
            "model_probability": None,
            "market_probability": None,
            "ev_pct": None,
            "source": source,
        }

    ev_pct = expected_value_pct(odds, model_probability, commission)
    edge_pct = 100 * (
        model_probability - break_even_probability(odds, commission)
    )
    has_independent_model = source != "market_midpoint"
    min_ev = float(profile.get("min_ev_pct", 2.0))
    min_edge = float(profile.get("min_probability_edge_pct", 2.0))
    price_band = bool(profile.get("authorize_on_price_band"))
    recommend = price_band or (
        has_independent_model and ev_pct >= min_ev and edge_pct >= min_edge
    )
    return {
        "confidence": round(model_probability * 100),
        "recommend": recommend,
        "reasoning": (
            f"Modelo {source}; p={model_probability:.1%}, "
            f"equilíbrio={break_even_probability(odds, commission):.1%}, "
            f"EV={ev_pct:+.1f}%."
            + (
                " Autorizado pela faixa de odd/spread."
                if price_band
                else "" if has_independent_model else " Mercado observado, sem edge independente."
            )
        ),
        "model_probability": model_probability,
        "market_probability": market_probability,
        "ev_pct": ev_pct,
        "edge_pct": edge_pct,
        "source": source,
    }
