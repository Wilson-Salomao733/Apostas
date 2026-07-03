"""Carrega bot_config.ini e perfis de múltiplas."""

from __future__ import annotations

import json
import os
from configparser import ConfigParser
from pathlib import Path
from typing import Any

from combo_definitions import (
    ALL_COMBO_KEYS,
    COMBO_DEFINITIONS,
    leg_profile,
    resolve_combo_key,
)

ROOT = Path(__file__).resolve().parent
BOT_CONFIG_PATH = ROOT / "bot_config.ini"
MODE_FILE = ROOT / "data" / "bot_mode.json"

VALID_MODES = ("off", "manual", "semi", "auto")
VALID_STRATEGIES = ("all_combos",) + ALL_COMBO_KEYS


def load_bot_config() -> ConfigParser:
    cfg = ConfigParser()
    path = os.getenv("BOT_CONFIG_PATH", str(BOT_CONFIG_PATH))
    cfg.read(path)
    return cfg


def get_active_strategy() -> str:
    cfg = load_bot_config()
    raw = cfg.get("bot", "active_strategy", fallback="combo_u45_u105")
    return resolve_combo_key(raw)


def get_check_interval() -> int:
    cfg = load_bot_config()
    return cfg.getint("bot", "check_interval", fallback=120)


def get_combo_params(combo_key: str) -> dict[str, Any]:
    """Parâmetros da múltipla (stake, limites, odd combinada)."""
    key = resolve_combo_key(combo_key)
    defaults = COMBO_DEFINITIONS[key]
    section = defaults.get("config_section", key)
    cfg = load_bot_config()

    def _float(opt: str, fallback: float) -> float:
        if cfg.has_section(section) and cfg.has_option(section, opt):
            return cfg.getfloat(section, opt)
        return defaults.get(opt, fallback)

    def _int(opt: str, fallback: int) -> int:
        if cfg.has_section(section) and cfg.has_option(section, opt):
            return cfg.getint(section, opt)
        return int(defaults.get(opt, fallback))

    def _optional_float(opt: str) -> float | None:
        if cfg.has_section(section) and cfg.has_option(section, opt):
            return cfg.getfloat(section, opt)
        return defaults.get(opt)

    return {
        "stake": _float("stake", 20.0),
        "min_combined_odds": _float("min_combined_odds", defaults.get("min_combined_odds", 1.70)),
        "max_combined_odds": _float("max_combined_odds", defaults.get("max_combined_odds", 3.00)),
        "min_confidence": _int("min_confidence", 72),
        "max_concurrent_bets": _int("max_concurrent_bets", 3),
        "daily_loss_limit": _float("daily_loss_limit", 60.0),
        "daily_profit_target": _float("daily_profit_target", 100.0),
        "min_volume": _float("min_volume", defaults.get("min_volume", 3000)),
        "good_league_only": defaults.get("good_league_only", True),
        "leg1_min_odds": _optional_float("leg1_min_odds"),
        "leg2_min_odds": _optional_float("leg2_min_odds"),
        "leg2_stake_ratio": _optional_float("leg2_stake_ratio"),
    }


def build_scan_profiles(active_strategy: str | None = None) -> list[dict[str, Any]]:
    """Retorna apenas perfis de múltiplas para varredura."""
    strategy = resolve_combo_key(active_strategy or get_active_strategy())
    if strategy == "all_combos":
        keys = list(ALL_COMBO_KEYS)
    elif strategy in COMBO_DEFINITIONS:
        keys = [strategy]
    else:
        keys = ["combo_u45_u105"]

    profiles: list[dict[str, Any]] = []
    for key in keys:
        combo = dict(COMBO_DEFINITIONS[key])
        combo.update(get_combo_params(key))
        combo["leg1_profile"] = leg_profile(combo["leg1"])
        combo["leg2_profile"] = leg_profile(combo["leg2"])
        if combo.get("leg1_min_odds") is not None:
            combo["leg1_profile"]["min_odds"] = float(combo["leg1_min_odds"])
        if combo.get("leg2_min_odds") is not None:
            combo["leg2_profile"]["min_odds"] = float(combo["leg2_min_odds"])
        combo["sport"] = "football"
        combo["event_type_id"] = "1"
        combo["risk"] = "médio"
        profiles.append(combo)
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


def is_dry_run() -> bool:
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


def combo_label(key: str) -> str:
    key = resolve_combo_key(key)
    if key == "all_combos":
        return "Todas múltiplas"
    return COMBO_DEFINITIONS.get(key, {}).get("label", key)
