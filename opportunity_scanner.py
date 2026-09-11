#!/usr/bin/env python3
"""
Varredura multi-esporte de oportunidades (futebol + tênis).
Modo manual ou automático — encontra e analisa com IA.
"""

import hashlib
import json
import logging
import os
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import requests

from api_football import APIFootball
from bet_ledger import record_snapshot
from combo_definitions import u45_league_allowed
from config_loader import build_scan_profiles, get_manual_stake
from strategy_model import assess_value, execution_quality

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
CURRENT_SEASON = 2026
MIN_GLOBAL_ODDS = 1.12

GOOD_LEAGUES = {
    "premier league", "la liga", "bundesliga", "serie a", "ligue 1",
    "eredivisie", "primeira liga", "champions league", "europa league",
    "conference league", "brasileirao", "brasileirão", "campeonato brasileiro",
    "copa do brasil", "libertadores", "sul-americana",
    "mls", "liga mx", "j1 league", "k league", "a-league",
    "super lig", "ekstraklasa", "scottish premiership",
    "belgian pro league", "austrian bundesliga", "swiss super league",
    "danish superliga", "allsvenskan", "eliteserien",
    "saudi pro league", "nations league",
    "copa do mundo", "world cup", "fifa world cup", "copa mundial", "mundial", "fifa",
}

TENNIS_GOOD_KEYWORDS = {
    "atp", "wta", "grand slam", "australian open", "roland garros",
    "wimbledon", "us open", "challenger", "itf",
}

BLOCKED_KEYWORDS = {
    "u21", "u23", "u18", "reserve", "youth", "friendly", "amistoso",
    "pre-season", "ii liga", "division 3", "third division", "terceira",
    "gibraltar", "andorra", "faroe", "san marino", "liechtenstein",
    "women", "(w)", "(f)", "feminino", "femenino",
}

PENDING_FILE = "data/pending_opportunities.json"


@dataclass
class Opportunity:
    opp_id: str
    bet_type: str
    bet_key: str
    risk: str
    home: str
    away: str
    league: str
    market_id: str
    selection_id: int
    selection_label: str
    odds: float
    stake: float
    confidence: int
    reasoning: str
    potential_profit: float
    kickoff: str = ""
    sport: str = "football"
    legs: List[dict] = field(default_factory=list)
    combined_odds: float = 0.0
    leg2_stake_ratio: float = 0.0
    leg_stakes: List[float] = field(default_factory=list)
    event_id: str = ""
    favorite_odds: float | None = None
    model_probability: float | None = None
    market_probability: float | None = None
    ev_pct: float | None = None
    commission_rate: float = 0.065
    manual_override: bool = False
    reject_reason: str = ""
    back_size: float | None = None
    lay_price: float | None = None
    spread_pct: float | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


# Rejeições de qualidade em escanteios → Telegram com Apostar/Ignorar
QUALITY_OVERRIDE_REASONS = frozenset({
    "spread_too_wide",
    "insufficient_back_size",
    "wrong_odds",
})
CORNERS_OVERRIDE_KEYS = frozenset({"corners_105", "corners_under_105"})
OVERRIDE_NOTIFY_FILE = os.path.join("data", "notified_overrides.json")
MAX_QUALITY_OVERRIDES = 8


def _is_world_cup(league: str) -> bool:
    name = league.lower()
    return any(x in name for x in ("world cup", "fifa", "mundial", "copa do mundo"))


def _league_tier(league: str, sport: str = "football") -> str:
    name = league.lower()
    for kw in BLOCKED_KEYWORDS:
        if kw in name:
            return "blocked"
    if sport == "tennis":
        for kw in TENNIS_GOOD_KEYWORDS:
            if kw in name:
                return "good"
        return "unknown"
    for good in GOOD_LEAGUES:
        if good in name:
            return "good"
    return "unknown"


def _normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).lower())
    return " ".join(
        "".join(char for char in normalized if not unicodedata.combining(char))
        .replace("-", " ")
        .split()
    )


def _league_allowed(league: str, allowed_names: tuple[str, ...] | list[str]) -> bool:
    normalized = _normalize_name(league)
    return any(_normalize_name(name) in normalized for name in allowed_names)


def _has_corner_expectation(corner_stats: dict) -> bool:
    home = (corner_stats or {}).get("home") or {}
    away = (corner_stats or {}).get("away") or {}
    return float(home.get("avg_total") or 0) > 0 and float(away.get("avg_total") or 0) > 0


def _parse_participants(event_name: str) -> Tuple[str, str]:
    for sep in (" v ", " vs ", " @ "):
        if sep in event_name.lower():
            idx = event_name.lower().index(sep)
            a = event_name[:idx].strip()
            b = event_name[idx + len(sep):].strip()
            return a, b
    return "", ""


def _make_opp_id(market_id: str, selection_id: int, bet_key: str) -> str:
    raw = f"{market_id}:{selection_id}:{bet_key}"
    return hashlib.sha256(raw.encode()).hexdigest()[:10]


def _override_expires_at(kickoff: str) -> str:
    try:
        if kickoff:
            kick = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
            return (kick + timedelta(hours=2)).isoformat()
    except Exception:
        pass
    return (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()


def load_override_notified() -> dict:
    if not os.path.exists(OVERRIDE_NOTIFY_FILE):
        return {}
    try:
        with open(OVERRIDE_NOTIFY_FILE, encoding="utf-8") as handle:
            store = json.load(handle)
        now = datetime.now(timezone.utc)
        cleaned = {}
        for key, meta in (store or {}).items():
            expires = str((meta or {}).get("expires_at", ""))
            try:
                if expires and datetime.fromisoformat(expires) < now:
                    continue
            except Exception:
                pass
            cleaned[key] = meta
        return cleaned
    except Exception:
        return {}


def save_override_notified(store: dict) -> None:
    os.makedirs("data", exist_ok=True)
    with open(OVERRIDE_NOTIFY_FILE, "w", encoding="utf-8") as handle:
        json.dump(store, handle, indent=2, ensure_ascii=False)


def was_override_notified(opp_id: str) -> bool:
    return opp_id in load_override_notified()


def mark_override_notified(opp_id: str, kickoff: str = "", ignored: bool = False) -> None:
    store = load_override_notified()
    store[opp_id] = {
        "expires_at": _override_expires_at(kickoff),
        "ignored": bool(ignored),
        "marked_at": datetime.now(timezone.utc).isoformat(),
    }
    save_override_notified(store)


def _quality_reason_label(
    reason: str,
    odds: float,
    spread_pct: float | None,
    back_size: float | None,
    min_odds: float,
    max_odds: float,
) -> str:
    if reason == "spread_too_wide":
        spread_txt = f"{spread_pct:.1f}%" if spread_pct is not None else "?"
        return f"Spread largo ({spread_txt})"
    if reason == "insufficient_back_size":
        size_txt = f"R$ {back_size:.0f}" if back_size is not None else "?"
        return f"Liquidez baixa (back {size_txt})"
    if reason == "wrong_odds":
        return f"Odd fora da faixa ({odds:.2f}; alvo {min_odds:.2f}–{max_odds:.2f})"
    return reason.replace("_", " ")


class OpportunityScanner:
    def __init__(
        self,
        betfair_api,
        api_football: APIFootball,
        groq_key: str,
        stake: float | None = None,
        active_strategy: str | None = None,
        enabled_sports: list[str] | None = None,
        filter_mode: str = "auto",
    ):
        self.betfair = betfair_api
        self.api_football = api_football
        self.groq_keys = self._parse_groq_keys(groq_key)
        self.groq_key = self.groq_keys[0] if self.groq_keys else ""
        self._groq_key_index = 0
        self.stake = stake if stake is not None else get_manual_stake()
        self.active_strategy = active_strategy
        # auto = filtros estritos; semi/manual = mais sugestões
        self.filter_mode = filter_mode if filter_mode in ("auto", "semi", "manual") else "auto"
        self.max_per_profile = int(os.getenv("SCAN_MAX_PER_TYPE", "60"))
        self.max_results = int(os.getenv("SCAN_MAX_RESULTS", "10"))
        self.last_stats: dict = {}
        self._near_misses: List[Opportunity] = []
        self._quality_overrides: List[Opportunity] = []
        self.last_quality_overrides: List[Opportunity] = []
        self._betfair_error: str | None = None

    @staticmethod
    def _parse_groq_keys(raw: str) -> list[str]:
        keys: list[str] = []
        for part in str(raw or "").replace("\n", ",").split(","):
            key = part.strip()
            if key and key not in keys:
                keys.append(key)
        return keys

    def scan(self) -> List[Opportunity]:
        profiles = build_scan_profiles(self.active_strategy, filter_mode=self.filter_mode)
        logger.info(
            "Iniciando varredura (%d tipo(s), filtros=%s)...",
            len(profiles),
            self.filter_mode,
        )
        candidates: List[Opportunity] = []
        self._near_misses = []
        self._quality_overrides = []
        self.last_quality_overrides = []
        self._betfair_error = None
        stats: dict = {
            "markets_total": 0,
            "blocked_league": 0,
            "wrong_odds": 0,
            "low_volume": 0,
            "model_rejected": 0,
            "model_analyzed": 0,
            "quality_overrides": 0,
        }

        for profile in profiles:
            if self.filter_mode == "auto" and not profile.get("live_enabled", True):
                stats["disabled_by_validation"] = (
                    stats.get("disabled_by_validation", 0) + 1
                )
                logger.warning(
                    "[%s] bloqueada no auto: validação temporal insuficiente",
                    profile["label"],
                )
                continue
            profile_stake = profile.get("stake", self.stake)
            old_stake = self.stake
            self.stake = profile_stake
            try:
                if profile.get("kind") == "single":
                    found, partial = self._scan_profile(profile)
                elif profile.get("primary_optional_leg"):
                    found, partial = self._scan_primary_optional(profile)
                else:
                    found, partial = self._scan_combo(profile)
                candidates.extend(found)
                for k, v in partial.items():
                    stats[k] = stats.get(k, 0) + v
                logger.info("[%s] %d oportunidade(s) aprovada(s)", profile["label"], len(found))
            except Exception as e:
                logger.error("Erro no perfil %s: %s", profile["key"], e)
            finally:
                self.stake = old_stake
            time.sleep(0.3)

        candidates.sort(
            key=lambda o: (
                0 if _is_world_cup(o.league) else 1,
                0 if _league_tier(o.league, o.sport) == "good" else 1,
                -o.confidence,
                -o.potential_profit,
            ),
        )
        results = candidates[: self.max_results]
        if not results and self._near_misses:
            self._near_misses.sort(key=lambda o: -o.confidence)
            results = self._near_misses[:3]
            stats["fallback"] = len(results)
        stats["approved"] = sum(
            1 for opportunity in results if "⚠️" not in opportunity.bet_type
        )
        stats["review_suggestions"] = len(results) - stats["approved"]
        stats["model_analyzed"] = (
            stats.get("model_rejected", 0) + stats["approved"]
        )
        if stats.get("markets_total", 0) == 0 and self._betfair_error:
            stats["betfair_error"] = self._betfair_error
        overrides = self._select_quality_overrides(self._quality_overrides)
        self.last_quality_overrides = overrides
        stats["quality_overrides"] = len(overrides)
        self.last_stats = stats
        self._save_pending(results + overrides)
        logger.info(
            "Varredura concluída: %d oportunidade(s) + %d override(s) | stats=%s",
            len(results),
            len(overrides),
            stats,
        )
        return results

    def _prioritize_markets(self, markets: List[dict], sport: str) -> List[dict]:
        def sort_key(m: dict) -> tuple:
            league = m.get("competition", {}).get("name", "")
            tier = _league_tier(league, sport)
            tier_order = {"good": 0, "unknown": 1, "blocked": 2}.get(tier, 1)
            wc = 0 if _is_world_cup(league) else 1
            return (tier_order, wc, m.get("marketStartTime", ""))

        return sorted(markets, key=sort_key)

    def _odds_range(self, profile: dict, league: str) -> tuple[float, float]:
        """Faixa de odd por perna. Auto exige piso global; semi permite under mais baixo."""
        min_o = float(profile["min_odds"])
        max_o = float(profile["max_odds"])
        if self.filter_mode == "auto":
            min_o = max(min_o, MIN_GLOBAL_ODDS)
        elif profile["key"] not in ("corners_under_105", "corners_105"):
            min_o = max(min_o, MIN_GLOBAL_ODDS)
        return min_o, max_o

    def _scan_combo(self, profile: dict) -> tuple[List[Opportunity], dict]:
        """Múltipla mesmo jogo; se faltar escanteios, fallback para só Under 4.5."""
        leg1 = profile["leg1_profile"]
        leg2 = profile["leg2_profile"]
        min_combined = float(profile.get("min_combined_odds", 1.70))
        max_combined = float(profile.get("max_combined_odds", 3.00))
        min_conf = int(profile.get("min_confidence", 72))
        fallback_enabled = bool(profile.get("fallback_single_enabled", True))

        primary_markets = self._prioritize_markets(
            self._fetch_markets(leg1["market_type"], "1"), "football",
        )
        secondary_markets = self._fetch_markets(leg2["market_type"], "1")
        secondary_by_event: Dict[str, dict] = {}
        for m in secondary_markets:
            eid = str(m.get("event", {}).get("id", ""))
            if eid:
                secondary_by_event[eid] = m

        logger.info(
            "Mercados: %s=%d | %s=%d",
            leg1["market_type"], len(primary_markets),
            leg2["market_type"], len(secondary_markets),
        )

        approved: List[Opportunity] = []
        partial = {
            "markets_total": len(primary_markets),
            "corners_markets": len(secondary_markets),
            "combo_checked": 0,
            "fallback_u45_checked": 0,
            "blocked_league": 0,
            "no_leg2_market": 0,
            "fallback_u45": 0,
        }

        paired: list[tuple[dict, dict]] = []
        singles: list[dict] = []
        for mkt1 in primary_markets:
            league = mkt1.get("competition", {}).get("name", "")
            tier = _league_tier(league, "football")
            if tier == "blocked":
                partial["blocked_league"] += 1
                continue
            if profile.get("good_league_only") and tier != "good":
                partial["blocked_league"] += 1
                continue
            eid = str(mkt1.get("event", {}).get("id", ""))
            mkt2 = secondary_by_event.get(eid)
            if mkt2:
                paired.append((mkt1, mkt2))
            else:
                partial["no_leg2_market"] += 1
                if fallback_enabled:
                    singles.append(mkt1)

        for mkt1, mkt2 in paired[: self.max_per_profile]:
            partial["combo_checked"] = partial.get("combo_checked", 0) + 1
            opp, reason = self._evaluate_combo(
                mkt1, mkt2, leg1, leg2, profile, min_combined, max_combined, min_conf,
            )
            if opp:
                approved.append(opp)
            elif reason:
                partial[reason] = partial.get(reason, 0) + 1
            time.sleep(0.45)

        # Sem escanteios no jogo → aposta só Under 4.5
        if singles and fallback_enabled:
            remaining = max(0, self.max_per_profile - len(approved))
            single_profile = self._fallback_u45_profile(profile, leg1)
            old_stake = self.stake
            self.stake = float(
                profile.get("fallback_single_stake")
                or single_profile.get("stake")
                or (old_stake / 2)
            )
            try:
                for mkt1 in singles[:remaining]:
                    partial["fallback_u45_checked"] += 1
                    opp, reason = self._evaluate_market(mkt1, single_profile)
                    if opp:
                        approved.append(opp)
                        partial["fallback_u45"] += 1
                        logger.info(
                            "Fallback U4.5: %s x %s @ %.2f (sem mercado de escanteios)",
                            opp.home, opp.away, opp.odds,
                        )
                    elif reason:
                        key = f"fallback_{reason}"
                        partial[key] = partial.get(key, 0) + 1
                    time.sleep(0.25)
            finally:
                self.stake = old_stake

        return approved, partial

    def _scan_primary_optional(self, profile: dict) -> tuple[List[Opportunity], dict]:
        """U10.5 principal; anexa U4.5 somente quando todos os filtros próprios passam."""
        corner_leg = profile["leg1_profile"]
        goal_leg = profile["leg2_profile"]
        corner_markets = self._prioritize_markets(
            self._fetch_markets(corner_leg["market_type"], "1"), "football",
        )
        goal_markets = self._fetch_markets(goal_leg["market_type"], "1", hours=72)
        goals_by_event = {
            str(market.get("event", {}).get("id", "")): market
            for market in goal_markets
            if market.get("event", {}).get("id")
        }
        stats = {
            "markets_total": len(corner_markets),
            "corners_markets": len(corner_markets),
            "goal_markets": len(goal_markets),
            "corner_approved": 0,
            "u45_added": 0,
            "u45_no_market": 0,
            "u45_league_rejected": 0,
            "u45_favorite_rejected": 0,
            "u45_model_rejected": 0,
        }
        approved: List[Opportunity] = []
        corner_stake = float(profile.get("corner_stake", 2.0))
        goal_stake = float(profile.get("goal_stake", 2.0))

        for corner_market in corner_markets[: self.max_per_profile]:
            league = corner_market.get("competition", {}).get("name", "")
            if _league_tier(league, "football") == "blocked":
                stats["blocked_league"] = stats.get("blocked_league", 0) + 1
                continue
            corner_profile = self._optional_leg_profile(
                profile, corner_leg, corner_stake, profile["leg1_short"], "corners",
            )
            corner_opp, reason = self._evaluate_market(corner_market, corner_profile)
            if not corner_opp:
                if reason:
                    stats[reason] = stats.get(reason, 0) + 1
                continue

            corner_opp.bet_key = profile["key"]
            corner_opp.bet_type = f"{profile['label']} (somente U10.5)"
            corner_opp.opp_id = _make_opp_id(
                corner_market["marketId"], corner_opp.selection_id, profile["key"],
            )
            corner_opp.leg_stakes = [corner_stake]
            stats["corner_approved"] += 1
            event_id = corner_opp.event_id
            goal_market = goals_by_event.get(event_id)
            if not goal_market:
                stats["u45_no_market"] += 1
                approved.append(corner_opp)
                continue

            if not _league_allowed(league, profile.get("u45_leagues", ())):
                stats["u45_league_rejected"] += 1
                record_snapshot(
                    profile["key"], goal_market, None, None, "", "REJECTED",
                    "u45_league_not_allowed", leg_key="goals",
                )
                approved.append(corner_opp)
                continue

            match_market, match_book, favorite = self._match_odds_favorite(event_id)
            threshold = float(profile.get("favorite_min_odds", 1.40))
            if not self._favorite_allows_u45(favorite, threshold):
                favorite_odds = float(favorite[2]) if favorite else None
                reason = (
                    f"favorite_below_{threshold:.2f}"
                    if favorite else "favorite_price_unavailable"
                )
                stats["u45_favorite_rejected"] += 1
                record_snapshot(
                    profile["key"], goal_market, None, None, "", "REJECTED", reason,
                    favorite_odds=favorite_odds, leg_key="goals",
                )
                if match_market:
                    record_snapshot(
                        profile["key"], match_market, match_book,
                        int(favorite[0]) if favorite else None,
                        str(favorite[1]) if favorite else "",
                        "REJECTED", reason, favorite_odds=favorite_odds,
                        leg_key="match_odds_gate",
                    )
                approved.append(corner_opp)
                continue

            favorite_odds = float(favorite[2])
            record_snapshot(
                profile["key"], match_market, match_book, int(favorite[0]), str(favorite[1]),
                "APPROVED", f"favorite_odds_{favorite_odds:.2f}",
                favorite_odds=favorite_odds, leg_key="match_odds_gate",
            )
            goal_profile = self._optional_leg_profile(
                profile, goal_leg, goal_stake, profile["leg2_short"], "goals",
            )
            goal_profile["favorite_odds"] = favorite_odds
            goal_opp, goal_reason = self._evaluate_market(goal_market, goal_profile)
            if not goal_opp:
                stats["u45_model_rejected"] += 1
                if goal_reason:
                    stats[f"u45_{goal_reason}"] = stats.get(f"u45_{goal_reason}", 0) + 1
                approved.append(corner_opp)
                continue

            approved.append(
                self._combine_optional_legs(
                    profile, corner_opp, goal_opp, corner_stake, goal_stake, favorite_odds,
                )
            )
            stats["u45_added"] += 1
            time.sleep(0.25)
        return approved, stats

    @staticmethod
    def _favorite_allows_u45(
        favorite: tuple[int, str, float] | None,
        threshold: float = 1.40,
    ) -> bool:
        return bool(favorite and float(favorite[2]) >= float(threshold))

    @staticmethod
    def _optional_leg_profile(
        combo_profile: dict,
        leg: dict,
        stake: float,
        label: str,
        leg_key: str,
    ) -> dict:
        return {
            **leg,
            "key": combo_profile["key"],
            "model_key": leg.get("key", combo_profile["key"]),
            "kind": "single",
            "label": label,
            "risk": "médio",
            "stake": stake,
            "min_confidence": int(combo_profile.get("min_confidence", 60)),
            "good_league_only": False,
            "require_stats": True,
            "commission_rate": float(combo_profile.get("commission_rate", 0.065)),
            "max_spread_pct": float(combo_profile.get("max_spread_pct", 10.0)),
            "min_back_size": float(combo_profile.get("min_back_size", 10.0)),
            "min_ev_pct": float(combo_profile.get("min_ev_pct", 2.0)),
            "min_probability_edge_pct": float(
                combo_profile.get("min_probability_edge_pct", 2.0)
            ),
            "leg_key": leg_key,
        }

    def _match_odds_favorite(
        self, event_id: str,
    ) -> tuple[dict | None, dict | None, tuple[int, str, float] | None]:
        try:
            markets = self.betfair.list_market_catalogue_complete(
                filter_dict={
                    "eventIds": [str(event_id)],
                    "marketTypeCodes": ["MATCH_ODDS"],
                },
                market_projection=[
                    "COMPETITION", "EVENT", "RUNNER_DESCRIPTION",
                    "MARKET_START_TIME", "MARKET_DESCRIPTION",
                ],
                max_results=20,
                slice_hours=12,
            ) or []
        except Exception as exc:
            logger.warning("MATCH_ODDS indisponível para evento %s: %s", event_id, exc)
            return None, None, None
        if not markets:
            return None, None, None
        market = markets[0]
        book = self._get_book(market["marketId"])
        if not book:
            return market, None, None
        return market, book, self._pick_favorite(market.get("runners", []), book)

    @staticmethod
    def _combine_optional_legs(
        profile: dict,
        corner: Opportunity,
        goal: Opportunity,
        corner_stake: float,
        goal_stake: float,
        favorite_odds: float,
    ) -> Opportunity:
        commission = float(profile.get("commission_rate", 0.065))
        legs = [
            {
                "key": "corners",
                "market_id": corner.market_id,
                "selection_id": corner.selection_id,
                "odds": corner.odds,
                "stake": corner_stake,
                "label": f"{profile['leg1_short']} @ {corner.odds:.2f}",
            },
            {
                "key": "goals",
                "market_id": goal.market_id,
                "selection_id": goal.selection_id,
                "odds": goal.odds,
                "stake": goal_stake,
                "label": f"{profile['leg2_short']} @ {goal.odds:.2f}",
            },
        ]
        total_stake = round(corner_stake + goal_stake, 2)
        profit = round(
            (
                corner_stake * (corner.odds - 1)
                + goal_stake * (goal.odds - 1)
            ) * (1 - commission),
            2,
        )
        return Opportunity(
            opp_id=_make_opp_id(corner.market_id, corner.selection_id, profile["key"]),
            bet_type=profile["label"],
            bet_key=profile["key"],
            risk="médio",
            home=corner.home,
            away=corner.away,
            league=corner.league,
            market_id=corner.market_id,
            selection_id=corner.selection_id,
            selection_label=f"{legs[0]['label']} + {legs[1]['label']}",
            odds=round(corner.odds * goal.odds, 3),
            stake=total_stake,
            confidence=min(corner.confidence, goal.confidence),
            reasoning=(
                f"U10.5: {corner.reasoning} U4.5: {goal.reasoning} "
                f"Favorito MATCH_ODDS @ {favorite_odds:.2f}."
            )[:400],
            potential_profit=profit,
            kickoff=corner.kickoff,
            legs=legs,
            combined_odds=round(corner.odds * goal.odds, 3),
            leg_stakes=[corner_stake, goal_stake],
            event_id=corner.event_id,
            favorite_odds=favorite_odds,
            model_probability=min(
                float(corner.model_probability or 0), float(goal.model_probability or 0)
            ),
            market_probability=min(
                float(corner.market_probability or 0), float(goal.market_probability or 0)
            ),
            ev_pct=min(float(corner.ev_pct or 0), float(goal.ev_pct or 0)),
            commission_rate=commission,
        )

    def _fallback_u45_profile(self, combo_profile: dict, leg1: dict) -> dict:
        """Perfil de aposta simples Under 4.5 quando falta a perna de escanteios."""
        min_odds = float(
            combo_profile.get("leg1_min_odds")
            or leg1.get("min_odds")
            or 1.15
        )
        max_odds = float(leg1.get("max_odds") or 1.50)
        stake = float(
            combo_profile.get("fallback_single_stake")
            or (float(combo_profile.get("stake", 40.0)) / 2)
        )
        return {
            "key": "under45",
            "kind": "single",
            "label": "Menos 4.5 gols (sem escanteios)",
            "market_type": leg1["market_type"],
            "selection_hint": leg1["selection_hint"],
            "min_odds": min_odds,
            "max_odds": max_odds,
            "min_confidence": int(combo_profile.get("min_confidence", 60)),
            "min_volume": float(combo_profile.get("min_volume", 300)),
            "good_league_only": bool(combo_profile.get("good_league_only", False)),
            "require_stats": False,
            "prompt_goal": "Menos de 4.5 gols no jogo (máximo 4 gols).",
            "risk": "médio",
            "stake": stake,
            "sport": "football",
            "event_type_id": "1",
        }

    def _evaluate_combo(
        self, mkt1, mkt2, leg1, leg2, combo_profile,
        min_combined, max_combined, min_conf,
    ) -> tuple[Optional[Opportunity], Optional[str]]:
        event = mkt1.get("event", {})
        league = mkt1.get("competition", {}).get("name", "")
        home, away = _parse_participants(event.get("name", ""))
        if not home or not away:
            return None, "bad_event"

        book1 = self._get_book(mkt1["marketId"])
        book2 = self._get_book(mkt2["marketId"])
        if not book1 or not book2:
            return None, "no_book"

        sel1 = self._pick_selection(mkt1, book1, leg1)
        sel2 = self._pick_selection(mkt2, book2, leg2)
        if not sel1 or not sel2:
            return None, "no_selection"

        id1, label1, odds1 = sel1
        id2, label2, odds2 = sel2

        def _absolute_leg_stake(leg: dict) -> float:
            key = "corner_stake" if "CORNR" in str(leg.get("market_type", "")) else "goal_stake"
            value = combo_profile.get(key)
            if value is not None:
                return float(value)
            return float(combo_profile.get("stake", self.stake)) / 2

        stake1 = _absolute_leg_stake(leg1)
        stake2 = _absolute_leg_stake(leg2)
        quality1 = execution_quality(
            book1, id1, stake1,
            max_spread_pct=float(combo_profile.get("max_spread_pct", 10)),
            min_back_size=float(combo_profile.get("min_back_size", 10)),
        )
        quality2 = execution_quality(
            book2, id2, stake2,
            max_spread_pct=float(combo_profile.get("max_spread_pct", 10)),
            min_back_size=float(combo_profile.get("min_back_size", 10)),
        )
        if not quality1.allowed or not quality2.allowed:
            record_snapshot(
                combo_profile["key"], mkt1, book1, id1, label1,
                "REJECTED", quality1.reason, leg_key=leg1.get("key", "leg1"),
            )
            record_snapshot(
                combo_profile["key"], mkt2, book2, id2, label2,
                "REJECTED", quality2.reason, leg_key=leg2.get("key", "leg2"),
            )
            return None, "execution_quality"
        min1, max1 = self._odds_range(leg1, league)
        min2, max2 = self._odds_range(leg2, league)
        if not (min1 <= odds1 <= max1 and min2 <= odds2 <= max2):
            logger.info(
                "Odd fora da faixa %s x %s: %.2f [%.2f-%.2f] / %.2f [%.2f-%.2f]",
                home, away, odds1, min1, max1, odds2, min2, max2,
            )
            record_snapshot(
                combo_profile["key"], mkt1, book1, id1, label1,
                "REJECTED", "wrong_odds",
            )
            record_snapshot(
                combo_profile["key"], mkt2, book2, id2, label2,
                "REJECTED", "wrong_odds",
            )
            return None, "wrong_odds"

        combined = round(odds1 * odds2, 3)
        if not (min_combined <= combined <= max_combined):
            logger.info(
                "Combinada fora da faixa %s x %s: %.3f [%.2f-%.2f]",
                home, away, combined, min_combined, max_combined,
            )
            record_snapshot(
                combo_profile["key"], mkt1, book1, id1, label1,
                "REJECTED", "portfolio_price_range",
            )
            record_snapshot(
                combo_profile["key"], mkt2, book2, id2, label2,
                "REJECTED", "portfolio_price_range",
            )
            return None, "wrong_combined"

        needs_corners = combo_profile.get("needs_corners_stats", False)
        home_stats, away_stats, h2h, has_stats, corner_stats = self._get_stats(
            home, away, needs_corners,
        )
        model_defaults = {
            "commission_rate": combo_profile.get("commission_rate", 0.065),
            "min_ev_pct": combo_profile.get("min_ev_pct", 2.0),
            "min_probability_edge_pct": combo_profile.get(
                "min_probability_edge_pct", 2.0
            ),
        }
        analysis1 = assess_value(
            {**leg1, **model_defaults}, odds1, book1, id1,
            home_stats, away_stats, corner_stats,
        )
        analysis2 = assess_value(
            {**leg2, **model_defaults}, odds2, book2, id2,
            home_stats, away_stats, corner_stats,
        )
        if not analysis1.get("recommend") or not analysis2.get("recommend"):
            record_snapshot(
                combo_profile["key"], mkt1, book1, id1, label1,
                "REJECTED", str(analysis1.get("reasoning", "")),
            )
            record_snapshot(
                combo_profile["key"], mkt2, book2, id2, label2,
                "REJECTED", str(analysis2.get("reasoning", "")),
            )
            return None, "model_rejected"

        stake = round(stake1 + stake2, 2)
        key = combo_profile["key"]
        commission = float(combo_profile.get("commission_rate", 0.065))
        profit = round(
            (
                stake1 * (odds1 - 1)
                + stake2 * (odds2 - 1)
            ) * (1 - commission),
            2,
        )
        confidence = min(
            int(analysis1.get("confidence", 0)),
            int(analysis2.get("confidence", 0)),
        )
        legs = [
            {
                "key": "leg1",
                "market_id": mkt1["marketId"],
                "selection_id": id1,
                "odds": odds1,
                "stake": stake1,
                "label": f"{combo_profile['leg1_short']} @ {odds1:.2f}",
            },
            {
                "key": "leg2",
                "market_id": mkt2["marketId"],
                "selection_id": id2,
                "odds": odds2,
                "stake": stake2,
                "label": f"{combo_profile['leg2_short']} @ {odds2:.2f}",
            },
        ]
        opp_id = _make_opp_id(mkt1["marketId"], id2, key)
        record_snapshot(
            key, mkt1, book1, id1, label1, "APPROVED", analysis1["reasoning"],
            leg_key=leg1.get("key", "leg1"),
        )
        record_snapshot(
            key, mkt2, book2, id2, label2, "APPROVED", analysis2["reasoning"],
            leg_key=leg2.get("key", "leg2"),
        )

        return Opportunity(
            opp_id=opp_id,
            bet_type=combo_profile["label"],
            bet_key=key,
            risk="médio",
            home=home,
            away=away,
            league=league,
            market_id=mkt1["marketId"],
            selection_id=id1,
            selection_label=f"{combo_profile['leg1_short']} @ {odds1:.2f} × {combo_profile['leg2_short']} @ {odds2:.2f}",
            odds=combined,
            combined_odds=combined,
            stake=stake,
            confidence=confidence,
            reasoning=(
                f"U4.5: {analysis1['reasoning']} "
                f"U10.5: {analysis2['reasoning']}"
            )[:400],
            potential_profit=profit,
            kickoff=mkt1.get("marketStartTime", ""),
            sport="football",
            legs=legs,
            leg_stakes=[stake1, stake2],
            event_id=str(event.get("id", "")),
            model_probability=min(
                float(analysis1.get("model_probability") or 0),
                float(analysis2.get("model_probability") or 0),
            ),
            market_probability=min(
                float(analysis1.get("market_probability") or 0),
                float(analysis2.get("market_probability") or 0),
            ),
            ev_pct=min(
                float(analysis1.get("ev_pct") or 0),
                float(analysis2.get("ev_pct") or 0),
            ),
            commission_rate=commission,
        ), None

    def _analyze_groq_combo(
        self, combo_profile, home, away, league,
        leg1_name, odds1, leg2_name, odds2, combined,
        home_stats, away_stats, h2h, corner_stats, has_stats,
    ) -> Optional[dict]:
        if not self.groq_keys:
            return self._heuristic_fallback()
        stats_block = ""
        if has_stats:
            ha = float(home_stats.get("avg_scored_total") or 0)
            hd = float(home_stats.get("avg_conceded_total") or 0)
            aa = float(away_stats.get("avg_scored_total") or 0)
            ad = float(away_stats.get("avg_conceded_total") or 0)
            stats_block = (
                f"Gols — {home}: {ha:.1f} marcados / {hd:.1f} sofridos | "
                f"{away}: {aa:.1f} / {ad:.1f}\n"
                f"H2H média gols: {h2h.get('avg_goals_per_game', 'N/A')}\n"
            )
        if corner_stats:
            hc = corner_stats.get("home", {})
            ac = corner_stats.get("away", {})
            stats_block += (
                f"Escanteios médios — {home}: {hc.get('avg_total', '?')}, "
                f"{away}: {ac.get('avg_total', '?')}\n"
            )

        prompt = f"""Analise esta MÚLTIPLA no mesmo jogo (as duas seleções devem bater):

JOGO: {home} x {away}
LIGA: {league}
MÚLTIPLA: {combo_profile['label']}
PERNA 1: {leg1_name} @ {odds1}
PERNA 2: {leg2_name} @ {odds2}
ODD COMBINADA: {combined}

{stats_block}
{combo_profile.get('ia_hint', '')}

Só recommend=true se AMBAS as pernas forem razoáveis e a odd combinada compensar o risco.

JSON:
{{"confidence": 0-100, "recommend": true/false, "reasoning": "2 frases em português"}}"""

        return self._call_groq(prompt)

    def _scan_profile(self, profile: dict) -> tuple[List[Opportunity], dict]:
        sport = profile.get("sport", "football")
        markets = self._prioritize_markets(
            self._fetch_markets(profile["market_type"], profile.get("event_type_id", "1")),
            sport,
        )
        approved: List[Opportunity] = []
        partial = {"markets_total": len(markets)}

        for mkt in markets[: self.max_per_profile]:
            opp, reason = self._evaluate_market(mkt, profile)
            if opp:
                approved.append(opp)
            elif reason:
                partial[reason] = partial.get(reason, 0) + 1
            time.sleep(0.25)

        return approved, partial

    def _fetch_markets(
        self, market_type: str, event_type_id: str, hours: int | None = None,
    ) -> List[dict]:
        now = datetime.now(timezone.utc)
        # Escanteios são raros na Betfair BR — janela maior
        hours = hours or (72 if "CORNR" in market_type else 24)
        try:
            markets = self.betfair.list_market_catalogue_complete(
                filter_dict={
                    "eventTypeIds": [event_type_id],
                    "marketTypeCodes": [market_type],
                    "marketStartTime": {
                        "from": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "to": (now + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                },
                market_projection=[
                    "COMPETITION", "EVENT", "RUNNER_DESCRIPTION",
                    "MARKET_START_TIME", "MARKET_DESCRIPTION",
                ],
                max_results=200,
                slice_hours=12,
            )
            found = markets or []
            logger.info("Busca %s (%dh): %d mercado(s)", market_type, hours, len(found))
            return found
        except Exception as e:
            logger.error("Erro ao buscar %s: %s", market_type, e)
            self._betfair_error = str(e)
            return []

    def _evaluate_market(self, mkt: dict, profile: dict) -> tuple[Optional[Opportunity], Optional[str]]:
        sport = profile.get("sport", "football")
        market_stake = float(profile.get("stake", self.stake))
        event = mkt.get("event", {})
        comp = mkt.get("competition", {})
        league = comp.get("name", "")
        tier = _league_tier(league, sport)

        if tier == "blocked":
            return None, "blocked_league"
        if profile.get("good_league_only") and tier != "good":
            return None, "blocked_league"
        if profile.get("use_u45_allowlist") and not u45_league_allowed(league):
            record_snapshot(
                profile["key"], mkt, None, None, "",
                "REJECTED", "u45_league_not_allowed",
                leg_key=profile.get("leg_key", "goals"),
            )
            return None, "blocked_league"

        home, away = _parse_participants(event.get("name", ""))
        if not home or not away:
            return None, "bad_event"

        book = self._get_book(mkt["marketId"])
        if not book:
            return None, "no_book"

        selection = self._pick_selection(mkt, book, profile)
        if not selection:
            record_snapshot(
                profile["key"], mkt, book, None, "",
                "REJECTED", "no_selection",
                favorite_odds=profile.get("favorite_odds"),
                leg_key=profile.get("leg_key", profile["key"]),
            )
            return None, "no_selection"

        sel_id, sel_label, odds = selection
        quality = execution_quality(
            book,
            sel_id,
            market_stake,
            max_spread_pct=float(profile.get("max_spread_pct", 10)),
            min_back_size=float(profile.get("min_back_size", 10)),
        )
        if not quality.allowed:
            record_snapshot(
                profile["key"], mkt, book, sel_id, sel_label,
                "REJECTED", quality.reason,
                favorite_odds=profile.get("favorite_odds"),
                leg_key=profile.get("leg_key", profile["key"]),
            )
            self._maybe_quality_override(
                mkt, profile, home, away, league, sel_id, sel_label,
                quality.back_price or odds, quality.reason,
                back_size=quality.back_size,
                lay_price=quality.lay_price,
                spread_pct=quality.spread_pct,
            )
            return None, "execution_quality"
        min_o, max_o = self._odds_range(profile, league)
        if odds < MIN_GLOBAL_ODDS and profile["key"] not in ("corners_105", "corners_under_105"):
            record_snapshot(
                profile["key"], mkt, book, sel_id, sel_label,
                "REJECTED", "below_global_odds",
                favorite_odds=profile.get("favorite_odds"),
                leg_key=profile.get("leg_key", profile["key"]),
            )
            return None, "wrong_odds"
        if not (min_o <= odds <= max_o):
            record_snapshot(
                profile["key"], mkt, book, sel_id, sel_label,
                "REJECTED", "wrong_odds",
                favorite_odds=profile.get("favorite_odds"),
                leg_key=profile.get("leg_key", profile["key"]),
            )
            self._maybe_quality_override(
                mkt, profile, home, away, league, sel_id, sel_label,
                odds, "wrong_odds",
                back_size=quality.back_size,
                lay_price=quality.lay_price,
                spread_pct=quality.spread_pct,
            )
            return None, "wrong_odds"

        if profile.get("favorite_min_odds") and profile.get("use_u45_allowlist"):
            event_id = str(event.get("id", ""))
            match_market, match_book, favorite = self._match_odds_favorite(event_id)
            threshold = float(profile.get("favorite_min_odds", 1.40))
            if not self._favorite_allows_u45(favorite, threshold):
                favorite_odds = float(favorite[2]) if favorite else None
                reason = (
                    f"favorite_below_{threshold:.2f}"
                    if favorite else "favorite_price_unavailable"
                )
                record_snapshot(
                    profile["key"], mkt, book, sel_id, sel_label,
                    "REJECTED", reason, favorite_odds=favorite_odds,
                    leg_key=profile.get("leg_key", "goals"),
                )
                if match_market:
                    record_snapshot(
                        profile["key"], match_market, match_book,
                        int(favorite[0]) if favorite else None,
                        str(favorite[1]) if favorite else "",
                        "REJECTED", reason, favorite_odds=favorite_odds,
                        leg_key="match_odds_gate",
                    )
                return None, "favorite_rejected"
            profile = dict(profile)
            profile["favorite_odds"] = float(favorite[2])

        if sport == "tennis":
            analysis = self._analyze_groq_tennis(
                profile, home, away, league, odds, sel_label,
            )
            has_stats = False
        else:
            model_key = str(profile.get("model_key") or profile.get("key", ""))
            needs_corners = (
                "corner" in model_key
                or "CORNR" in str(profile.get("market_type", ""))
                or "esc" in profile.get("label", "").lower()
            )
            home_stats, away_stats, h2h, has_stats, corner_stats = self._get_stats(
                home, away, needs_corners,
            )
            missing_stats = (
                (needs_corners and not _has_corner_expectation(corner_stats))
                or (not needs_corners and not has_stats)
            )
            if profile.get("require_stats") and missing_stats:
                record_snapshot(
                    profile["key"], mkt, book, sel_id, sel_label,
                    "REJECTED", "missing_independent_stats",
                    favorite_odds=profile.get("favorite_odds"),
                    leg_key=profile.get("leg_key", profile["key"]),
                )
                return None, "model_rejected"
            analysis = assess_value(
                profile, odds, book, sel_id,
                home_stats, away_stats, corner_stats,
            )

        if not analysis:
            return None, "model_rejected"

        confidence = int(analysis.get("confidence", 0))
        extra = 0
        if not profile.get("authorize_on_price_band"):
            extra = 2 if not has_stats else 0
            if tier == "unknown":
                extra += 2
        min_conf = profile["min_confidence"] + extra
        if confidence < min_conf:
            record_snapshot(
                profile["key"], mkt, book, sel_id, sel_label,
                "REJECTED", str(analysis.get("reasoning", "confidence")),
                favorite_odds=profile.get("favorite_odds"),
                leg_key=profile.get("leg_key", profile["key"]),
            )
            self._maybe_near_miss(
                mkt, profile, home, away, league, sel_id, sel_label, odds,
                confidence, analysis, sport, kickoff=mkt.get("marketStartTime", ""),
            )
            return None, "model_rejected"

        if analysis.get("recommend") is False:
            record_snapshot(
                profile["key"], mkt, book, sel_id, sel_label,
                "REJECTED", str(analysis.get("reasoning", "model_rejected")),
                favorite_odds=profile.get("favorite_odds"),
                leg_key=profile.get("leg_key", profile["key"]),
            )
            self._maybe_near_miss(
                mkt, profile, home, away, league, sel_id, sel_label, odds,
                confidence, analysis, sport, kickoff=mkt.get("marketStartTime", ""),
            )
            return None, "model_rejected"

        kickoff = mkt.get("marketStartTime", "")
        commission = float(profile.get("commission_rate", 0.065))
        profit = round(market_stake * (odds - 1) * (1 - commission), 2)
        record_snapshot(
            profile["key"], mkt, book, sel_id, sel_label,
            "APPROVED", str(analysis.get("reasoning", "")),
            favorite_odds=profile.get("favorite_odds"),
            leg_key=profile.get("leg_key", profile["key"]),
        )

        return Opportunity(
            opp_id=_make_opp_id(mkt["marketId"], sel_id, profile["key"]),
            bet_type=profile["label"],
            bet_key=profile["key"],
            risk=profile["risk"],
            home=home,
            away=away,
            league=league,
            market_id=mkt["marketId"],
            selection_id=sel_id,
            selection_label=sel_label,
            odds=odds,
            stake=market_stake,
            confidence=confidence,
            reasoning=str(analysis.get("reasoning", ""))[:400],
            potential_profit=profit,
            kickoff=kickoff,
            sport=sport,
            event_id=str(event.get("id", "")),
            model_probability=analysis.get("model_probability"),
            market_probability=analysis.get("market_probability"),
            ev_pct=analysis.get("ev_pct"),
            commission_rate=commission,
            favorite_odds=profile.get("favorite_odds"),
            leg_stakes=[market_stake],
        ), None

    def _maybe_near_miss(self, mkt, profile, home, away, league, sel_id, sel_label, odds,
                         confidence, analysis, sport, kickoff):
        if confidence < 55:
            return
        nm = self._near_miss_from(
            mkt, profile, home, away, league, sel_id, sel_label, odds,
            confidence, analysis, sport, kickoff,
        )
        if nm:
            self._near_misses.append(nm)

    def _maybe_quality_override(
        self,
        mkt: dict,
        profile: dict,
        home: str,
        away: str,
        league: str,
        sel_id: int,
        sel_label: str,
        odds: float,
        reason: str,
        *,
        back_size: float | None = None,
        lay_price: float | None = None,
        spread_pct: float | None = None,
    ) -> None:
        if profile.get("key") not in CORNERS_OVERRIDE_KEYS:
            return
        if reason not in QUALITY_OVERRIDE_REASONS:
            return
        if not odds or odds <= 1.01:
            return
        opp = self._quality_override_from(
            mkt, profile, home, away, league, sel_id, sel_label, odds, reason,
            back_size=back_size, lay_price=lay_price, spread_pct=spread_pct,
        )
        if opp and not was_override_notified(opp.opp_id):
            self._quality_overrides.append(opp)

    def _quality_override_from(
        self,
        mkt: dict,
        profile: dict,
        home: str,
        away: str,
        league: str,
        sel_id: int,
        sel_label: str,
        odds: float,
        reason: str,
        *,
        back_size: float | None = None,
        lay_price: float | None = None,
        spread_pct: float | None = None,
    ) -> Optional[Opportunity]:
        market_stake = float(profile.get("stake", self.stake))
        commission = float(profile.get("commission_rate", 0.065))
        profit = round(market_stake * (odds - 1) * (1 - commission), 2)
        min_o = float(profile.get("min_odds", 1.40))
        max_o = float(profile.get("max_odds", 1.73))
        reason_label = _quality_reason_label(
            reason, odds, spread_pct, back_size, min_o, max_o,
        )
        details = [
            f"Motivo: {reason_label}",
            f"Back @{odds:.2f}",
        ]
        if lay_price:
            details.append(f"Lay @{lay_price:.2f}")
        if spread_pct is not None:
            details.append(f"Spread {spread_pct:.1f}%")
        if back_size is not None:
            details.append(f"Liquidez back R$ {back_size:.0f}")
        details.append("Bot não apostou sozinho — confirme se quiser entrar.")
        kickoff = mkt.get("marketStartTime", "")
        return Opportunity(
            opp_id=_make_opp_id(mkt["marketId"], sel_id, f"{profile['key']}:override"),
            bet_type=f"🔧 Override · {profile['label']}",
            bet_key=profile["key"],
            risk="médio",
            home=home,
            away=away,
            league=league,
            market_id=mkt["marketId"],
            selection_id=sel_id,
            selection_label=sel_label,
            odds=float(odds),
            stake=market_stake,
            confidence=50,
            reasoning=" | ".join(details)[:400],
            potential_profit=profit,
            kickoff=kickoff,
            sport=profile.get("sport", "football"),
            event_id=str(mkt.get("event", {}).get("id", "")),
            commission_rate=commission,
            leg_stakes=[market_stake],
            manual_override=True,
            reject_reason=reason,
            back_size=float(back_size) if back_size is not None else None,
            lay_price=float(lay_price) if lay_price else None,
            spread_pct=float(spread_pct) if spread_pct is not None else None,
        )

    def _select_quality_overrides(self, overrides: List[Opportunity]) -> List[Opportunity]:
        if not overrides:
            return []
        unique: dict[str, Opportunity] = {}
        for opp in overrides:
            unique[opp.opp_id] = opp

        def sort_key(opp: Opportunity) -> tuple:
            tier = _league_tier(opp.league, opp.sport)
            tier_rank = 0 if tier == "good" else 1
            # Prefer odds closer to the usual corners band midpoint (~1.56)
            distance = abs(float(opp.odds) - 1.56)
            return (tier_rank, distance, -(opp.back_size or 0))

        ranked = sorted(unique.values(), key=sort_key)
        return ranked[:MAX_QUALITY_OVERRIDES]

    def _near_miss_from(
        self, mkt, profile, home, away, league, sel_id, sel_label, odds,
        confidence, analysis, sport, kickoff,
    ) -> Optional[Opportunity]:
        reason = str(analysis.get("reasoning", "Modelo não recomendou"))[:400]
        market_stake = float(profile.get("stake", self.stake))
        commission = float(profile.get("commission_rate", 0.065))
        profit = round(market_stake * (odds - 1) * (1 - commission), 2)
        return Opportunity(
            opp_id=_make_opp_id(mkt["marketId"], sel_id, profile["key"]),
            bet_type=f"⚠️ {profile['label']}",
            bet_key=profile["key"],
            risk="médio",
            home=home,
            away=away,
            league=league,
            market_id=mkt["marketId"],
            selection_id=sel_id,
            selection_label=sel_label,
            odds=odds,
            stake=market_stake,
            confidence=confidence,
            reasoning=f"Modelo rejeitou — apenas para revisão: {reason}",
            potential_profit=profit,
            kickoff=kickoff or mkt.get("marketStartTime", ""),
            sport=sport,
            event_id=str(mkt.get("event", {}).get("id", "")),
            model_probability=analysis.get("model_probability"),
            market_probability=analysis.get("market_probability"),
            ev_pct=analysis.get("ev_pct"),
            commission_rate=commission,
            leg_stakes=[market_stake],
        )

    def _pick_selection(
        self, catalogue: dict, book: dict, profile: dict
    ) -> Optional[Tuple[int, str, float]]:
        runners_desc = catalogue.get("runners", [])
        hint = profile["selection_hint"]

        if hint == "favorite":
            return self._pick_favorite(runners_desc, book)

        target_id = None
        target_label = ""
        for rd in runners_desc:
            nm = rd.get("runnerName", "").lower()
            if hint == "under" and any(word in nm for word in ("under", "menos")):
                target_id = rd.get("selectionId")
                target_label = rd.get("runnerName", "Under")
                break
            if hint == "over" and any(word in nm for word in ("over", "mais")):
                target_id = rd.get("selectionId")
                target_label = rd.get("runnerName", "Over")
                break
            if hint == "no" and nm in ("no", "não", "nao"):
                target_id = rd.get("selectionId")
                target_label = rd.get("runnerName", "No")
                break

        if not target_id:
            return None

        for runner in book.get("runners", []):
            if runner.get("selectionId") == target_id:
                backs = runner.get("ex", {}).get("availableToBack", [])
                if backs:
                    return target_id, target_label, float(backs[0].get("price", 0))
        return None

    def _pick_favorite(
        self, runners_desc: List[dict], book: dict
    ) -> Optional[Tuple[int, str, float]]:
        best = None
        for rd in runners_desc:
            name = rd.get("runnerName", "")
            low = name.lower()
            if low in ("the draw", "empate", "draw"):
                continue
            sel_id = rd.get("selectionId")
            for runner in book.get("runners", []):
                if runner.get("selectionId") != sel_id:
                    continue
                backs = runner.get("ex", {}).get("availableToBack", [])
                if not backs:
                    continue
                price = float(backs[0].get("price", 0))
                if price <= 0:
                    continue
                if best is None or price < best[2]:
                    best = (sel_id, name, price)
        return best

    def _get_stats(self, home: str, away: str, needs_corners: bool = False):
        home_stats, away_stats, h2h = {}, {}, {}
        corner_stats = {}
        has_stats = False
        fixture = self.api_football.get_fixture_by_teams(home, away)
        if not fixture:
            return home_stats, away_stats, h2h, has_stats, corner_stats

        lid = fixture["league"]["id"]
        hid = fixture["teams"]["home"]["id"]
        aid = fixture["teams"]["away"]["id"]
        hs = self.api_football.get_team_stats(hid, lid, CURRENT_SEASON)
        as_ = self.api_football.get_team_stats(aid, lid, CURRENT_SEASON)
        h2r = self.api_football.get_h2h(hid, aid)
        home_stats = self.api_football.extract_goals_stats(hs) if hs else {}
        away_stats = self.api_football.extract_goals_stats(as_) if as_ else {}
        h2h = self.api_football.extract_h2h_summary(h2r, hid, aid)
        has_stats = bool(home_stats and away_stats)
        if needs_corners and hs and as_:
            corner_stats = {
                "home": self.api_football.extract_corners_stats(hs),
                "away": self.api_football.extract_corners_stats(as_),
            }
        return home_stats, away_stats, h2h, has_stats, corner_stats

    def _analyze_groq_football(
        self,
        profile: dict,
        home: str,
        away: str,
        league: str,
        odds: float,
        selection_label: str,
        home_stats: dict,
        away_stats: dict,
        h2h: dict,
        has_stats: bool,
        corner_stats: dict,
    ) -> Optional[dict]:
        if not self.groq_keys:
            return self._heuristic_fallback()

        if has_stats:
            ha = float(home_stats.get("avg_scored_total") or 0)
            hd = float(home_stats.get("avg_conceded_total") or 0)
            aa = float(away_stats.get("avg_scored_total") or 0)
            ad = float(away_stats.get("avg_conceded_total") or 0)
            stats_block = (
                f"{home}: marca {ha:.1f}/jogo, sofre {hd:.1f}/jogo, forma {home_stats.get('form', 'N/A')}\n"
                f"{away}: marca {aa:.1f}/jogo, sofre {ad:.1f}/jogo, forma {away_stats.get('form', 'N/A')}\n"
                f"H2H média gols: {h2h.get('avg_goals_per_game', 'N/A')}\n"
            )
        else:
            stats_block = "Sem estatísticas detalhadas — use conhecimento da liga e dos times.\n"

        if corner_stats:
            hc = corner_stats.get("home", {})
            ac = corner_stats.get("away", {})
            stats_block += (
                f"Escanteios médios — {home}: {hc.get('avg_total', 'N/A')}, "
                f"{away}: {ac.get('avg_total', 'N/A')}\n"
            )

        prompt = f"""Analise esta oportunidade de aposta em futebol:

JOGO: {home} x {away}
LIGA: {league}
MERCADO: {profile['label']} — {selection_label}
OBJETIVO: {profile['prompt_goal']}
ODD: {odds}
RISCO ESPERADO: {profile['risk']}

{stats_block}

Responda SOMENTE JSON válido:
{{
  "confidence": 0-100,
  "recommend": true/false,
  "expected_outcome": "breve descrição",
  "reasoning": "2 frases objetivas em português"
}}

Seja conservador: recommend=true só se a aposta tiver boa relação risco/retorno para o mercado indicado."""

        return self._call_groq(prompt)

    def _analyze_groq_tennis(
        self,
        profile: dict,
        player_a: str,
        player_b: str,
        tournament: str,
        odds: float,
        selection_label: str,
    ) -> Optional[dict]:
        if not self.groq_keys:
            return self._heuristic_fallback()

        prompt = f"""Analise esta oportunidade de aposta em tênis:

JOGO: {player_a} vs {player_b}
TORNEIO: {tournament}
MERCADO: {profile['label']} — {selection_label}
OBJETIVO: {profile['prompt_goal']}
ODD: {odds}

Responda SOMENTE JSON válido:
{{
  "confidence": 0-100,
  "recommend": true/false,
  "expected_outcome": "breve descrição",
  "reasoning": "2 frases objetivas em português"
}}

Seja conservador. Em tênis, considere superfície, ranking relativo e estilo de jogo."""

        return self._call_groq(prompt)

    def _call_groq(self, prompt: str) -> Optional[dict]:
        if not self.groq_keys:
            logger.warning("Sem chave Groq — usando fallback heurístico")
            return self._heuristic_fallback()

        last_error: Exception | None = None
        for offset in range(len(self.groq_keys)):
            idx = (self._groq_key_index + offset) % len(self.groq_keys)
            key = self.groq_keys[idx]
            try:
                resp = requests.post(
                    GROQ_API_URL,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": GROQ_MODEL,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Analista de apostas esportivas. Responda apenas JSON válido.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 350,
                    },
                    timeout=25,
                    proxies={"http": None, "https": None},
                )
                if resp.status_code == 429 and len(self.groq_keys) > 1:
                    logger.warning("Groq chave %d atingiu limite; tentando próxima.", idx + 1)
                    last_error = requests.HTTPError(f"429 rate limit na chave {idx + 1}")
                    continue
                resp.raise_for_status()
                self._groq_key_index = idx
                self.groq_key = key
                content = resp.json()["choices"][0]["message"]["content"].strip()
                if content.startswith("```"):
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]
                return json.loads(content.strip())
            except requests.HTTPError as e:
                last_error = e
                if len(self.groq_keys) > 1:
                    logger.warning("Groq chave %d falhou (%s); tentando próxima.", idx + 1, e)
                    continue
                break
            except Exception as e:
                last_error = e
                break

        if last_error:
            logger.warning("Groq falhou: %s — usando fallback heurístico", last_error)
        return self._heuristic_fallback()

    @staticmethod
    def _heuristic_fallback() -> dict:
        """Quando a IA cai (DNS/rede), ainda permite aposta se odd/volume já passaram."""
        return {
            "confidence": 68,
            "recommend": True,
            "reasoning": "IA indisponível; aprovado por filtros de odd/volume (fallback).",
        }

    def _get_book(self, market_id: str) -> Optional[dict]:
        try:
            books = self.betfair.list_market_book(
                market_ids=[market_id],
                price_projection={
                    "priceData": ["EX_BEST_OFFERS", "EX_TRADED"],
                    "exBestOffersOverrides": {"bestPricesDepth": 3},
                },
            )
            return books[0] if books else None
        except Exception as e:
            logger.debug("Book error %s: %s", market_id, e)
            return None

    def _save_pending(self, opportunities: List[Opportunity]) -> None:
        os.makedirs("data", exist_ok=True)
        store = {}
        if os.path.exists(PENDING_FILE):
            try:
                with open(PENDING_FILE) as f:
                    store = json.load(f)
            except Exception:
                store = {}

        expires = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
        for opp in opportunities:
            data = opp.to_dict()
            data["expires_at"] = expires
            store[opp.opp_id] = data

        with open(PENDING_FILE, "w") as f:
            json.dump(store, f, indent=2)

    @staticmethod
    def load_pending(opp_id: str) -> Optional[dict]:
        if not os.path.exists(PENDING_FILE):
            return None
        try:
            with open(PENDING_FILE) as f:
                store = json.load(f)
            opp = store.get(opp_id)
            if not opp:
                return None
            expires = opp.get("expires_at", "")
            if expires and datetime.fromisoformat(expires) < datetime.now(timezone.utc):
                return None
            return opp
        except Exception:
            return None
