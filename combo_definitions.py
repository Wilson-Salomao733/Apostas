"""Definições das carteiras e apostas simples suportadas pelo bot."""

from __future__ import annotations

import unicodedata
from typing import Any

# Ligas com Over 2.5 <= 50%, só as que a Betfair já listou (catálogo ou CSV).
# exclude evita copa, feminino e divisões erradas com o mesmo país.
U45_ALLOWED_LEAGUES: tuple[dict[str, Any], ...] = (
    {"label": "Brasileirão Série A", "over25": 50, "include": ("brazilian serie a", "brasileirao serie a"), "exclude": ("serie b", "serie c", "serie d")},
    {"label": "Macedônia 1 MFL", "over25": 50, "include": ("north macedonian", "macedonian soccer"), "exclude": ()},
    {"label": "Bósnia Primeira Liga", "over25": 50, "include": ("bosnian premier",), "exclude": ()},
    {"label": "Japão J League 2", "over25": 50, "include": ("japanese j league 2", "j2 league"), "exclude": ()},
    {"label": "Turquia 1. Lig", "over25": 48, "include": ("turkish 1", "tff 1"), "exclude": ()},
    {"label": "Ucrânia Premier", "over25": 47, "include": ("ukrainian premier", "ukraine premier"), "exclude": ("persha", "first")},
    {"label": "Azerbaijão 1st Division", "over25": 47, "include": ("azerbaijan 1st",), "exclude": ()},
    {"label": "Cazaquistão Premier", "over25": 47, "include": ("kazakhstan premier",), "exclude": ()},
    {"label": "Colômbia Primera A", "over25": 46, "include": ("colombian primera a",), "exclude": ("primera b", "femenina")},
    {"label": "Sérvia Superliga", "over25": 46, "include": ("serbian super",), "exclude": ()},
    {"label": "França Ligue 2", "over25": 44, "include": ("french ligue 2", "ligue 2"), "exclude": ()},
    {"label": "Romênia Liga 1", "over25": 44, "include": ("romanian liga", "liga 1"), "exclude": ()},
    {"label": "K League 1", "over25": 44, "include": ("south korean k1", "k league 1"), "exclude": ()},
    {"label": "Uruguai Primera", "over25": 44, "include": ("uruguayan primera",), "exclude": ()},
    {"label": "Brasileirão Série C", "over25": 42, "include": ("brazilian serie c", "brasileirao serie c"), "exclude": ()},
    {"label": "Uganda Premier", "over25": 42, "include": ("ugandan premier",), "exclude": ()},
    {"label": "Brasileirão Série B", "over25": 42, "include": ("brazilian serie b", "brasileirao serie b"), "exclude": ()},
    {"label": "Tanzânia Premier", "over25": 41, "include": ("tanzanian premier",), "exclude": ()},
    {"label": "Índia Super Liga", "over25": 41, "include": ("indian super league",), "exclude": ()},
    {"label": "Eslovênia Prva Liga", "over25": 41, "include": ("slovenian prva", "slovenian first"), "exclude": ()},
    {"label": "Liga Portugal 2", "over25": 41, "include": ("liga portugal 2", "portuguese segunda"), "exclude": ()},
    {"label": "Grécia Super Liga 2", "over25": 39, "include": ("greek super league 2", "super league 2"), "exclude": ()},
    {"label": "Grécia Super Liga", "over25": 40, "include": ("greek super league",), "exclude": ("2",)},
    {"label": "Argentina Liga Profesional", "over25": 40, "include": ("argentinian primera division", "liga profesional"), "exclude": ("nacional",)},
    {"label": "Equador Serie A", "over25": 40, "include": ("ecuadorian serie a", "ecuador serie a"), "exclude": ()},
    {"label": "África do Sul Premier", "over25": 39, "include": ("south african premier",), "exclude": ()},
    {"label": "La Liga 2", "over25": 39, "include": ("spanish segunda", "laliga 2", "segunda division"), "exclude": ("b2",)},
    {"label": "Marrocos Botola", "over25": 38, "include": ("botola", "moroccan"), "exclude": ()},
    {"label": "Brasileirão Série D", "over25": 38, "include": ("brazilian serie d", "brasileirao serie d"), "exclude": ()},
    {"label": "Bahrein Premier", "over25": 33, "include": ("bahraini premier",), "exclude": ()},
    {"label": "França Nacional", "over25": 33, "include": ("french national", "championnat national"), "exclude": ()},
    {"label": "Argentina Primera Nacional", "over25": 33, "include": ("argentinian primera nacional", "primera nacional"), "exclude": ()},
    {"label": "Montenegro Prva", "over25": 32, "include": ("montenegrin 1st", "montenegrin first"), "exclude": ()},
    {"label": "Egito Premier", "over25": 31, "include": ("egyptian premier",), "exclude": ("2nd", "second")},
    {"label": "Finlândia Veikkausliiga", "over25": 20, "include": ("veikkausliiga", "finnish veikkaus"), "exclude": ()},
    {"label": "Argélia Ligue 1", "over25": 17, "include": ("algerian ligue 1",), "exclude": ()},
    {"label": "Escócia Championship", "over25": 16, "include": ("scottish championship",), "exclude": ()},
)

_U45_NAME_BLOCK = (
    "cup", "copa ", "women", "femenin", "feminino", "u20", "u21", "u23",
    "2nd division", "primera b", "liga femenina", "friendly", "amistoso",
)


def _norm_league(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value).lower())
    return " ".join(
        "".join(char for char in text if not unicodedata.combining(char))
        .replace("-", " ")
        .split()
    )


def u45_league_allowed(league: str) -> bool:
    name = _norm_league(league)
    if any(token in name for token in _U45_NAME_BLOCK):
        return False
    for rule in U45_ALLOWED_LEAGUES:
        if not any(token in name for token in rule["include"]):
            continue
        if any(token in name for token in rule.get("exclude", ())):
            continue
        return True
    return False


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
    "combo_u105_u45": {
        "key": "combo_u105_u45",
        "label": "U10.5 e U4.5 independentes",
        "leg1": "corners_under_105",
        "leg2": "under45",
        "leg1_short": "U10.5 esc",
        "leg2_short": "U4.5 gols",
        "ia_hint": (
            "Duas pernas independentes no mesmo ciclo: U10.5 por preço/spread "
            "e U4.5 só em ligas de poucos gols."
        ),
        "needs_corners_stats": False,
        "config_section": "combo_u105_u45",
        "good_league_only": False,
        "independent_legs": True,
        "primary_optional_leg": False,
        "u45_leagues": (
            "laliga 2",
            "segunda division",
            "segunda división",
            "liga profesional argentina",
            "argentina primera division",
            "primera nacional",
            "brasileirao serie a",
            "brasileirão série a",
            "campeonato brasileiro serie a",
            "campeonato brasileiro série a",
            "brasileirao serie b",
            "brasileirão série b",
            "campeonato brasileiro serie b",
            "campeonato brasileiro série b",
            "super league greece",
            "greek super league",
            "egyptian premier league",
        ),
        "favorite_min_odds": 1.40,
        "leg1_min_odds": 1.20,
        "leg2_min_odds": 1.30,
        "min_confidence": 60,
        "corner_stake": 20.0,
        "goal_stake": 20.0,
        "stake": 40.0,
        "max_concurrent_bets": 2,
        "daily_loss_limit": 70.0,
        "daily_profit_target": 100.0,
        "commission_rate": 0.065,
        "max_spread_pct": 10.0,
        "min_back_size": 10.0,
        "min_ev_pct": 2.0,
        "min_probability_edge_pct": 2.0,
        "max_event_exposure": 70.0,
        "max_total_exposure": 70.0,
        "fallback_single_enabled": True,
        "live_enabled": True,
    },
    "combo_u45_u105": {
        "key": "combo_u45_u105",
        "label": "Carteira U4.5 gols + U10.5 esc",
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
        "stake": 4.0,
        "max_concurrent_bets": 2,
        "daily_loss_limit": 12.0,
        "daily_profit_target": 20.0,
        "commission_rate": 0.065,
        "max_spread_pct": 10.0,
        "min_back_size": 10.0,
        "min_ev_pct": 2.0,
        "min_probability_edge_pct": 2.0,
        "live_enabled": False,
        # O fallback não é liberado até superar validação temporal.
        "fallback_single_enabled": False,
        "fallback_single_stake": 2.0,
    },
}

ALL_COMBO_KEYS: tuple[str, ...] = tuple(COMBO_DEFINITIONS.keys())

SINGLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "under45": {
        "key": "under45",
        "kind": "single",
        "label": "Menos 4.5 gols",
        "market_type": "OVER_UNDER_45",
        "selection_hint": "under",
        "min_odds": 1.30,
        "max_odds": 1.40,
        "min_confidence": 60,
        "min_volume": 300,
        "good_league_only": False,
        "require_stats": True,
        "favorite_min_odds": 1.40,
        "use_u45_allowlist": True,
        "config_section": "under45",
        "prompt_goal": "Menos de 4.5 gols no jogo (máximo 4 gols).",
        "risk": "médio",
        "stake": 20.0,
        "max_concurrent_bets": 2,
        "daily_loss_limit": 70.0,
        "daily_profit_target": 100.0,
        "commission_rate": 0.065,
        "max_spread_pct": 8.0,
        "min_back_size": 10.0,
        "min_ev_pct": 2.0,
        "min_probability_edge_pct": 2.0,
        "max_event_exposure": 35.0,
        "max_total_exposure": 70.0,
        "live_enabled": True,
    },
    "corners_105": {
        "key": "corners_105",
        "kind": "single",
        "label": "Menos 10.5 escanteios",
        "market_type": "OVER_UNDER_105_CORNR",
        "selection_hint": "under",
        "min_odds": 1.40,
        "max_odds": 1.73,
        "min_confidence": 58,
        "min_volume": 100,
        "good_league_only": False,
        "require_stats": False,
        "authorize_on_price_band": True,
        "config_section": "corners_105",
        "prompt_goal": "Menos de 10.5 escanteios no jogo (máximo 10 escanteios).",
        "risk": "médio",
        "stake": 20.0,
        "max_concurrent_bets": 2,
        "daily_loss_limit": 70.0,
        "daily_profit_target": 100.0,
        "commission_rate": 0.065,
        "max_spread_pct": 10.0,
        "min_back_size": 10.0,
        "min_ev_pct": 2.0,
        "min_probability_edge_pct": 2.0,
        "max_event_exposure": 35.0,
        "max_total_exposure": 70.0,
        "live_enabled": True,
    },
}

ALL_SINGLE_KEYS: tuple[str, ...] = tuple(SINGLE_DEFINITIONS.keys())

SEMI_FILTER_RELAXATION: dict[str, Any] = {
    "min_volume": 150,
    "min_volume_leg2": 80,
    "min_combined_odds": 1.35,
    "min_confidence": 55,
    "leg1_min_odds": 1.12,
    "leg2_min_odds": 1.15,
    "single_min_volume": 50,
}

COMBO_ALIASES = {
    "combo_u45_u85": "combo_u45_u105",
    "combo_u45_o85": "combo_u45_u105",
    "all_combos": "combo_u45_u105",
    "corners_under_105": "corners_105",
    "u45": "under45",
    "u105": "corners_105",
    "u105_u45": "combo_u105_u45",
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
