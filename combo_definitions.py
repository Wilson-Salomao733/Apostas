"""Definições de pernas, apostas simples e múltiplas (mesmo jogo)."""

from __future__ import annotations

from typing import Any

# Pernas reutilizáveis (mercado Betfair + filtro de odd)
LEG_TEMPLATES: dict[str, dict[str, Any]] = {
    "under45": {
        "key": "under45",
        "market_type": "OVER_UNDER_45",
        "selection_hint": "under",
        "min_odds": 1.20,
        "max_odds": 1.45,
    },
    "corners_under_105": {
        "key": "corners_under_105",
        "market_type": "OVER_UNDER_105_CORNR",
        "selection_hint": "under",
        "min_odds": 1.35,
        "max_odds": 2.25,
    },
    "under35": {
        "key": "under35",
        "market_type": "OVER_UNDER_35",
        "selection_hint": "under",
        "min_odds": 1.30,
        "max_odds": 1.55,
    },
    "over15": {
        "key": "over15",
        "market_type": "OVER_UNDER_15",
        "selection_hint": "over",
        "min_odds": 1.25,
        "max_odds": 1.55,
    },
    "corners_over_85": {
        "key": "corners_over_85",
        "market_type": "OVER_UNDER_85_CORNR",
        "selection_hint": "over",
        "min_odds": 1.45,
        "max_odds": 2.30,
    },
    "btts_no": {
        "key": "btts_no",
        "market_type": "BOTH_TEAMS_TO_SCORE",
        "selection_hint": "no",
        "min_odds": 1.50,
        "max_odds": 2.40,
    },
    "favorite": {
        "key": "favorite",
        "market_type": "MATCH_ODDS",
        "selection_hint": "favorite",
        "min_odds": 1.45,
        "max_odds": 2.10,
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
        "good_league_only": True,
        # Filtros estritos (modo auto). Semi/manual relaxam via config_loader.
        "min_volume": 2000,
        "min_volume_leg2": 2000,
        "min_combined_odds": 1.55,
        "max_combined_odds": 2.80,
        "leg1_min_odds": 1.20,
        "leg2_min_odds": 1.35,
        "leg2_stake_ratio": 0.50,
    },
    "combo_u45_o85": {
        "key": "combo_u45_o85",
        "label": "Menos 4.5 gols + Mais 8.5 esc",
        "leg1": "under45",
        "leg2": "corners_over_85",
        "leg1_short": "U4.5 gols",
        "leg2_short": "O8.5 esc",
        "ia_hint": (
            "Poucos gols mas volume alto de cruzamentos — escanteios podem compensar."
        ),
        "needs_corners_stats": True,
        "config_section": "combo_u45_u85",
        "good_league_only": True,
        "min_volume": 3000,
        "min_combined_odds": 1.70,
        "max_combined_odds": 3.00,
    },
    "combo_u45_btts_no": {
        "key": "combo_u45_btts_no",
        "label": "Menos 4.5 gols + Ambos NÃO marcam",
        "leg1": "under45",
        "leg2": "btts_no",
        "leg1_short": "U4.5 gols",
        "leg2_short": "BTTS Não",
        "ia_hint": (
            "Jogo fechado: poucos gols e baixa chance dos dois times marcarem."
        ),
        "needs_corners_stats": False,
        "config_section": "combo_u45_btts_no",
        "good_league_only": True,
        "min_volume": 3000,
        "min_combined_odds": 1.65,
        "max_combined_odds": 2.80,
    },
    "combo_u35_o85": {
        "key": "combo_u35_o85",
        "label": "Menos 3.5 gols + Mais 8.5 esc",
        "leg1": "under35",
        "leg2": "corners_over_85",
        "leg1_short": "U3.5 gols",
        "leg2_short": "O8.5 esc",
        "ia_hint": (
            "Jogo bem truncado em gols (máx. 3) mas com pressão e escanteios."
        ),
        "needs_corners_stats": True,
        "config_section": "combo_u35_o85",
        "good_league_only": True,
        "min_volume": 3000,
        "min_combined_odds": 1.80,
        "max_combined_odds": 3.20,
    },
    "combo_o15_o85": {
        "key": "combo_o15_o85",
        "label": "Mais 1.5 gols + Mais 8.5 esc",
        "leg1": "over15",
        "leg2": "corners_over_85",
        "leg1_short": "O1.5 gols",
        "leg2_short": "O8.5 esc",
        "ia_hint": (
            "Jogo aberto: pelo menos 2 gols e muita ação nas áreas (escanteios)."
        ),
        "needs_corners_stats": True,
        "config_section": "combo_o15_o85",
        "good_league_only": True,
        "min_volume": 4000,
        "min_combined_odds": 1.75,
        "max_combined_odds": 3.00,
    },
    "combo_fav_u45": {
        "key": "combo_fav_u45",
        "label": "Favorito vence + Menos 4.5 gols",
        "leg1": "favorite",
        "leg2": "under45",
        "leg1_short": "Favorito ML",
        "leg2_short": "U4.5 gols",
        "ia_hint": (
            "Favorito controla e vence sem goleada — placar magro (0-0, 1-0, 2-0)."
        ),
        "needs_corners_stats": False,
        "config_section": "combo_fav_u45",
        "good_league_only": True,
        "min_volume": 5000,
        "min_combined_odds": 1.70,
        "max_combined_odds": 3.00,
    },
}

ALL_COMBO_KEYS: tuple[str, ...] = tuple(COMBO_DEFINITIONS.keys())

# Apostas de 1 perna — úteis em dias fracos (sem exigir 2 mercados no mesmo jogo)
SINGLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "under45": {
        "key": "under45",
        "kind": "single",
        "label": "Menos 4.5 gols",
        "market_type": "OVER_UNDER_45",
        "selection_hint": "under",
        "min_odds": 1.20,
        "max_odds": 1.40,
        "min_confidence": 72,
        "min_volume": 1500,
        "good_league_only": True,
        "require_stats": False,
        "config_section": "under45",
        "prompt_goal": "Menos de 4.5 gols no jogo (máximo 4 gols).",
        "risk": "médio",
        "stake": 20.0,
        "max_concurrent_bets": 5,
        "daily_loss_limit": 80.0,
        "daily_profit_target": 80.0,
    },
    "corners_105": {
        "key": "corners_105",
        "kind": "single",
        "label": "Menos 10.5 escanteios",
        "market_type": "OVER_UNDER_105_CORNR",
        "selection_hint": "under",
        "min_odds": 1.20,
        "max_odds": 1.55,
        "min_confidence": 72,
        "min_volume": 500,
        "good_league_only": True,
        "require_stats": False,
        "config_section": "corners_105",
        "prompt_goal": "Menos de 10.5 escanteios no jogo (máximo 10).",
        "risk": "médio",
        "stake": 20.0,
        "max_concurrent_bets": 3,
        "daily_loss_limit": 60.0,
        "daily_profit_target": 80.0,
    },
}

ALL_SINGLE_KEYS: tuple[str, ...] = tuple(SINGLE_DEFINITIONS.keys())

# Relaxamento só para semi/manual (sugestões). Auto NÃO usa isto.
SEMI_FILTER_RELAXATION: dict[str, Any] = {
    "min_volume": 1000,
    "min_volume_leg2": 300,
    "min_combined_odds": 1.50,
    "min_confidence": 70,
    "leg1_min_odds": 1.20,
    "leg2_min_odds": 1.25,
    "single_min_volume": 400,
}

# Aliases legado
COMBO_ALIASES = {
    "combo_u45_u85": "combo_u45_u105",
    "corners_under_105": "corners_105",
    "u45": "under45",
    "u105": "corners_105",
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
