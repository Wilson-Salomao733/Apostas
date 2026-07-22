"""Carrega bot_config.ini e perfis de múltiplas / apostas simples."""

from __future__ import annotations

import json
import os
from configparser import ConfigParser
from pathlib import Path
from typing import Any

from combo_definitions import (
    ALL_COMBO_KEYS,
    ALL_SINGLE_KEYS,
    COMBO_DEFINITIONS,
    SEMI_FILTER_RELAXATION,
    SINGLE_DEFINITIONS,
    is_combo_strategy,
    is_single_strategy,
    leg_profile,
    resolve_combo_key,
)

ROOT = Path(__file__).resolve().parent
BOT_CONFIG_PATH = ROOT / "bot_config.ini"
MODE_FILE = ROOT / "data" / "bot_mode.json"
STRATEGY_FILE = ROOT / "data" / "active_strategy.json"

VALID_MODES = ("off", "manual", "semi", "auto")
VALID_STRATEGIES = ("all_combos",) + ALL_COMBO_KEYS + ALL_SINGLE_KEYS


def load_bot_config() -> ConfigParser:
    cfg = ConfigParser()
    path = os.getenv("BOT_CONFIG_PATH", str(BOT_CONFIG_PATH))
    cfg.read(path)
    return cfg


def get_active_strategy() -> str:
    """Prioriza data/active_strategy.json (gravável no Docker); fallback no ini."""
    data = _read_json(STRATEGY_FILE, {})
    raw = data.get("strategy")
    if raw:
        key = resolve_combo_key(str(raw))
        if key in VALID_STRATEGIES:
            return key

    cfg = load_bot_config()
    raw = cfg.get("bot", "active_strategy", fallback="combo_u45_u105")
    return resolve_combo_key(raw)


def save_strategy(key: str) -> None:
    key = resolve_combo_key(key)
    if key not in VALID_STRATEGIES:
        raise ValueError(f"Estratégia inválida: {key}")
    _write_json(STRATEGY_FILE, {"strategy": key})
    # Melhor esforço: espelha no ini se for gravável (fora do Docker :ro)
    try:
        path = Path(os.getenv("BOT_CONFIG_PATH", str(BOT_CONFIG_PATH)))
        cfg = ConfigParser()
        cfg.read(path)
        if not cfg.has_section("bot"):
            cfg.add_section("bot")
        cfg.set("bot", "active_strategy", key)
        with open(path, "w") as f:
            cfg.write(f)
    except OSError:
        pass


def get_check_interval() -> int:
    cfg = load_bot_config()
    return cfg.getint("bot", "check_interval", fallback=120)


def get_daily_scan_config() -> dict[str, Any]:
    """Configuração da varredura diária informativa."""
    cfg = load_bot_config()
    section = "daily_scan"
    strategy = resolve_combo_key(cfg.get(section, "strategy", fallback="all_combos"))
    if strategy not in VALID_STRATEGIES:
        strategy = "all_combos"
    return {
        "enabled": cfg.getboolean(section, "enabled", fallback=True),
        "time": cfg.get(section, "time", fallback="09:00"),
        "strategy": strategy,
        "send_empty": cfg.getboolean(section, "send_empty", fallback=True),
    }


def _section_params(section: str, defaults: dict[str, Any]) -> dict[str, Any]:
    cfg = load_bot_config()

    def _float(opt: str, fallback: float) -> float:
        if cfg.has_section(section) and cfg.has_option(section, opt):
            return cfg.getfloat(section, opt)
        return float(defaults.get(opt, fallback))

    def _int(opt: str, fallback: int) -> int:
        if cfg.has_section(section) and cfg.has_option(section, opt):
            return cfg.getint(section, opt)
        return int(defaults.get(opt, fallback))

    def _optional_float(opt: str) -> float | None:
        if cfg.has_section(section) and cfg.has_option(section, opt):
            return cfg.getfloat(section, opt)
        return defaults.get(opt)

    return {
        "stake": _float("stake", float(defaults.get("stake", 20.0))),
        "min_odds": _float("min_odds", float(defaults.get("min_odds", 1.20))),
        "max_odds": _float("max_odds", float(defaults.get("max_odds", 2.00))),
        "min_combined_odds": _float(
            "min_combined_odds", float(defaults.get("min_combined_odds", 1.70))
        ),
        "max_combined_odds": _float(
            "max_combined_odds", float(defaults.get("max_combined_odds", 3.00))
        ),
        "min_confidence": _int("min_confidence", int(defaults.get("min_confidence", 72))),
        "max_concurrent_bets": _int(
            "max_concurrent_bets", int(defaults.get("max_concurrent_bets", 3))
        ),
        "daily_loss_limit": _float(
            "daily_loss_limit", float(defaults.get("daily_loss_limit", 60.0))
        ),
        "daily_profit_target": _float(
            "daily_profit_target", float(defaults.get("daily_profit_target", 100.0))
        ),
        "min_volume": _float("min_volume", float(defaults.get("min_volume", 3000))),
        "min_volume_leg2": _float(
            "min_volume_leg2", float(defaults.get("min_volume_leg2", 500))
        ),
        "leg1_min_odds": _optional_float("leg1_min_odds"),
        "leg2_min_odds": _optional_float("leg2_min_odds"),
        "leg2_stake_ratio": _optional_float("leg2_stake_ratio"),
        "require_stats": (
            cfg.getboolean(section, "require_stats", fallback=bool(defaults.get("require_stats", False)))
            if cfg.has_section(section)
            else bool(defaults.get("require_stats", False))
        ),
    }


def get_combo_params(combo_key: str) -> dict[str, Any]:
    """Parâmetros da múltipla (stake, limites, odd combinada)."""
    key = resolve_combo_key(combo_key)
    defaults = COMBO_DEFINITIONS[key]
    section = defaults.get("config_section", key)
    params = _section_params(section, defaults)
    params["good_league_only"] = defaults.get("good_league_only", True)
    return params


def get_single_params(single_key: str) -> dict[str, Any]:
    """Parâmetros de aposta simples (1 perna)."""
    key = resolve_combo_key(single_key)
    defaults = SINGLE_DEFINITIONS[key]
    section = defaults.get("config_section", key)
    params = _section_params(section, defaults)
    params["good_league_only"] = defaults.get("good_league_only", True)
    return params


def get_strategy_params(strategy_key: str) -> dict[str, Any]:
    key = resolve_combo_key(strategy_key)
    if is_single_strategy(key):
        return get_single_params(key)
    if is_combo_strategy(key):
        return get_combo_params(key)
    return get_combo_params("combo_u45_u105")


def _apply_semi_relaxation(combo: dict[str, Any]) -> None:
    """Afrouxa filtros só para sugestões (semi/manual). Auto não chama isto."""
    relax = SEMI_FILTER_RELAXATION
    for key in ("min_volume", "min_volume_leg2", "min_combined_odds", "min_confidence"):
        if key not in relax:
            continue
        current = combo.get(key)
        if current is None:
            combo[key] = relax[key]
        else:
            combo[key] = min(float(current), float(relax[key]))

    if combo.get("leg1") == "under45":
        combo["leg1_min_odds"] = float(relax["leg1_min_odds"])
    if combo.get("leg2") == "corners_under_105":
        combo["leg2_min_odds"] = float(relax["leg2_min_odds"])
    if combo.get("leg2") == "under45":
        combo["leg2_min_odds"] = float(relax["leg1_min_odds"])


def _apply_single_semi_relaxation(profile: dict[str, Any]) -> None:
    relax = SEMI_FILTER_RELAXATION
    if "min_confidence" in relax:
        profile["min_confidence"] = min(
            int(profile.get("min_confidence", 72)), int(relax["min_confidence"])
        )
    soft_vol = float(relax.get("single_min_volume", relax.get("min_volume", 400)))
    profile["min_volume"] = min(float(profile.get("min_volume", soft_vol)), soft_vol)


def build_scan_profiles(
    active_strategy: str | None = None,
    filter_mode: str = "auto",
) -> list[dict[str, Any]]:
    """Retorna perfis (combo ou single). filter_mode=auto usa filtros estritos;
    semi/manual relaxam para enviar mais sugestões."""
    strategy = resolve_combo_key(active_strategy or get_active_strategy())
    relaxed = filter_mode in ("semi", "manual")

    if is_single_strategy(strategy):
        return [_build_single_profile(strategy, relaxed)]

    if strategy == "all_combos":
        keys = list(ALL_COMBO_KEYS)
    elif is_combo_strategy(strategy):
        keys = [strategy]
    else:
        keys = ["combo_u45_u105"]

    profiles: list[dict[str, Any]] = []
    for key in keys:
        combo = dict(COMBO_DEFINITIONS[key])
        combo.update(get_combo_params(key))
        if relaxed:
            _apply_semi_relaxation(combo)
        combo["kind"] = "combo"
        combo["filter_mode"] = "semi" if relaxed else "auto"
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


def _build_single_profile(key: str, relaxed: bool) -> dict[str, Any]:
    base = dict(SINGLE_DEFINITIONS[key])
    base.update(get_single_params(key))
    if relaxed:
        _apply_single_semi_relaxation(base)
    base["kind"] = "single"
    base["filter_mode"] = "semi" if relaxed else "auto"
    base["sport"] = "football"
    base["event_type_id"] = "1"
    return base


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
    groq_keys = [
        os.getenv("GROQ_API_KEY", ""),
        os.getenv("GROQ_API_KEY_2", ""),
        os.getenv("GROQ_API_KEYS", ""),
        cfg.get("api_keys", "groq_api_key", fallback=""),
        cfg.get("api_keys", "groq_api_key_2", fallback=""),
    ]
    gk = ",".join(k.strip() for k in groq_keys if k.strip())
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
    if key in SINGLE_DEFINITIONS:
        return SINGLE_DEFINITIONS[key]["label"]
    return COMBO_DEFINITIONS.get(key, {}).get("label", key)
