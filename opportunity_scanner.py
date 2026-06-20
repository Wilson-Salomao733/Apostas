#!/usr/bin/env python3
"""
Varredura multi-mercado de oportunidades de futebol (modo manual).
Não aposta automaticamente — apenas encontra e analisa com IA.
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

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
CURRENT_SEASON = 2025
SOCCER_EVENT_TYPE_ID = "1"

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
}

BLOCKED_KEYWORDS = {
    "u21", "u23", "u18", "reserve", "youth", "friendly", "amistoso",
    "pre-season", "ii liga", "division 3", "third division", "terceira",
    "gibraltar", "andorra", "faroe", "san marino", "liechtenstein",
}

SCAN_PROFILES = [
    {
        "key": "under45",
        "label": "Under 4.5 Gols",
        "market_type": "OVER_UNDER_45",
        "selection_hint": "under",
        "min_odds": 1.25,
        "max_odds": 1.42,
        "min_confidence": 72,
        "risk": "baixo",
        "prompt_goal": "MENOS de 4,5 gols (máximo 4 gols no jogo)",
    },
    {
        "key": "over15",
        "label": "Over 1.5 Gols",
        "market_type": "OVER_UNDER_15",
        "selection_hint": "over",
        "min_odds": 1.25,
        "max_odds": 1.55,
        "min_confidence": 70,
        "risk": "baixo",
        "prompt_goal": "MAIS de 1,5 gols (pelo menos 2 gols no jogo)",
    },
    {
        "key": "over25",
        "label": "Over 2.5 Gols",
        "market_type": "OVER_UNDER_25",
        "selection_hint": "over",
        "min_odds": 1.75,
        "max_odds": 2.45,
        "min_confidence": 68,
        "risk": "médio",
        "prompt_goal": "MAIS de 2,5 gols (pelo menos 3 gols no jogo)",
    },
    {
        "key": "favorite",
        "label": "Favorito (Match Odds)",
        "market_type": "MATCH_ODDS",
        "selection_hint": "favorite",
        "min_odds": 1.45,
        "max_odds": 2.10,
        "min_confidence": 68,
        "risk": "médio",
        "prompt_goal": "vitória do time favorito (Match Odds)",
    },
]

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
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


def _league_ok(league: str) -> bool:
    name = league.lower()
    for kw in BLOCKED_KEYWORDS:
        if kw in name:
            return False
    for good in GOOD_LEAGUES:
        if good in name:
            return True
    return False


def _parse_teams(event_name: str) -> Tuple[str, str]:
    if " v " in event_name:
        parts = event_name.split(" v ", 1)
        return parts[0].strip(), parts[1].strip()
    if " vs " in event_name.lower():
        parts = event_name.lower().split(" vs ", 1)
        return parts[0].strip().title(), parts[1].strip().title()
    return "", ""


def _make_opp_id(market_id: str, selection_id: int, bet_key: str) -> str:
    raw = f"{market_id}:{selection_id}:{bet_key}"
    return hashlib.sha256(raw.encode()).hexdigest()[:10]


class OpportunityScanner:
    def __init__(self, betfair_api, api_football: APIFootball, groq_key: str, stake: float = 20.0):
        self.betfair = betfair_api
        self.api_football = api_football
        self.groq_key = groq_key
        self.stake = stake
        self.max_per_profile = int(os.getenv("SCAN_MAX_PER_TYPE", "12"))
        self.max_results = int(os.getenv("SCAN_MAX_RESULTS", "6"))

    def scan(self) -> List[Opportunity]:
        logger.info("Iniciando varredura multi-mercado...")
        candidates: List[Opportunity] = []

        for profile in SCAN_PROFILES:
            try:
                found = self._scan_profile(profile)
                candidates.extend(found)
                logger.info(f"[{profile['label']}] {len(found)} oportunidade(s) aprovada(s)")
            except Exception as e:
                logger.error(f"Erro no perfil {profile['key']}: {e}")
            time.sleep(0.5)

        candidates.sort(key=lambda o: (o.confidence, o.potential_profit / max(o.stake, 1)), reverse=True)
        results = candidates[: self.max_results]
        self._save_pending(results)
        logger.info(f"Varredura concluída: {len(results)} oportunidade(s) enviáveis")
        return results

    def _scan_profile(self, profile: dict) -> List[Opportunity]:
        markets = self._fetch_markets(profile["market_type"])
        approved: List[Opportunity] = []

        for mkt in markets[: self.max_per_profile]:
            opp = self._evaluate_market(mkt, profile)
            if opp:
                approved.append(opp)
            time.sleep(0.8)

        return approved

    def _fetch_markets(self, market_type: str) -> List[dict]:
        now = datetime.now(timezone.utc)
        try:
            markets = self.betfair.list_market_catalogue(
                filter_dict={
                    "eventTypeIds": [SOCCER_EVENT_TYPE_ID],
                    "marketTypeCodes": [market_type],
                    "marketStartTime": {
                        "from": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "to": (now + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                },
                market_projection=[
                    "COMPETITION", "EVENT", "RUNNER_DESCRIPTION", "MARKET_START_TIME",
                ],
                max_results=80,
            )
            return markets or []
        except Exception as e:
            logger.error(f"Erro ao buscar {market_type}: {e}")
            return []

    def _evaluate_market(self, mkt: dict, profile: dict) -> Optional[Opportunity]:
        event = mkt.get("event", {})
        comp = mkt.get("competition", {})
        league = comp.get("name", "")
        if not _league_ok(league):
            return None

        home, away = _parse_teams(event.get("name", ""))
        if not home or not away:
            return None

        book = self._get_book(mkt["marketId"])
        if not book:
            return None

        selection = self._pick_selection(mkt, book, profile)
        if not selection:
            return None

        sel_id, sel_label, odds = selection
        if not (profile["min_odds"] <= odds <= profile["max_odds"]):
            return None

        home_stats, away_stats, h2h, has_stats = self._get_stats(home, away)
        analysis = self._analyze_groq(
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
        )
        if not analysis:
            return None

        confidence = int(analysis.get("confidence", 0))
        min_conf = profile["min_confidence"] + (5 if not has_stats else 0)
        if confidence < min_conf:
            return None

        if analysis.get("recommend") is False:
            return None

        kickoff = mkt.get("marketStartTime", "")
        profit = round(self.stake * (odds - 1), 2)
        opp_id = _make_opp_id(mkt["marketId"], sel_id, profile["key"])

        return Opportunity(
            opp_id=opp_id,
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
            if name.lower() in ("the draw", "empate", "draw"):
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

    def _get_stats(self, home: str, away: str):
        home_stats, away_stats, h2h = {}, {}, {}
        has_stats = False
        fixture = self.api_football.get_fixture_by_teams(home, away)
        if not fixture:
            return home_stats, away_stats, h2h, has_stats

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
        return home_stats, away_stats, h2h, has_stats

    def _analyze_groq(
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
                            "content": (
                                "Analista de apostas esportivas. Responda apenas JSON válido."
                            ),
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
            logger.warning(f"Groq falhou {home} x {away}: {e}")
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
            logger.debug(f"Book error {market_id}: {e}")
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
