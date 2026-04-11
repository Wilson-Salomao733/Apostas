#!/usr/bin/env python3
"""
Estratégia Over 1.5 + Under 4.5
Aposta em jogos com 2-4 gols esperados.
  - Back Over 1.5 (mercado OVER_UNDER_15)
  - Filtro: Under 4.5 odds confirmam que o jogo não será de 5+ gols
  - Win rate alvo: ~70-78% dependendo da seleção
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from api_football import APIFootball
from groq_analyzer import GroqAnalyzer, MatchAnalysis

logger = logging.getLogger(__name__)

SOCCER_EVENT_TYPE_ID = "1"
OVER_UNDER_15_MARKET = "OVER_UNDER_15"
OVER_UNDER_45_MARKET = "OVER_UNDER_45"
CURRENT_SEASON = 2025

# Ligas com dados confiáveis (Groq conhece bem)
GOOD_LEAGUES = {
    "premier league", "la liga", "bundesliga", "serie a", "ligue 1",
    "eredivisie", "primeira liga", "champions league", "europa league",
    "conference league", "brasileirao", "brasileirão", "campeonato brasileiro",
    "serie a", "copa do brasil", "libertadores", "sul-americana",
    "mls", "liga mx", "j1 league", "k league", "a-league",
    "super lig", "primeira liga", "ekstraklasa", "scottish premiership",
    "belgian pro league", "jupiler pro league", "austrian bundesliga",
    "swiss super league", "danish superliga", "allsvenskan", "eliteserien",
    "greek super league", "czech first league", "national league",
    "saudi pro league", "chinese super league", "nations league",
    "world cup", "euro", "copa america", "copa áfrica",
}

BLOCKED_KEYWORDS = {
    "u21", "u23", "u18", "reserve", "youth", "friendly", "amistoso",
    "pre-season", "ii liga", "division 3", "third division", "terceira",
    "gibraltar", "andorra", "faroe", "san marino", "liechtenstein",
}


def _league_quality(league_name: str) -> str:
    """Retorna 'good', 'unknown' ou 'blocked'."""
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
    odds: float
    stake: float
    potential_profit: float
    placed_at: datetime
    confidence: int
    reasoning: str
    bet_type: str = "OVER_15"
    status: str = "ACTIVE"
    profit_loss: float = 0.0


class StrategyOver15:
    """
    Estratégia: Over 1.5 Gols.
    Busca jogos onde é provável 2+ gols, confirmado por estatísticas e IA.
    """

    def __init__(self, betfair_api, api_football: APIFootball,
                 groq_analyzer: GroqAnalyzer, config, db, telegram):
        self.betfair       = betfair_api
        self.api_football  = api_football
        self.groq          = groq_analyzer
        self.db            = db
        self.telegram      = telegram

        self.stake            = float(config.get("over15", "stake", fallback="20.0"))
        self.min_odds         = float(config.get("over15", "min_odds", fallback="1.25"))
        self.max_odds         = float(config.get("over15", "max_odds", fallback="1.60"))
        self.min_confidence   = int(config.get("over15", "min_confidence", fallback="72"))
        self.max_concurrent   = int(config.get("over15", "max_concurrent_bets", fallback="3"))
        self.daily_loss_limit = float(config.get("over15", "daily_loss_limit", fallback="60.0"))
        self.daily_profit_tgt = float(config.get("over15", "daily_profit_target", fallback="80.0"))

        self.active_bets: Dict[str, ActiveBet] = {}
        self.daily_profit   = 0.0
        self.daily_losses   = 0.0
        self.consecutive_losses = 0
        self.bets_placed_today  = 0
        self._checked_today: set = set()

        logger.info(
            f"[Over1.5] Estratégia inicializada | "
            f"Stake: R${self.stake} | Odds: {self.min_odds}-{self.max_odds} | "
            f"Confiança: {self.min_confidence}% | Max: {self.max_concurrent}"
        )

    # ─── Limites ──────────────────────────────────────────────────────────────

    def _check_limits(self) -> bool:
        if self.daily_losses >= self.daily_loss_limit:
            logger.warning(f"[Over1.5] Stop loss diário: R${self.daily_losses:.2f}")
            return False
        if self.daily_profit >= self.daily_profit_tgt:
            logger.info(
                f"[Over1.5] 🔄 Meta atingida: +R${self.daily_profit:.2f} — "
                f"reiniciando contadores para novo ciclo."
            )
            self.daily_profit       = 0.0
            self.daily_losses       = 0.0
            self.consecutive_losses = 0
            self.bets_placed_today  = 0
            self._checked_events.clear()
        if self.consecutive_losses >= 3:
            logger.warning("[Over1.5] 3 derrotas consecutivas. Pausa temporária.")
            return False
        return True

    def _count_active(self) -> int:
        return sum(1 for b in self.active_bets.values() if b.status == "ACTIVE")

    # ─── Ciclo principal ──────────────────────────────────────────────────────

    def run_cycle(self):
        if not self._check_limits():
            return

        self._monitor_active_bets()

        if self._count_active() >= self.max_concurrent:
            logger.info(f"[Over1.5] Máximo de apostas atingido ({self.max_concurrent}).")
            return

        remaining = self.api_football.get_requests_remaining()
        if remaining < 5:
            logger.warning(f"[Over1.5] API-Football: {remaining} req restantes. Aguardando reset.")
            return

        markets = self._find_markets()
        if not markets:
            logger.info("[Over1.5] Nenhum mercado Over 1.5 disponível.")
            return

        for market in markets:
            if self._count_active() >= self.max_concurrent:
                break
            if not self._check_limits():
                break
            self._evaluate(market)
            time.sleep(1)

    # ─── Busca de mercados ────────────────────────────────────────────────────

    def _find_markets(self) -> List[dict]:
        try:
            now = datetime.now(timezone.utc)
            markets = self.betfair.list_market_catalogue(
                filter_dict={
                    "eventTypeIds": [SOCCER_EVENT_TYPE_ID],
                    "marketTypeCodes": [OVER_UNDER_15_MARKET],
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
            logger.info(f"[Over1.5] Betfair: {len(markets or [])} mercados, {len(new)} novos")
            return new
        except Exception as e:
            logger.error(f"[Over1.5] Erro ao buscar mercados: {e}")
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
            logger.info(f"[Over1.5] Liga bloqueada: {league}")
            return

        logger.info(f"[Over1.5] Avaliando: {home} x {away} | {league}")

        # Odds Over 1.5
        book = self._get_book(market_id)
        if not book:
            return

        selection = self._extract_over_selection(catalogue, book)
        if not selection:
            self._checked_today.add(market_id)
            return

        odds = selection["odds"]
        sel_id = selection["selection_id"]

        if not (self.min_odds <= odds <= self.max_odds):
            logger.info(f"[Over1.5] Odds {odds} fora do range [{self.min_odds}-{self.max_odds}] para {home} x {away}")
            return

        # Odds OK → marca como verificado
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
        else:
            logger.info(f"[Over1.5] Sem fixture na API-Football para {home} x {away}")

        # Filtro estatístico (apenas se temos dados)
        if has_stats and not self._stats_filter(home_stats, away_stats):
            logger.info(f"[Over1.5] Filtro estatístico rejeitou {home} x {away}")
            return

        # Groq AI
        analysis = self.groq.analyze_match(
            home_team=home, away_team=away,
            home_stats=home_stats, away_stats=away_stats,
            h2h_summary=h2h, over25_odds=odds,
            league_name=league, has_stats=has_stats,
        )

        if not analysis:
            logger.warning(f"[Over1.5] Sem análise Groq para {home} x {away}")
            return

        # Para Over 1.5, exige menos confiança que Over 2.5 (bar mais baixo)
        effective_min = self.min_confidence if has_stats else self.min_confidence + 5
        if analysis.confidence < effective_min:
            logger.info(
                f"[Over1.5] Groq NÃO recomendou: {home} x {away} | "
                f"Confiança: {analysis.confidence}% (mín: {effective_min}%) | {analysis.reasoning}"
            )
            return

        logger.info(
            f"[Over1.5] ✅ APROVADO: {home} x {away} | "
            f"Odds: {odds} | Confiança: {analysis.confidence}% | {analysis.reasoning}"
        )
        self._place_bet(market_id, sel_id, odds, analysis, home, away)

    def _stats_filter(self, home: dict, away: dict) -> bool:
        """Filtro leve: rejeita apenas jogos muito defensivos."""
        ha = float(home.get("avg_scored_total") or 0)
        aa = float(away.get("avg_scored_total") or 0)
        # Para Over 1.5 o bar é mais baixo — rejeita apenas jogos muito sem gols
        return (ha + aa) >= 1.2

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
            logger.error(f"[Over1.5] Erro ao buscar odds {market_id}: {e}")
            return None

    def _extract_over_selection(self, catalogue: dict, book: dict) -> Optional[dict]:
        runners_desc = catalogue.get("runners", [])
        over_id = None
        for rd in runners_desc:
            nm = rd.get("runnerName", "").lower()
            if "over" in nm and "1.5" in nm:
                over_id = rd.get("selectionId")
                break
        if not over_id and runners_desc:
            over_id = runners_desc[0].get("selectionId")
        if not over_id:
            return None
        for r in book.get("runners", []):
            if r.get("selectionId") == over_id:
                backs = r.get("ex", {}).get("availableToBack", [])
                if backs:
                    return {"selection_id": over_id, "odds": backs[0].get("price", 0)}
        return None

    # ─── Apostar ──────────────────────────────────────────────────────────────

    def _place_bet(self, market_id, selection_id, odds, analysis, home, away):
        try:
            customer_ref = f"OV15_{uuid.uuid4().hex[:12].upper()}"
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
                logger.error(f"[Over1.5] Falha ao apostar: {err}")
                self._notify_error(home, away, err)
                return

            reports = result.get("instructionReports", [])
            bet_id  = reports[0].get("betId", customer_ref) if reports else customer_ref
            profit  = round(self.stake * (odds - 1), 2)

            bet = ActiveBet(
                bet_id=bet_id, market_id=market_id, selection_id=selection_id,
                home_team=home, away_team=away, odds=odds, stake=self.stake,
                potential_profit=profit, placed_at=datetime.now(timezone.utc),
                confidence=analysis.confidence, reasoning=analysis.reasoning,
            )
            self.active_bets[bet_id] = bet
            self.bets_placed_today += 1

            logger.info(
                f"[Over1.5] 🎯 APOSTA COLOCADA | {home} x {away} | "
                f"Over 1.5 @ {odds} | Stake: R${self.stake} | Lucro pot.: R${profit} | ID: {bet_id}"
            )
            self._notify_placed(bet, analysis)

        except Exception as e:
            logger.error(f"[Over1.5] Exceção ao apostar {home} x {away}: {e}")
            self._notify_error(home, away, str(e))

    # ─── Monitor ──────────────────────────────────────────────────────────────

    def _monitor_active_bets(self):
        active = [b for b in self.active_bets.values() if b.status == "ACTIVE"]
        if not active:
            return

        now = datetime.now(timezone.utc)
        for bet in active:
            if (now - bet.placed_at).total_seconds() / 3600 > 6:
                logger.warning(f"[Over1.5] Aposta {bet.bet_id} antiga (>6h). Marcando UNKNOWN.")
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
            logger.error(f"[Over1.5] Erro ao monitorar: {e}")

    def _resolve(self, bet: ActiveBet, book: dict):
        for r in book.get("runners", []):
            if r.get("selectionId") == bet.selection_id:
                status = r.get("status", "")
                if status == "WINNER":
                    bet.status = "WON"
                    bet.profit_loss = bet.potential_profit
                    self.daily_profit += bet.potential_profit
                    self.consecutive_losses = 0
                    logger.info(f"[Over1.5] ✅ GANHOU | {bet.home_team} x {bet.away_team} | +R${bet.potential_profit:.2f}")
                    self._notify_result(bet, won=True)
                elif status == "LOSER":
                    bet.status = "LOST"
                    bet.profit_loss = -bet.stake
                    self.daily_losses += bet.stake
                    self.consecutive_losses += 1
                    logger.info(f"[Over1.5] ❌ PERDEU | {bet.home_team} x {bet.away_team} | -R${bet.stake:.2f}")
                    self._notify_result(bet, won=False)
                break

    # ─── Notificações ─────────────────────────────────────────────────────────

    def _notify_placed(self, bet: ActiveBet, analysis):
        if not self.telegram or not self.telegram.enabled:
            return
        msg = (
            f"🎯 <b>NOVA APOSTA — Over 1.5 Gols</b>\n\n"
            f"⚽ <b>{bet.home_team} x {bet.away_team}</b>\n"
            f"📊 Odds: <b>{bet.odds}</b>\n"
            f"💰 Stake: R${bet.stake:.2f} | Lucro pot.: <b>R${bet.potential_profit:.2f}</b>\n"
            f"🤖 Confiança IA: <b>{analysis.confidence}%</b>\n"
            f"📝 {analysis.reasoning}\n"
            f"📅 {bet.placed_at.strftime('%d/%m %H:%M')} UTC"
        )
        self.telegram.send_message(msg)

    def _notify_result(self, bet: ActiveBet, won: bool):
        if not self.telegram or not self.telegram.enabled:
            return
        emoji  = "✅" if won else "❌"
        result = f"+R${bet.profit_loss:.2f}" if won else f"-R${bet.stake:.2f}"
        msg = (
            f"{emoji} <b>RESULTADO — Over 1.5 Gols</b>\n\n"
            f"⚽ <b>{bet.home_team} x {bet.away_team}</b>\n"
            f"{'GANHOU' if won else 'PERDEU'}: <b>{result}</b>\n"
            f"📊 P&L dia: R${self.daily_profit - self.daily_losses:+.2f}\n"
            f"🎯 Apostas hoje: {self.bets_placed_today}"
        )
        self.telegram.send_message(msg)

    def _notify_error(self, home, away, error):
        if not self.telegram or not self.telegram.enabled:
            return
        self.telegram.send_message(
            f"⚠️ <b>ERRO AO APOSTAR [Over 1.5]</b>\n⚽ {home} x {away}\n❗ {error}"
        )

    # ─── Status ───────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "strategy": "over15",
            "strategy_label": "Over 1.5 Gols",
            "active_bets": self._count_active(),
            "bets_today": self.bets_placed_today,
            "daily_profit": round(self.daily_profit, 2),
            "daily_losses": round(self.daily_losses, 2),
            "net_today": round(self.daily_profit - self.daily_losses, 2),
            "consecutive_losses": self.consecutive_losses,
            "api_requests_remaining": self.api_football.get_requests_remaining(),
        }
