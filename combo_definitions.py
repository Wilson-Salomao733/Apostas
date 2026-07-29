"""Definições — foco único: Menos de 10.5 escanteios."""

from __future__ import annotations

from typing import Any

LEG_TEMPLATES: dict[str, dict[str, Any]] = {
    "corners_under_105": {
        "key": "corners_under_105",
        "market_type": "OVER_UNDER_105_CORNR",
        "selection_hint": "under",
        "min_odds": 1.20,
        "max_odds": 2.50,
    },
}

# Sem múltiplas — só escanteios
COMBO_DEFINITIONS: dict[str, dict[str, Any]] = {}
ALL_COMBO_KEYS: tuple[str, ...] = ()

SINGLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "corners_105": {
        "key": "corners_105",
        "kind": "single",
        "label": "Menos 10.5 escanteios",
        "market_type": "OVER_UNDER_105_CORNR",
        "selection_hint": "under",
        "min_odds": 1.20,
        "max_odds": 2.50,
        "min_confidence": 58,
        "min_volume": 100,
        "good_league_only": False,
        "require_stats": False,
        "config_section": "corners_105",
        "prompt_goal": "Menos de 10.5 escanteios no jogo (máximo 10 escanteios).",
        "risk": "médio",
        "stake": 20.0,
        "max_concurrent_bets": 5,
        "daily_loss_limit": 80.0,
        "daily_profit_target": 100.0,
    },
}

ALL_SINGLE_KEYS: tuple[str, ...] = tuple(SINGLE_DEFINITIONS.keys())

SEMI_FILTER_RELAXATION: dict[str, Any] = {
    "min_volume": 50,
    "min_confidence": 55,
    "single_min_volume": 50,
}

COMBO_ALIASES = {
    "combo_u45_u105": "corners_105",
    "combo_u45_u85": "corners_105",
    "combo_u45_o85": "corners_105",
    "all_combos": "corners_105",
    "under45": "corners_105",
    "u45": "corners_105",
    "u105": "corners_105",
    "corners_under_105": "corners_105",
}


def resolve_combo_key(key: str) -> str:
    return COMBO_ALIASES.get(key, key)


def is_single_strategy(key: str) -> bool:
    return resolve_combo_key(key) in SINGLE_DEFINITIONS


def is_combo_strategy(key: str) -> bool:
    return resolve_combo_key(key) in COMBO_DEFINITIONS


def leg_profile(leg_key: str) -> dict[str, Any]:
    if leg_key not in LEG_TEMPLATES:
        raise KeyError(f"Perna desconhecida: {leg_key}")
    return dict(LEG_TEMPLATES[leg_key])
