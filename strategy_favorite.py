#!/usr/bin/env python3
"""
Estratégia Favorito — Back no time mais provável de vencer.
Mercado: MATCH_ODDS (1X2)
Alvo: Back no favorito quando odds 1.45-1.90 e IA confirma edge real.
Win rate esperado: ~62-70% com seleção criteriosa.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import requests

from api_football import APIFootball
from groq_analyzer import GroqAnalyzer

logger = logging.getLogger(__name__)

SOCCER_EVENT_TYPE_ID = "1"
MATCH_ODDS_MARKET = "MATCH_ODDS"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.3-70b-versatile"
CURRENT_SEASON = 2025

GOOD_LEAGUES = {
    "premier league", "la liga", "bundesliga", "serie a", "ligue 1",
    "eredivisie", "primeira liga", "champions league", "europa league",
    "conference league", "brasileirao", "brasileirão", "campeonato brasileiro",
    "copa do brasil", "libertadores", "sul-americana",
    "mls", "liga mx", "j1 league", "k league", "a-league",
    "super lig", "ekstraklasa", "scottish premiership",
    "belgian pro league", "jupiler pro league", "austrian bundesliga",
    "swiss super league", "danish superliga", "allsvenskan", "eliteserien",
    "greek super league", "czech first league",
    "saudi pro league", "chinese super league", "nations league",
    "world cup", "euro", "copa america",
}

BLOCKED_KEYWORDS = {
    "u21", "u23", "u18", "reserve", "youth", "friendly", "amistoso",
    "pre-season", "ii liga", "division 3", "third", "terceira",
    "gibraltar", "andorra", "faroe", "san marino", "liechtenstein",
}


def _league_quality(league_name: str) -> str:
    name = league_name.lower()
    for kw in BLOCKED_KEYWORDS:
        if kw in name:
            return "blocked"
    for good in GOOD_LEAGUES:
        if good in name:
            return "good"
    return "unknown"


@dataclass
class ActiveBet:
    bet_id: str
    market_id: str
    selection_id: int
    home_team: str
    away_team: str
    favorite_name: str
    odds: float
    stake: float
    potential_profit: float
    placed_at: datetime
    confidence: int
    reasoning: str
    status: str = "ACTIVE"
    profit_loss: float = 0.0


class StrategyFavorite:
    """
    Aposta no favorito quando há edge real detectado pela IA.
    Mercado: MATCH_ODDS (maior liquidez na Betfair).
    """

    def __init__(self, betfair_api, api_football: APIFootball,
                 groq_analyzer: GroqAnalyzer, config, db, telegram):
        self.betfair      = betfair_api
        self.api_football = api_football
        self.groq_key     = groq_analyzer.api_key
        self.db           = db
        self.telegram     = telegram

        self.stake            = float(config.get("favorite", "stake", fallback="20.0"))
        self.min_odds         = float(config.get("favorite", "min_odds", fallback="1.45"))
        self.max_odds         = float(config.get("favorite", "max_odds", fallback="1.90"))
        self.min_confidence   = int(config.get("favorite", "min_confidence", fallback="70"))
        self.max_concurrent   = int(config.get("favorite", "max_concurrent_bets", fallback="3"))
        self.daily_loss_limit = float(config.get("favorite", "daily_loss_limit", fallback="60.0"))
        self.daily_profit_tgt = float(config.get("favorite", "daily_profit_target", fallback="80.0"))

        self.active_bets: Dict[str, ActiveBet] = {}
        self.daily_profit       = 0.0
        self.daily_losses       = 0.0
        self.consecutive_losses = 0
        self.bets_placed_today  = 0
        self._checked_today: set = set()

        logger.info(
            f"[Favorito] Estratégia inicializada | "
            f"Stake: R${self.stake} | Odds: {self.min_odds}-{self.max_odds} | "
            f"Confiança: {self.min_confidence}% | Max: {self.max_concurrent}"
        )

    # ─── Limites ──────────────────────────────────────────────────────────────

    def _check_limits(self) -> bool:
        if self.daily_losses >= self.daily_loss_limit:
            logger.warning(f"[Favorito] Stop loss: R${self.daily_losses:.2f}")
            return False
        if self.daily_profit >= self.daily_profit_tgt:
            logger.info(
                f"[Favorito] 🔄 Meta atingida: +R${self.daily_profit:.2f} — "
                f"reiniciando contadores para novo ciclo."
            )
            self.daily_profit       = 0.0
            self.daily_losses       = 0.0
            self.consecutive_losses = 0
            self.bets_placed_today  = 0
            self._checked_events.clear()
        if self.consecutive_losses >= 3:
            logger.warning("[Favorito] 3 derrotas consecutivas. Pausando.")
            return False
        return True

    def _count_active(self) -> int:
        return sum(1 for b in self.active_bets.values() if b.status == "ACTIVE")

    # ─── Ciclo ────────────────────────────────────────────────────────────────

    def run_cycle(self):
        if not self._check_limits():
            return

        self._monitor_active_bets()

        if self._count_active() >= self.max_concurrent:
            logger.info(f"[Favorito] Máximo de apostas atingido ({self.max_concurrent}).")
            return

        remaining = self.api_football.get_requests_remaining()
        if remaining < 5:
            logger.warning(f"[Favorito] API-Football: {remaining} req. Aguardando reset.")
            return

        markets = self._find_markets()
        if not markets:
            logger.info("[Favorito] Nenhum mercado Match Odds disponível.")
            return

        for market in markets:
            if self._count_active() >= self.max_concurrent:
                break
            if not self._check_limits():
                break
            self._evaluate(market)
            time.sleep(1)

    # ─── Busca ────────────────────────────────────────────────────────────────

    def _find_markets(self) -> List[dict]:
        try:
            now = datetime.now(timezone.utc)
            markets = self.betfair.list_market_catalogue(
                filter_dict={
                    "eventTypeIds": [SOCCER_EVENT_TYPE_ID],
                    "marketTypeCodes": [MATCH_ODDS_MARKET],
                    "marketStartTime": {
                        "from": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "to": (now + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                    "inPlayOnly": False,
                },
                market_projection=["COMPETITION", "EVENT", "RUNNER_DESCRIPTION", "MARKET_START_TIME"],
                max_results=50,
            )
            new = [m for m in (markets or []) if m.get("marketId") not in self._checked_today]
            logger.info(f"[Favorito] Betfair: {len(markets or [])} mercados MATCH_ODDS, {len(new)} novos")
            return new
        except Exception as e:
            logger.error(f"[Favorito] Erro ao buscar mercados: {e}")
            return []

    # ─── Avaliação ────────────────────────────────────────────────────────────

    def _evaluate(self, catalogue: dict):
        market_id = catalogue.get("marketId")
        event     = catalogue.get("event", {})
        comp      = catalogue.get("competition", {})
        name      = event.get("name", "")
        home      = name.split(" v ")[0].strip() if " v " in name else ""
        away      = name.split(" v ")[1].strip() if " v " in name else ""
        league    = comp.get("name", "")

        if not home or not away:
            self._checked_today.add(market_id)
            return

        quality = _league_quality(league)
        if quality == "blocked":
            self._checked_today.add(market_id)
            logger.info(f"[Favorito] Liga bloqueada: {league}")
            return

        logger.info(f"[Favorito] Avaliando: {home} x {away} | {league}")

        # Odds dos 3 runners (Home / Draw / Away)
        book = self._get_book(market_id)
        if not book:
            return

        runners_info = self._extract_runners(catalogue, book)
        if not runners_info:
            self._checked_today.add(market_id)
            return

        # Identificar favorito (menor odds back)
        favorite = min(runners_info, key=lambda r: r["odds"])
        odds     = favorite["odds"]
        fav_name = favorite["name"]

        if not (self.min_odds <= odds <= self.max_odds):
            logger.info(
                f"[Favorito] Odds do favorito {odds} ({fav_name}) fora do range "
                f"[{self.min_odds}-{self.max_odds}] para {home} x {away}"
            )
            return

        # Mercado aceito para análise
        self._checked_today.add(market_id)

        # Stats API-Football
        home_stats, away_stats, h2h = {}, {}, {}
        has_stats = False
        fixture = self.api_football.get_fixture_by_teams(home, away)
        if fixture:
            lid = fixture["league"]["id"]
            hid = fixture["teams"]["home"]["id"]
            aid = fixture["teams"]["away"]["id"]
            hs  = self.api_football.get_team_stats(hid, lid, CURRENT_SEASON)
            as_ = self.api_football.get_team_stats(aid, lid, CURRENT_SEASON)
            h2h_raw = self.api_football.get_h2h(hid, aid)
            home_stats = self.api_football.extract_goals_stats(hs) if hs else {}
            away_stats = self.api_football.extract_goals_stats(as_) if as_ else {}
            h2h = self.api_football.extract_h2h_summary(h2h_raw, hid, aid)
            has_stats = bool(home_stats and away_stats)

        # Groq analisa se o favorito tem edge real
        is_home_fav = fav_name.lower() in home.lower() or home.lower() in fav_name.lower()
        analysis = self._analyze_favorite(
            home=home, away=away, league=league,
            favorite_name=fav_name, is_home_fav=is_home_fav,
            odds=odds, home_stats=home_stats, away_stats=away_stats,
            h2h=h2h, has_stats=has_stats,
        )

        if not analysis:
            logger.warning(f"[Favorito] Sem análise Groq para {home} x {away}")
            return

        effective_min = self.min_confidence if has_stats else self.min_confidence + 8
        confidence    = analysis.get("confidence", 0)

        if confidence < effective_min:
            logger.info(
                f"[Favorito] Groq NÃO recomendou: {home} x {away} | "
                f"Confiança: {confidence}% (mín: {effective_min}%) | "
                f"{analysis.get('reasoning', '')}"
            )
            return

        logger.info(
            f"[Favorito] ✅ APROVADO: {fav_name} vence {home} x {away} | "
            f"Odds: {odds} | Confiança: {confidence}% | {analysis.get('reasoning', '')}"
        )
        self._place_bet(
            market_id=market_id,
            selection_id=favorite["selection_id"],
            odds=odds,
            confidence=confidence,
            reasoning=analysis.get("reasoning", ""),
            home=home, away=away, fav_name=fav_name,
        )

    # ─── Groq para Favorito ───────────────────────────────────────────────────

    def _analyze_favorite(self, home, away, league, favorite_name, is_home_fav,
                          odds, home_stats, away_stats, h2h, has_stats) -> Optional[dict]:
        """Chama Groq para avaliar se o favorito tem edge real."""
        try:
            if has_stats and home_stats and away_stats:
                fav_stats  = home_stats if is_home_fav else away_stats
                opp_stats  = away_stats if is_home_fav else home_stats
                stats_block = (
                    f"ESTATÍSTICAS {favorite_name.upper()} (favorito):\n"
                    f"- Média gols marcados: {fav_stats.get('avg_scored_total', 'N/A')}\n"
                    f"- Média gols sofridos: {fav_stats.get('avg_conceded_total', 'N/A')}\n"
                    f"- Forma recente: {fav_stats.get('form', 'N/A')}\n"
                    f"- Jogos disputados: {fav_stats.get('games_played', 'N/A')}\n\n"
                    f"ESTATÍSTICAS ADVERSÁRIO:\n"
                    f"- Média gols marcados: {opp_stats.get('avg_scored_total', 'N/A')}\n"
                    f"- Média gols sofridos: {opp_stats.get('avg_conceded_total', 'N/A')}\n"
                    f"- Forma recente: {opp_stats.get('form', 'N/A')}\n\n"
                    f"H2H — Taxa de vitória do favorito nos últimos confrontos: "
                    f"{h2h.get('over25_rate', 'N/A')}\n"
                )
            else:
                stats_block = "AVISO: Sem dados estatísticos detalhados. Use seu conhecimento geral.\n"

            prompt = f"""Analise se o time favorito tem vantagem real neste jogo:

JOGO: {home} (casa) x {away} (fora)
LIGA: {league}
FAVORITO: {favorite_name} | ODDS BETFAIR: {odds}
MANDA EM CASA: {'SIM' if is_home_fav else 'NÃO'}

{stats_block}

Responda APENAS em JSON:
{{
  "confidence": <0-100: % de chance do FAVORITO vencer>,
  "expected_result": "<vitória favorito / empate / vitória azarão>",
  "risk_level": "<LOW|MEDIUM|HIGH>",
  "reasoning": "<1-2 frases em português>"
}}

Confidence alto (>70) quando:
- Favorito tem forma muito superior
- Odds 1.45-1.90 indicam vantagem real sem ser blowout
- Time mandante em boa fase contra visitante inferior
- H2H favorável"""

            headers = {
                "Authorization": f"Bearer {self.groq_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content":
                     "Você é analista de futebol especializado em apostas. "
                     "Responda SEMPRE em JSON válido, sem texto fora do JSON."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 300,
            }
            resp = requests.post(
                GROQ_API_URL, headers=headers, json=payload, timeout=20,
                proxies={"http": None, "https": None},
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            import json
            result = json.loads(content.strip())
            confidence = int(result.get("confidence", 50))
            logger.info(
                f"[Favorito] Groq | {home} x {away} | "
                f"Favorito: {favorite_name} | Confiança: {confidence}% | {result.get('reasoning','')}"
            )
            return result
        except Exception as e:
            logger.error(f"[Favorito] Erro Groq para {home} x {away}: {e}")
            return None

    # ─── Odds ─────────────────────────────────────────────────────────────────

    def _get_book(self, market_id: str) -> Optional[dict]:
        try:
            books = self.betfair.list_market_book(
                market_ids=[market_id],
                price_projection={"priceData": ["EX_BEST_OFFERS"],
                                  "exBestOffersOverrides": {"bestPricesDepth": 3}},
            )
            return books[0] if books else None
        except Exception as e:
            logger.error(f"[Favorito] Erro ao buscar odds {market_id}: {e}")
            return None

    def _extract_runners(self, catalogue: dict, book: dict) -> List[dict]:
        runners_desc = {rd["selectionId"]: rd.get("runnerName", "") for rd in catalogue.get("runners", [])}
        result = []
        for runner in book.get("runners", []):
            sel_id = runner.get("selectionId")
            backs  = runner.get("ex", {}).get("availableToBack", [])
            if backs and sel_id in runners_desc:
                result.append({
                    "selection_id": sel_id,
                    "name": runners_desc[sel_id],
                    "odds": backs[0].get("price", 999),
                })
        return result

    # ─── Apostar ──────────────────────────────────────────────────────────────

    def _place_bet(self, market_id, selection_id, odds, confidence, reasoning,
                   home, away, fav_name):
        try:
            customer_ref = f"FAV_{uuid.uuid4().hex[:12].upper()}"
            result = self.betfair.place_orders(
                market_id=market_id,
                instructions=[{
                    "instructionType": "LIMIT",
                    "selectionId": selection_id,
                    "side": "BACK",
                    "orderType": "LIMIT",
                    "limitOrder": {
                        "size": round(self.stake, 2),
                        "price": round(odds, 2),
                        "persistenceType": "LAPSE",
                    },
                }],
                customer_ref=customer_ref,
            )

            if not result or result.get("status") != "SUCCESS":
                err = result.get("errorCode", "?") if result else "Sem resposta"
                logger.error(f"[Favorito] Falha ao apostar: {err}")
                self._notify_error(home, away, err)
                return

            reports = result.get("instructionReports", [])
            bet_id  = reports[0].get("betId", customer_ref) if reports else customer_ref
            profit  = round(self.stake * (odds - 1), 2)

            bet = ActiveBet(
                bet_id=bet_id, market_id=market_id, selection_id=selection_id,
                home_team=home, away_team=away, favorite_name=fav_name,
                odds=odds, stake=self.stake, potential_profit=profit,
                placed_at=datetime.now(timezone.utc),
                confidence=confidence, reasoning=reasoning,
            )
            self.active_bets[bet_id] = bet
            self.bets_placed_today += 1

            logger.info(
                f"[Favorito] 🎯 APOSTA COLOCADA | {fav_name} vence {home} x {away} | "
                f"@ {odds} | Stake: R${self.stake} | Lucro pot.: R${profit} | ID: {bet_id}"
            )
            self._notify_placed(bet)
        except Exception as e:
            logger.error(f"[Favorito] Exceção ao apostar: {e}")
            self._notify_error(home, away, str(e))

    # ─── Monitor ──────────────────────────────────────────────────────────────

    def _monitor_active_bets(self):
        active = [b for b in self.active_bets.values() if b.status == "ACTIVE"]
        if not active:
            return

        now = datetime.now(timezone.utc)
        for bet in active:
            if (now - bet.placed_at).total_seconds() / 3600 > 6:
                logger.warning(f"[Favorito] Aposta {bet.bet_id} antiga (>6h). Marcando UNKNOWN.")
                bet.status = "UNKNOWN"

        active = [b for b in self.active_bets.values() if b.status == "ACTIVE"]
        if not active:
            return

        try:
            mids  = list({b.market_id for b in active})
            books = self.betfair.list_market_book(
                market_ids=mids,
                price_projection={"priceData": ["EX_BEST_OFFERS"]},
            )
            if not books:
                return
            for book in books:
                if book.get("status") in ("CLOSED", "SETTLED"):
                    for bet in [b for b in active if b.market_id == book["marketId"]]:
                        self._resolve(bet, book)
        except Exception as e:
            logger.error(f"[Favorito] Erro ao monitorar: {e}")

    def _resolve(self, bet: ActiveBet, book: dict):
        for r in book.get("runners", []):
            if r.get("selectionId") == bet.selection_id:
                s = r.get("status", "")
                if s == "WINNER":
                    bet.status = "WON"
                    bet.profit_loss = bet.potential_profit
                    self.daily_profit += bet.potential_profit
                    self.consecutive_losses = 0
                    logger.info(f"[Favorito] ✅ GANHOU | {bet.favorite_name} | +R${bet.potential_profit:.2f}")
                    self._notify_result(bet, won=True)
                elif s == "LOSER":
                    bet.status = "LOST"
                    bet.profit_loss = -bet.stake
                    self.daily_losses += bet.stake
                    self.consecutive_losses += 1
                    logger.info(f"[Favorito] ❌ PERDEU | {bet.favorite_name} | -R${bet.stake:.2f}")
                    self._notify_result(bet, won=False)
                break

    # ─── Notificações ─────────────────────────────────────────────────────────

    def _notify_placed(self, bet: ActiveBet):
        if not self.telegram or not self.telegram.enabled:
            return
        msg = (
            f"🎯 <b>NOVA APOSTA — Favorito</b>\n\n"
            f"⚽ <b>{bet.home_team} x {bet.away_team}</b>\n"
            f"🏆 Apostando em: <b>{bet.favorite_name}</b>\n"
            f"📊 Odds: <b>{bet.odds}</b>\n"
            f"💰 Stake: R${bet.stake:.2f} | Lucro pot.: <b>R${bet.potential_profit:.2f}</b>\n"
            f"🤖 Confiança IA: <b>{bet.confidence}%</b>\n"
            f"📝 {bet.reasoning}\n"
            f"📅 {bet.placed_at.strftime('%d/%m %H:%M')} UTC"
        )
        self.telegram.send_message(msg)

    def _notify_result(self, bet: ActiveBet, won: bool):
        if not self.telegram or not self.telegram.enabled:
            return
        emoji  = "✅" if won else "❌"
        result = f"+R${bet.profit_loss:.2f}" if won else f"-R${bet.stake:.2f}"
        msg = (
            f"{emoji} <b>RESULTADO — Favorito</b>\n\n"
            f"⚽ <b>{bet.home_team} x {bet.away_team}</b>\n"
            f"🏆 {bet.favorite_name}: {'GANHOU' if won else 'PERDEU'} <b>{result}</b>\n"
            f"📊 P&L dia: R${self.daily_profit - self.daily_losses:+.2f}\n"
            f"🎯 Apostas hoje: {self.bets_placed_today}"
        )
        self.telegram.send_message(msg)

    def _notify_error(self, home, away, error):
        if not self.telegram or not self.telegram.enabled:
            return
        self.telegram.send_message(
            f"⚠️ <b>ERRO AO APOSTAR [Favorito]</b>\n⚽ {home} x {away}\n❗ {error}"
        )

    # ─── Status ───────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "strategy": "favorite",
            "strategy_label": "Favorito (Match Odds)",
            "active_bets": self._count_active(),
            "bets_today": self.bets_placed_today,
            "daily_profit": round(self.daily_profit, 2),
            "daily_losses": round(self.daily_losses, 2),
            "net_today": round(self.daily_profit - self.daily_losses, 2),
            "consecutive_losses": self.consecutive_losses,
            "api_requests_remaining": self.api_football.get_requests_remaining(),
        }
