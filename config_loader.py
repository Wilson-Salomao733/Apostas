"""Carrega bot_config.ini, modos e perfis de varredura."""

from __future__ import annotations

import json
import os
from configparser import ConfigParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
BOT_CONFIG_PATH = ROOT / "bot_config.ini"
MODE_FILE = ROOT / "data" / "bot_mode.json"
SPORTS_FILE = ROOT / "data" / "enabled_sports.json"

VALID_MODES = ("off", "manual", "semi", "auto")
VALID_STRATEGIES = (
    "under45", "over15", "over25", "favorite", "under_max",
    "corners_85", "corners_105", "combo_u45_u85",
    "tennis_match", "tennis_games",
)
VALID_SPORTS = ("football", "tennis")

SPORT_EVENT_TYPES = {
    "football": "1",
    "tennis": "2",
}

PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "under45": {
        "key": "under45",
        "label": "Under 4.5 Gols",
        "sport": "football",
        "market_type": "OVER_UNDER_45",
        "selection_hint": "under",
        "min_odds": 1.25,
        "max_odds": 1.40,
        "min_confidence": 75,
        "risk": "baixo",
        "prompt_goal": "MENOS de 4,5 gols (máximo 4 gols no jogo)",
        "config_section": "under45",
    },
    "over15": {
        "key": "over15",
        "label": "Over 1.5 Gols",
        "sport": "football",
        "market_type": "OVER_UNDER_15",
        "selection_hint": "over",
        "min_odds": 1.25,
        "max_odds": 1.60,
        "min_confidence": 72,
        "risk": "baixo",
        "prompt_goal": "MAIS de 1,5 gols (pelo menos 2 gols no jogo)",
        "config_section": "over15",
    },
    "over25": {
        "key": "over25",
        "label": "Over 2.5 Gols",
        "sport": "football",
        "market_type": "OVER_UNDER_25",
        "selection_hint": "over",
        "min_odds": 1.80,
        "max_odds": 2.60,
        "min_confidence": 70,
        "risk": "médio",
        "prompt_goal": "MAIS de 2,5 gols (pelo menos 3 gols no jogo)",
        "config_section": "over25",
    },
    "favorite": {
        "key": "favorite",
        "label": "Favorito (Match Odds)",
        "sport": "football",
        "market_type": "MATCH_ODDS",
        "selection_hint": "favorite",
        "min_odds": 1.45,
        "max_odds": 1.90,
        "min_confidence": 70,
        "risk": "médio",
        "prompt_goal": "vitória do time favorito (Match Odds)",
        "config_section": "favorite",
    },
    "corners_85": {
        "key": "corners_85",
        "label": "Under 8.5 Escanteios",
        "sport": "football",
        "market_type": "OVER_UNDER_85_CORNR",
        "selection_hint": "under",
        "min_odds": 1.25,
        "max_odds": 1.55,
        "min_confidence": 72,
        "risk": "médio",
        "prompt_goal": "MENOS de 8,5 escanteios na partida",
        "config_section": "corners_85",
        "min_volume": 3000,
        "good_league_only": True,
    },
    "corners_105": {
        "key": "corners_105",
        "label": "Under 10.5 Escanteios",
        "sport": "football",
        "market_type": "OVER_UNDER_105_CORNR",
        "selection_hint": "under",
        "min_odds": 1.25,
        "max_odds": 1.55,
        "min_confidence": 72,
        "risk": "médio",
        "prompt_goal": "MENOS de 10,5 escanteios na partida",
        "config_section": "corners_105",
        "min_volume": 5000,
        "good_league_only": True,
    },
    "tennis_match": {
        "key": "tennis_match",
        "label": "Tênis — Match Odds",
        "sport": "tennis",
        "market_type": "MATCH_ODDS",
        "selection_hint": "favorite",
        "min_odds": 1.45,
        "max_odds": 2.20,
        "min_confidence": 70,
        "risk": "médio",
        "prompt_goal": "vitória do jogador favorito (Match Odds)",
        "config_section": "tennis_match",
        "min_volume": 3000,
    },
    "tennis_games": {
        "key": "tennis_games",
        "label": "Tênis — Total Games O/U",
        "sport": "tennis",
        "market_type": "OVER_UNDER_215_GAMES",
        "selection_hint": "under",
        "min_odds": 1.50,
        "max_odds": 2.10,
        "min_confidence": 72,
        "risk": "médio",
        "prompt_goal": "MENOS de 21,5 games no jogo (partida não muito longa)",
        "config_section": "tennis_games",
        "min_volume": 2000,
    },
    "combo_u45_u85": {
        "key": "combo_u45_u85",
        "label": "Múltipla U4.5 gols + U8.5 escanteios",
        "sport": "football",
        "risk": "médio",
        "config_section": "combo_u45_u85",
        "good_league_only": True,
        "min_volume": 3000,
    },
}

FOOTBALL_STRATEGIES = ("under45", "over15", "over25", "favorite", "corners_85", "corners_105", "combo_u45_u85")
TENNIS_STRATEGIES = ("tennis_match", "tennis_games")


def load_bot_config() -> ConfigParser:
    cfg = ConfigParser()
    path = os.getenv("BOT_CONFIG_PATH", str(BOT_CONFIG_PATH))
    cfg.read(path)
    return cfg


def get_active_strategy() -> str:
    cfg = load_bot_config()
    return cfg.get("bot", "active_strategy", fallback="under45")


def get_check_interval() -> int:
    cfg = load_bot_config()
    strategy = get_active_strategy()
    if cfg.has_section(strategy) and cfg.has_option(strategy, "check_interval"):
        return cfg.getint(strategy, "check_interval")
    return cfg.getint("bot", "check_interval", fallback=120)


def get_strategy_params(strategy_key: str) -> dict[str, Any]:
    """Parâmetros de risco/stake da seção da estratégia no INI."""
    cfg = load_bot_config()
    section = strategy_key
    defaults = PROFILE_DEFAULTS.get(strategy_key, {})
    config_section = defaults.get("config_section", strategy_key)

    def _float(key: str, fallback: float) -> float:
        if cfg.has_section(config_section) and cfg.has_option(config_section, key):
            return cfg.getfloat(config_section, key)
        return fallback

    def _int(key: str, fallback: int) -> int:
        if cfg.has_section(config_section) and cfg.has_option(config_section, key):
            return cfg.getint(config_section, key)
        return fallback

    return {
        "stake": _float("stake", 20.0),
        "min_odds": _float("min_odds", defaults.get("min_odds", 1.25)),
        "max_odds": _float("max_odds", defaults.get("max_odds", 2.0)),
        "min_combined_odds": _float("min_combined_odds", 1.55),
        "max_combined_odds": _float("max_combined_odds", 2.40),
        "min_confidence": _int("min_confidence", defaults.get("min_confidence", 70)),
        "max_concurrent_bets": _int("max_concurrent_bets", 3),
        "daily_loss_limit": _float("daily_loss_limit", 60.0),
        "daily_profit_target": _float("daily_profit_target", 80.0),
        "require_stats": cfg.getboolean(config_section, "require_stats", fallback=False)
        if cfg.has_section(config_section)
        else False,
    }


def build_scan_profiles(
    active_strategy: str | None = None,
    enabled_sports: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Monta perfis de varredura mesclando defaults com bot_config.ini."""
    strategy = active_strategy or get_active_strategy()
    sports = enabled_sports if enabled_sports is not None else load_enabled_sports()
    profiles: list[dict[str, Any]] = []

    keys_to_scan: list[str] = []
    if strategy == "combo_u45_u85":
        if "football" in sports:
            keys_to_scan.append("combo_u45_u85")
    elif "football" in sports:
        if strategy in FOOTBALL_STRATEGIES:
            keys_to_scan.append(strategy)
        elif strategy == "under_max":
            keys_to_scan.extend(["under45", "corners_105"])
        else:
            keys_to_scan.extend([k for k in FOOTBALL_STRATEGIES if k != "corners_105"])
            keys_to_scan.append("corners_105")
    if "tennis" in sports:
        if strategy in TENNIS_STRATEGIES:
            keys_to_scan.append(strategy)
        else:
            keys_to_scan.extend(TENNIS_STRATEGIES)

    seen: set[str] = set()
    for key in keys_to_scan:
        if key in seen:
            continue
        if key == "combo_u45_u85":
            seen.add(key)
            params = get_strategy_params("combo_u45_u85")
            base = dict(PROFILE_DEFAULTS["combo_u45_u85"])
            base.update(params)
            base["event_type_id"] = SPORT_EVENT_TYPES["football"]
            profiles.append(base)
            continue
        if key not in PROFILE_DEFAULTS:
            continue
        seen.add(key)
        base = dict(PROFILE_DEFAULTS[key])
        params = get_strategy_params(key)
        base["min_odds"] = max(base["min_odds"], params["min_odds"], 1.20)
        base["max_odds"] = params["max_odds"]
        base["min_confidence"] = params["min_confidence"]
        base["stake"] = params["stake"]
        base["max_concurrent_bets"] = params["max_concurrent_bets"]
        base["daily_loss_limit"] = params["daily_loss_limit"]
        base["daily_profit_target"] = params["daily_profit_target"]
        base["require_stats"] = params["require_stats"]
        base["event_type_id"] = SPORT_EVENT_TYPES[base["sport"]]
        profiles.append(base)

    return profiles


def _read_json(path: Path, default: dict) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return default


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def load_mode() -> str:
    data = _read_json(MODE_FILE, {"mode": "manual"})
    mode = data.get("mode", "manual")
    return mode if mode in VALID_MODES else "manual"


def save_mode(mode: str) -> None:
    if mode not in VALID_MODES:
        raise ValueError(f"Modo inválido: {mode}")
    _write_json(MODE_FILE, {"mode": mode})


def load_enabled_sports() -> list[str]:
    data = _read_json(SPORTS_FILE, {"sports": ["football"]})
    sports = [s for s in data.get("sports", ["football"]) if s in VALID_SPORTS]
    return sports or ["football"]


def save_enabled_sports(sports: list[str]) -> None:
    valid = [s for s in sports if s in VALID_SPORTS]
    if not valid:
        valid = ["football"]
    _write_json(SPORTS_FILE, {"sports": valid})


def toggle_sport(sport: str) -> list[str]:
    current = load_enabled_sports()
    if sport in current:
        current = [s for s in current if s != sport]
    else:
        current.append(sport)
    if not current:
        current = ["football"]
    save_enabled_sports(current)
    return current


def is_dry_run() -> bool:
    """Desativado — bot só aposta de verdade na Betfair."""
    return False


def set_dry_run(_enabled: bool) -> None:
    pass


def get_manual_stake() -> float:
    cfg = load_bot_config()
    return cfg.getfloat("manual", "stake", fallback=20.0)


def get_api_keys() -> tuple[str, str]:
    cfg = load_bot_config()
    fk = os.getenv("API_FOOTBALL_KEY") or cfg.get("api_keys", "api_football_key", fallback="")
    gk = os.getenv("GROQ_API_KEY") or cfg.get("api_keys", "groq_api_key", fallback="")
    return fk, gk


def get_telegram_creds() -> tuple[str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        cfg = load_bot_config()
        token = token or cfg.get("telegram", "bot_token", fallback="")
        chat = chat or str(cfg.get("telegram", "chat_id", fallback=""))
    return token, chat
