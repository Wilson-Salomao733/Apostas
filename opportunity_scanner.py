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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import requests

from api_football import APIFootball
from config_loader import PROFILE_DEFAULTS, build_scan_profiles, get_manual_stake, get_strategy_params

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
CURRENT_SEASON = 2026
MIN_GLOBAL_ODDS = 1.20

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
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


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


class OpportunityScanner:
    def __init__(
        self,
        betfair_api,
        api_football: APIFootball,
        groq_key: str,
        stake: float | None = None,
        active_strategy: str | None = None,
        enabled_sports: list[str] | None = None,
    ):
        self.betfair = betfair_api
        self.api_football = api_football
        self.groq_key = groq_key
        self.stake = stake if stake is not None else get_manual_stake()
        self.active_strategy = active_strategy
        self.enabled_sports = enabled_sports
        self.max_per_profile = int(os.getenv("SCAN_MAX_PER_TYPE", "35"))
        self.max_results = int(os.getenv("SCAN_MAX_RESULTS", "8"))
        self.last_stats: dict = {}
        self._near_misses: List[Opportunity] = []
        self._betfair_error: str | None = None

    def scan(self) -> List[Opportunity]:
        profiles = build_scan_profiles(self.active_strategy, self.enabled_sports)
        logger.info("Iniciando varredura (%d perfil/is)...", len(profiles))
        candidates: List[Opportunity] = []
        self._near_misses = []
        self._betfair_error = None
        stats: dict = {
            "markets_total": 0,
            "blocked_league": 0,
            "wrong_odds": 0,
            "low_volume": 0,
            "ia_rejected": 0,
            "ia_analyzed": 0,
        }

        for profile in profiles:
            profile_stake = profile.get("stake", self.stake)
            old_stake = self.stake
            self.stake = profile_stake
            try:
                if profile["key"] == "combo_u45_u85":
                    found, partial = self._scan_combo_u45_u85(profile)
                else:
                    found, partial = self._scan_profile(profile)
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
        stats["approved"] = len(results)
        if stats.get("markets_total", 0) == 0 and self._betfair_error:
            stats["betfair_error"] = self._betfair_error
        self.last_stats = stats
        self._save_pending(results)
        logger.info("Varredura concluída: %d oportunidade(s) | stats=%s", len(results), stats)
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
        min_o = max(profile["min_odds"], MIN_GLOBAL_ODDS)
        max_o = profile["max_odds"]
        if profile["key"] == "under45" and _is_world_cup(league):
            min_o = min(min_o, 1.08)
        return min_o, max_o

    def _scan_combo_u45_u85(self, profile: dict) -> tuple[List[Opportunity], dict]:
        """Múltipla mesmo jogo: Under 4.5 gols + Under 8.5 escanteios."""
        goals_profile = {**PROFILE_DEFAULTS["under45"], **get_strategy_params("under45")}
        corners_profile = {**PROFILE_DEFAULTS["corners_85"], **get_strategy_params("corners_85")}
        min_combined = float(profile.get("min_combined_odds", 1.55))
        max_combined = float(profile.get("max_combined_odds", 2.40))
        min_conf = int(profile.get("min_confidence", 72))

        goals_markets = self._prioritize_markets(
            self._fetch_markets("OVER_UNDER_45", "1"), "football",
        )
        corners_markets = self._fetch_markets("OVER_UNDER_85_CORNR", "1")
        corners_by_event: Dict[str, dict] = {}
        for m in corners_markets:
            eid = str(m.get("event", {}).get("id", ""))
            if eid:
                corners_by_event[eid] = m

        approved: List[Opportunity] = []
        partial = {"markets_total": len(goals_markets), "combo_checked": 0}

        for mkt in goals_markets[: self.max_per_profile]:
            league = mkt.get("competition", {}).get("name", "")
            if profile.get("good_league_only") and _league_tier(league, "football") != "good":
                partial["blocked_league"] = partial.get("blocked_league", 0) + 1
                continue

            eid = str(mkt.get("event", {}).get("id", ""))
            cmkt = corners_by_event.get(eid)
            if not cmkt:
                partial["no_corners_market"] = partial.get("no_corners_market", 0) + 1
                continue

            partial["combo_checked"] = partial.get("combo_checked", 0) + 1
            opp = self._evaluate_combo(
                mkt, cmkt, goals_profile, corners_profile, profile,
                min_combined, max_combined, min_conf,
            )
            if opp:
                approved.append(opp)
            time.sleep(0.6)

        return approved, partial

    def _evaluate_combo(
        self, goals_mkt, corners_mkt, goals_profile, corners_profile, combo_profile,
        min_combined, max_combined, min_conf,
    ) -> Optional[Opportunity]:
        event = goals_mkt.get("event", {})
        league = goals_mkt.get("competition", {}).get("name", "")
        home, away = _parse_participants(event.get("name", ""))
        if not home or not away:
            return None

        g_book = self._get_book(goals_mkt["marketId"])
        c_book = self._get_book(corners_mkt["marketId"])
        if not g_book or not c_book:
            return None

        min_vol = combo_profile.get("min_volume", 3000)
        if float(g_book.get("totalMatched", 0) or 0) < min_vol:
            return None
        if float(c_book.get("totalMatched", 0) or 0) < min_vol:
            return None

        g_sel = self._pick_selection(goals_mkt, g_book, goals_profile)
        c_sel = self._pick_selection(corners_mkt, c_book, corners_profile)
        if not g_sel or not c_sel:
            return None

        g_id, g_label, g_odds = g_sel
        c_id, c_label, c_odds = c_sel
        min_g, max_g = self._odds_range(goals_profile, league)
        min_c, max_c = self._odds_range(corners_profile, league)
        if not (min_g <= g_odds <= max_g and min_c <= c_odds <= max_c):
            return None

        combined = round(g_odds * c_odds, 3)
        if not (min_combined <= combined <= max_combined):
            return None

        home_stats, away_stats, h2h, has_stats, corner_stats = self._get_stats(
            home, away, "combo_u45_u85",
        )
        analysis = self._analyze_groq_combo(
            home, away, league, g_odds, c_odds, combined,
            home_stats, away_stats, h2h, corner_stats, has_stats,
        )
        if not analysis:
            return None

        confidence = int(analysis.get("confidence", 0))
        extra = 5 if not has_stats else 0
        if confidence < min_conf + extra or analysis.get("recommend") is False:
            return None

        stake = float(combo_profile.get("stake", self.stake))
        profit = round(stake * (combined - 1) * 0.95, 2)
        legs = [
            {
                "key": "goals",
                "market_id": goals_mkt["marketId"],
                "selection_id": g_id,
                "odds": g_odds,
                "label": f"U4.5 gols @ {g_odds:.2f}",
            },
            {
                "key": "corners",
                "market_id": corners_mkt["marketId"],
                "selection_id": c_id,
                "odds": c_odds,
                "label": f"U8.5 esc @ {c_odds:.2f}",
            },
        ]
        opp_id = _make_opp_id(goals_mkt["marketId"], c_id, "combo_u45_u85")

        return Opportunity(
            opp_id=opp_id,
            bet_type=combo_profile.get("label", "Múltipla U4.5 + U8.5 esc"),
            bet_key="combo_u45_u85",
            risk="médio",
            home=home,
            away=away,
            league=league,
            market_id=goals_mkt["marketId"],
            selection_id=g_id,
            selection_label=f"U4.5 @ {g_odds:.2f} × U8.5 esc @ {c_odds:.2f}",
            odds=combined,
            combined_odds=combined,
            stake=stake,
            confidence=confidence,
            reasoning=str(analysis.get("reasoning", ""))[:400],
            potential_profit=profit,
            kickoff=goals_mkt.get("marketStartTime", ""),
            sport="football",
            legs=legs,
        )

    def _analyze_groq_combo(
        self, home, away, league, g_odds, c_odds, combined,
        home_stats, away_stats, h2h, corner_stats, has_stats,
    ) -> Optional[dict]:
        if not self.groq_key:
            return None
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

        prompt = f"""Analise esta MÚLTIPLA no mesmo jogo de futebol (as duas seleções devem bater):

JOGO: {home} x {away}
LIGA: {league}
PERNA 1: Menos de 4,5 gols @ {g_odds}
PERNA 2: Menos de 8,5 escanteios @ {c_odds}
ODD COMBINADA: {combined}

{stats_block}

Jogos com poucos gols costumam ter menos escanteios — avalie correlação.
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
            time.sleep(0.5)

        return approved, partial

    def _fetch_markets(self, market_type: str, event_type_id: str) -> List[dict]:
        now = datetime.now(timezone.utc)
        try:
            markets = self.betfair.list_market_catalogue(
                filter_dict={
                    "eventTypeIds": [event_type_id],
                    "marketTypeCodes": [market_type],
                    "marketStartTime": {
                        "from": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "to": (now + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                },
                market_projection=[
                    "COMPETITION", "EVENT", "RUNNER_DESCRIPTION", "MARKET_START_TIME",
                ],
                max_results=80,
            )
            return markets or []
        except Exception as e:
            logger.error("Erro ao buscar %s: %s", market_type, e)
            self._betfair_error = str(e)
            return []

    def _evaluate_market(self, mkt: dict, profile: dict) -> tuple[Optional[Opportunity], Optional[str]]:
        sport = profile.get("sport", "football")
        event = mkt.get("event", {})
        comp = mkt.get("competition", {})
        league = comp.get("name", "")
        tier = _league_tier(league, sport)

        if tier == "blocked":
            return None, "blocked_league"
        if profile.get("good_league_only") and tier != "good":
            return None, "blocked_league"
        if profile["key"] == "under45" and tier == "unknown":
            return None, "blocked_league"

        home, away = _parse_participants(event.get("name", ""))
        if not home or not away:
            return None, None

        book = self._get_book(mkt["marketId"])
        if not book:
            return None, None

        min_vol = profile.get("min_volume", 0)
        total_matched = float(book.get("totalMatched", 0) or 0)
        if min_vol and total_matched < min_vol:
            return None, "low_volume"

        selection = self._pick_selection(mkt, book, profile)
        if not selection:
            return None, None

        sel_id, sel_label, odds = selection
        min_o, max_o = self._odds_range(profile, league)
        if odds < MIN_GLOBAL_ODDS and not (_is_world_cup(league) and profile["key"] == "under45"):
            return None, "wrong_odds"
        if not (min_o <= odds <= max_o):
            return None, "wrong_odds"

        if sport == "tennis":
            analysis = self._analyze_groq_tennis(
                profile, home, away, league, odds, sel_label,
            )
            has_stats = False
        else:
            home_stats, away_stats, h2h, has_stats, corner_stats = self._get_stats(
                home, away, profile["key"],
            )
            if profile.get("require_stats") and not has_stats:
                return None, "ia_rejected"
            analysis = self._analyze_groq_football(
                profile=profile,
                home=home,
                away=away,
                league=league,
                odds=odds,
                selection_label=sel_label,
                home_stats=home_stats,
                away_stats=away_stats,
                h2h=h2h,
                has_stats=has_stats,
                corner_stats=corner_stats,
            )

        if not analysis:
            return None, "ia_rejected"

        confidence = int(analysis.get("confidence", 0))
        extra = 5 if not has_stats else 0
        if tier == "unknown":
            extra += 5
        min_conf = profile["min_confidence"] + extra
        if confidence < min_conf:
            self._maybe_near_miss(
                mkt, profile, home, away, league, sel_id, sel_label, odds,
                confidence, analysis, sport, kickoff=mkt.get("marketStartTime", ""),
            )
            return None, "ia_rejected"

        if analysis.get("recommend") is False:
            self._maybe_near_miss(
                mkt, profile, home, away, league, sel_id, sel_label, odds,
                confidence, analysis, sport, kickoff=mkt.get("marketStartTime", ""),
            )
            return None, "ia_rejected"

        kickoff = mkt.get("marketStartTime", "")
        profit = round(self.stake * (odds - 1), 2)

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
            stake=self.stake,
            confidence=confidence,
            reasoning=str(analysis.get("reasoning", ""))[:400],
            potential_profit=profit,
            kickoff=kickoff,
            sport=sport,
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

    def _near_miss_from(
        self, mkt, profile, home, away, league, sel_id, sel_label, odds,
        confidence, analysis, sport, kickoff,
    ) -> Optional[Opportunity]:
        reason = str(analysis.get("reasoning", "IA não recomendou"))[:400]
        profit = round(self.stake * (odds - 1), 2)
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
            stake=self.stake,
            confidence=confidence,
            reasoning=f"IA cautelosa — revise antes: {reason}",
            potential_profit=profit,
            kickoff=kickoff or mkt.get("marketStartTime", ""),
            sport=sport,
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
            if hint == "under" and "under" in nm:
                target_id = rd.get("selectionId")
                target_label = rd.get("runnerName", "Under")
                break
            if hint == "over" and "over" in nm:
                target_id = rd.get("selectionId")
                target_label = rd.get("runnerName", "Over")
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

    def _get_stats(self, home: str, away: str, profile_key: str):
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
        if profile_key in ("corners_105", "corners_85", "combo_u45_u85") and hs and as_:
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
        if not self.groq_key:
            return None

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
        if not self.groq_key:
            return None

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
        try:
            resp = requests.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {self.groq_key}",
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
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            return json.loads(content.strip())
        except Exception as e:
            logger.warning("Groq falhou: %s", e)
            return None

    def _get_book(self, market_id: str) -> Optional[dict]:
        try:
            books = self.betfair.list_market_book(
                market_ids=[market_id],
                price_projection={
                    "priceData": ["EX_BEST_OFFERS"],
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
