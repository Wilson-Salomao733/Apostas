"""Definições — foco único: Menos 4.5 gols + Menos 10.5 escanteios."""

from __future__ import annotations

from typing import Any

# Pernas do combo padrão
LEG_TEMPLATES: dict[str, dict[str, Any]] = {
    "under45": {
        "key": "under45",
        "market_type": "OVER_UNDER_45",
        "selection_hint": "under",
        "min_odds": 1.15,
        "max_odds": 1.50,
    },
    "corners_under_105": {
        "key": "corners_under_105",
        "market_type": "OVER_UNDER_105_CORNR",
        "selection_hint": "under",
        "min_odds": 1.20,
        "max_odds": 2.40,
    },
}

COMBO_DEFINITIONS: dict[str, dict[str, Any]] = {
    "combo_u45_u105": {
        "key": "combo_u45_u105",
        "label": "Menos 4.5 gols + Menos 10.5 esc",
        "leg1": "under45",
        "leg2": "corners_under_105",
        "leg1_short": "U4.5 gols",
        "leg2_short": "U10.5 esc",
        "ia_hint": (
            "Jogo tranquilo: poucos gols (máx. 4) e poucos escanteios (máx. 10). "
            "As duas condições precisam bater."
        ),
        "needs_corners_stats": True,
        "config_section": "combo_u45_u105",
        "good_league_only": False,
        "min_volume": 300,
        "min_volume_leg2": 100,
        "min_combined_odds": 1.40,
        "max_combined_odds": 3.50,
        "leg1_min_odds": 1.15,
        "leg2_min_odds": 1.20,
        "leg2_stake_ratio": 0.50,
        "min_confidence": 60,
    },
}

ALL_COMBO_KEYS: tuple[str, ...] = tuple(COMBO_DEFINITIONS.keys())

# Sem apostas simples — só a múltipla U4.5 + U10.5
SINGLE_DEFINITIONS: dict[str, dict[str, Any]] = {}
ALL_SINGLE_KEYS: tuple[str, ...] = ()

SEMI_FILTER_RELAXATION: dict[str, Any] = {
    "min_volume": 150,
    "min_volume_leg2": 80,
    "min_combined_odds": 1.35,
    "min_confidence": 55,
    "leg1_min_odds": 1.12,
    "leg2_min_odds": 1.15,
}

COMBO_ALIASES = {
    "combo_u45_u85": "combo_u45_u105",
    "combo_u45_o85": "combo_u45_u105",
    "all_combos": "combo_u45_u105",
    "under45": "combo_u45_u105",
    "corners_105": "combo_u45_u105",
    "corners_under_105": "combo_u45_u105",
    "u45": "combo_u45_u105",
    "u105": "combo_u45_u105",
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
