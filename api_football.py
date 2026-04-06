#!/usr/bin/env python3
"""
Integração com API-Football v3
Gerencia orçamento de 100 requisições/dia com cache inteligente
"""

import json
import logging
import os
from datetime import datetime, date
from typing import Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

CACHE_FILE = "data/api_football_cache.json"
DAILY_LIMIT = 95  # Reserva 5 para margem de segurança


class APIFootball:
    BASE_URL = "https://v3.football.api-sports.io"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.cache = self._load_cache()
        self._reset_daily_count_if_new_day()

    # ─── Cache ────────────────────────────────────────────────────────────────

    def _load_cache(self) -> dict:
        os.makedirs("data", exist_ok=True)
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"requests_today": 0, "last_reset_date": str(date.today()), "data": {}}

    def _save_cache(self):
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Falha ao salvar cache: {e}")

    def _reset_daily_count_if_new_day(self):
        today = str(date.today())
        if self.cache.get("last_reset_date") != today:
            self.cache["requests_today"] = 0
            self.cache["last_reset_date"] = today
            logger.info("Contador diário de requisições resetado")
            self._save_cache()

    def get_requests_remaining(self) -> int:
        self._reset_daily_count_if_new_day()
        return max(0, DAILY_LIMIT - self.cache.get("requests_today", 0))

    # ─── HTTP ─────────────────────────────────────────────────────────────────

    def _request(self, endpoint: str, params: dict, cache_key: str = None) -> Optional[dict]:
        """Faz requisição com cache. cache_key=None desativa o cache."""
        # Checar cache
        if cache_key and cache_key in self.cache.get("data", {}):
            cached = self.cache["data"][cache_key]
            cached_date = cached.get("_cached_date", "")
            if cached_date == str(date.today()):
                logger.debug(f"Cache hit: {cache_key}")
                return cached.get("response")

        # Verificar orçamento (e resetar se virou o dia)
        self._reset_daily_count_if_new_day()
        if self.cache.get("requests_today", 0) >= DAILY_LIMIT:
            logger.warning(f"Limite diário de requisições atingido ({DAILY_LIMIT})")
            return None

        url = f"{self.BASE_URL}/{endpoint}"
        headers = {
            "x-apisports-key": self.api_key,
            "x-rapidapi-host": "v3.football.api-sports.io",
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15,
                                proxies={'http': None, 'https': None})
            resp.raise_for_status()
            data = resp.json()

            self.cache["requests_today"] = self.cache.get("requests_today", 0) + 1
            remaining = data.get("paging", {})
            logger.info(
                f"API-Football [{endpoint}] → {self.cache['requests_today']}/{DAILY_LIMIT} req hoje"
            )

            response = data.get("response", [])

            # Salvar no cache
            if cache_key is not None:
                if "data" not in self.cache:
                    self.cache["data"] = {}
                self.cache["data"][cache_key] = {
                    "_cached_date": str(date.today()),
                    "response": response,
                }
            self._save_cache()
            return response

        except requests.exceptions.RequestException as e:
            logger.error(f"Erro na requisição API-Football [{endpoint}]: {e}")
            return None

    # ─── Endpoints ────────────────────────────────────────────────────────────

    def get_fixtures_today(self) -> List[dict]:
        """Retorna todos os jogos do dia (1 requisição, cache diário)."""
        today = str(date.today())
        cache_key = f"fixtures_date_{today}"
        result = self._request("fixtures", {"date": today, "timezone": "America/Sao_Paulo"}, cache_key)
        return result or []

    def get_fixtures_next(self, hours: int = 3) -> List[dict]:
        """Retorna próximos N fixtures (usa cache de hoje)."""
        all_today = self.get_fixtures_today()
        now = datetime.utcnow()
        upcoming = []
        for fx in all_today:
            try:
                ts = fx["fixture"]["timestamp"]
                fx_dt = datetime.utcfromtimestamp(ts)
                diff_hours = (fx_dt - now).total_seconds() / 3600
                if -0.5 <= diff_hours <= hours:
                    upcoming.append(fx)
            except Exception:
                pass
        return upcoming

    def get_team_stats(self, team_id: int, league_id: int, season: int) -> Optional[dict]:
        """Estatísticas de um time em uma liga/temporada. Cache por temporada."""
        cache_key = f"team_stats_{team_id}_{league_id}_{season}"
        result = self._request(
            "teams/statistics",
            {"team": team_id, "league": league_id, "season": season},
            cache_key,
        )
        if isinstance(result, dict):
            return result
        if isinstance(result, list) and result:
            return result[0]
        return None

    def get_h2h(self, team1_id: int, team2_id: int, last: int = 10) -> List[dict]:
        """Histórico de confrontos diretos. Cache diário."""
        cache_key = f"h2h_{min(team1_id, team2_id)}_{max(team1_id, team2_id)}"
        result = self._request(
            "fixtures/headtohead",
            {"h2h": f"{team1_id}-{team2_id}", "last": last},
            cache_key,
        )
        return result or []

    def get_fixture_by_teams(self, home_name: str, away_name: str) -> Optional[dict]:
        """Busca fixture de hoje pelo nome dos times (usa cache de fixtures do dia)."""
        fixtures = self.get_fixtures_today()
        home_lower = home_name.lower()
        away_lower = away_name.lower()

        best_match = None
        best_score = 0

        for fx in fixtures:
            try:
                fx_home = fx["teams"]["home"]["name"].lower()
                fx_away = fx["teams"]["away"]["name"].lower()

                # Score de similaridade simples baseado em palavras em comum
                score = self._name_similarity(home_lower, fx_home) + \
                        self._name_similarity(away_lower, fx_away)

                if score > best_score and score >= 0.5:
                    best_score = score
                    best_match = fx
            except Exception:
                pass

        if best_match:
            logger.info(
                f"Match encontrado: {best_match['teams']['home']['name']} x "
                f"{best_match['teams']['away']['name']} (score={best_score:.2f})"
            )
        return best_match

    def _name_similarity(self, name1: str, name2: str) -> float:
        """Similaridade simples entre dois nomes de times."""
        words1 = set(name1.replace("-", " ").split())
        words2 = set(name2.replace("-", " ").split())
        if not words1 or not words2:
            return 0.0
        # Remover palavras muito curtas e comuns
        stop = {"fc", "cf", "ac", "sc", "de", "do", "da", "the", "city", "united", "utd"}
        w1 = words1 - stop or words1
        w2 = words2 - stop or words2
        intersection = w1 & w2
        union = w1 | w2
        return len(intersection) / len(union)

    # ─── Análise de estatísticas ──────────────────────────────────────────────

    def extract_goals_stats(self, team_stats: dict) -> dict:
        """Extrai estatísticas de gols de forma padronizada."""
        if not team_stats:
            return {}
        try:
            goals = team_stats.get("goals", {})
            scored = goals.get("for", {}).get("average", {})
            conceded = goals.get("against", {}).get("average", {})
            fixtures = team_stats.get("fixtures", {})
            played = fixtures.get("played", {}).get("total", 0)

            return {
                "avg_scored_home": float(scored.get("home") or 0),
                "avg_scored_away": float(scored.get("away") or 0),
                "avg_scored_total": float(scored.get("total") or 0),
                "avg_conceded_home": float(conceded.get("home") or 0),
                "avg_conceded_away": float(conceded.get("away") or 0),
                "avg_conceded_total": float(conceded.get("total") or 0),
                "games_played": played,
                "form": team_stats.get("form", ""),
            }
        except Exception as e:
            logger.warning(f"Erro ao extrair stats de gols: {e}")
            return {}

    def extract_h2h_summary(self, h2h_fixtures: List[dict], team1_id: int, team2_id: int) -> dict:
        """Resume histórico de H2H focando em gols."""
        if not h2h_fixtures:
            return {}
        try:
            last_5 = sorted(h2h_fixtures, key=lambda x: x["fixture"]["date"], reverse=True)[:5]
            total_goals_list = []
            over25_count = 0

            for fx in last_5:
                home_goals = fx["goals"]["home"] or 0
                away_goals = fx["goals"]["away"] or 0
                total = home_goals + away_goals
                total_goals_list.append(total)
                if total >= 3:
                    over25_count += 1

            avg_goals = sum(total_goals_list) / len(total_goals_list) if total_goals_list else 0

            return {
                "matches_analyzed": len(last_5),
                "avg_goals_per_game": round(avg_goals, 2),
                "over25_in_last_5": over25_count,
                "over25_rate": round(over25_count / len(last_5), 2) if last_5 else 0,
                "goals_per_match": total_goals_list,
            }
        except Exception as e:
            logger.warning(f"Erro ao extrair H2H: {e}")
            return {}
