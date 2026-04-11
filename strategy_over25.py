#!/usr/bin/env python3
"""
Estratégia Smart Goals — Over 2.5 Gols
Fluxo: Betfair → API-Football (stats) → Groq AI (análise) → Aposta
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from api_football import APIFootball
from groq_analyzer import GroqAnalyzer, MatchAnalysis

logger = logging.getLogger(__name__)

SOCCER_EVENT_TYPE_ID = "1"
OVER_UNDER_25_MARKET_TYPE = "OVER_UNDER_25"
OVER_25_SELECTION_NAME = "Over 2.5 Goals"
CURRENT_SEASON = 2025  # Temporada atual para API-Football

# Ligas aceitas — foco em ligas com dados confiáveis e histórico de gols
# Groq tem muito mais conhecimento sobre essas ligas
ACCEPTED_LEAGUES = {
    # Europa Elite
    "premier league", "la liga", "bundesliga", "serie a", "ligue 1",
    "eredivisie", "primeira liga", "portuguese primeira liga",
    "belgian pro league", "jupiler pro league",
    "scottish premiership", "turkish super lig", "süper lig",
    "russian premier league", "russian football national league",
    "austrian bundesliga", "swiss super league",
    "danish superliga", "norwegian eliteserien", "swedish allsvenskan",
    "greek super league", "czech first league", "polish ekstraklasa",
    # Competições Europeias
    "champions league", "uefa champions league",
    "europa league", "uefa europa league",
    "conference league", "uefa conference league",
    # América do Sul
    "brasileirao", "brasileirão", "série a", "serie a",
    "campeonato brasileiro", "copa do brasil",
    "argentina primera división", "primera división",
    "liga profesional", "superliga argentina",
    "colombian primera a", "liga betplay",
    "chilean primera división",
    # América do Norte/Central
    "mls", "major league soccer",
    "liga mx", "mexican primera division",
    # Ásia - Apenas top ligas
    "j1 league", "japanese j1",
    "k league 1", "korean k league",
    "chinese super league",
    "saudi professional league", "saudi pro league",
    # Outros grandes torneios
    "world cup", "copa mundial", "euro", "copa america", "copa américa",
    "nations league", "uefa nations league",
    "australian a-league", "a-league",  # Permite A-League com confiança maior
}

# Palavras-chave que BLOQUEIAM a aposta (ligas ruins / sem dados)
BLOCKED_LEAGUE_KEYWORDS = {
    "azerbaijan", "azerbaijani", "moldov", "faroe", "gibraltar", "andorra",
    "liechtenstein", "san marino", "kosovo", "northern ireland",
    "maltese", "maltá", "estonian", "latvian", "lithuanian",
    "belarusian", "azerbaijani", "georgian", "armenian",
    "kazakh", "uzbek", "kyrgyz",
    "cambodia", "cambodian", "myanmar", "laos", "vietnam",  # Ligas asiáticas fracas
    "bangladesh", "pakistan", "nepal", "sri lanka",
    "zambia", "zimbabwe", "cameroon", "cameroonian", "algerian",
    "tunisian", "libyan", "sudanese", "kenyan", "ugandan",
    "namibian", "tanzanian", "mozambique",
    "bolivian", "paraguayan", "ecuadorian", "peruvian",
    "ii liga", "2nd division", "segunda división", "segunda liga",
    "third", "3rd", "tercera", "terceira", "division 3",
    "reserve", "u21", "u23", "under-21", "under-23", "youth",
    "friendly", "amistoso", "pre-season",
}


def _is_league_accepted(league_name: str) -> tuple:
    """
    Retorna (aceita: bool, motivo: str).
    Verifica se a liga tem qualidade suficiente para apostar.
    """
    name_lower = league_name.lower()

    # Verificar bloqueios explícitos primeiro
    for blocked in BLOCKED_LEAGUE_KEYWORDS:
        if blocked in name_lower:
            return False, f"Liga bloqueada: contém '{blocked}'"

    # Verificar lista de aceitos
    for accepted in ACCEPTED_LEAGUES:
        if accepted in name_lower:
            return True, "Liga aceita"

    # Liga desconhecida: bloqueia por padrão (conservador)
    return False, f"Liga desconhecida/não listada: '{league_name}'"


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
    status: str = "ACTIVE"   # ACTIVE | WON | LOST | CANCELLED
    profit_loss: float = 0.0


class StrategyOver25:
    def __init__(self, betfair_api, api_football: APIFootball,
                 groq_analyzer: GroqAnalyzer, config, db, telegram):
        self.betfair = betfair_api
        self.api_football = api_football
        self.groq = groq_analyzer
        self.db = db
        self.telegram = telegram

        # Configurações carregadas do config
        self.stake = float(config.get("over25", "stake", fallback="20.0"))
        self.min_odds = float(config.get("over25", "min_odds", fallback="1.75"))
        self.max_odds = float(config.get("over25", "max_odds", fallback="2.50"))
        self.min_confidence = int(config.get("over25", "min_confidence", fallback="65"))
        self.max_concurrent = int(config.get("over25", "max_concurrent_bets", fallback="2"))
        self.daily_loss_limit = float(config.get("over25", "daily_loss_limit", fallback="60.0"))
        self.daily_profit_target = float(config.get("over25", "daily_profit_target", fallback="80.0"))

        # Estado
        self.active_bets: Dict[str, ActiveBet] = {}
        self.daily_profit = 0.0
        self.daily_losses = 0.0
        self.consecutive_losses = 0
        self.bets_placed_today = 0
        self._markets_checked_today: set = set()  # Evita re-checar o mesmo mercado

        logger.info(
            f"Estratégia Over 2.5 inicializada | "
            f"Stake: R${self.stake} | Odds: {self.min_odds}-{self.max_odds} | "
            f"Confiança mínima: {self.min_confidence}% | Max simultâneas: {self.max_concurrent}"
        )

    # ─── Limites diários ──────────────────────────────────────────────────────

    def _check_daily_limits(self) -> bool:
        """Retorna True se pode continuar apostando."""
        if self.daily_losses >= self.daily_loss_limit:
            logger.warning(
                f"Stop loss diário atingido: R${self.daily_losses:.2f} de perdas"
            )
            return False
        if self.daily_profit >= self.daily_profit_target:
            logger.info(
                f"🔄 Meta atingida: +R${self.daily_profit:.2f} — "
                f"reiniciando contadores para novo ciclo."
            )
            self.daily_profit       = 0.0
            self.daily_losses       = 0.0
            self.consecutive_losses = 0
            self._markets_checked_today.clear()
        if self.consecutive_losses >= 3:
            logger.warning("3 derrotas consecutivas. Pausando 2 horas.")
            return False
        return True

    def _count_active(self) -> int:
        return sum(1 for b in self.active_bets.values() if b.status == "ACTIVE")

    def _count_active_display(self) -> int:
        """Conta apostas ativas + UNKNOWN para exibição no status."""
        return sum(1 for b in self.active_bets.values() if b.status in ("ACTIVE", "UNKNOWN"))

    # ─── Busca de mercados Betfair ─────────────────────────────────────────────

    def find_over25_markets(self) -> List[dict]:
        """
        Busca mercados Over/Under 2.5 gols no Betfair para jogos
        que começam nas próximas 4 horas.
        """
        try:
            from datetime import timedelta
            now = datetime.now(timezone.utc)
            from_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            to_time = (now + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ")

            markets = self.betfair.list_market_catalogue(
                filter_dict={
                    "eventTypeIds": [SOCCER_EVENT_TYPE_ID],
                    "marketTypeCodes": [OVER_UNDER_25_MARKET_TYPE],
                    "marketStartTime": {"from": from_time, "to": to_time},
                    "inPlayOnly": False,
                },
                market_projection=[
                    "COMPETITION", "EVENT", "RUNNER_DESCRIPTION", "MARKET_START_TIME"
                ],
                max_results=50,
            )

            if not markets:
                return []

            # Filtrar mercados já verificados hoje
            new_markets = [
                m for m in markets
                if m.get("marketId") not in self._markets_checked_today
            ]

            logger.info(
                f"Betfair: {len(markets)} mercados Over 2.5 encontrados, "
                f"{len(new_markets)} novos para verificar"
            )
            return new_markets

        except Exception as e:
            logger.error(f"Erro ao buscar mercados Over 2.5: {e}")
            return []

    def get_market_odds(self, market_id: str) -> Optional[dict]:
        """Retorna as odds atuais do mercado (Over e Under)."""
        try:
            books = self.betfair.list_market_book(
                market_ids=[market_id],
                price_projection={
                    "priceData": ["EX_BEST_OFFERS"],
                    "exBestOffersOverrides": {"bestPricesDepth": 3},
                },
            )
            if not books:
                return None
            return books[0] if books else None
        except Exception as e:
            logger.error(f"Erro ao buscar odds do mercado {market_id}: {e}")
            return None

    def _extract_over25_selection(self, catalogue: dict, book: dict) -> Optional[dict]:
        """Extrai selectionId e best odds para Over 2.5 Goals."""
        try:
            # Encontrar runner "Over 2.5 Goals" pelo nome no catálogo
            runners_desc = catalogue.get("runners", [])
            over_runner_id = None
            for rd in runners_desc:
                name = rd.get("runnerName", "").lower()
                if "over" in name and "2.5" in name:
                    over_runner_id = rd.get("selectionId")
                    break

            if not over_runner_id:
                # Fallback: primeiro runner geralmente é Over
                if runners_desc:
                    over_runner_id = runners_desc[0].get("selectionId")

            if not over_runner_id:
                return None

            # Buscar odds no livro
            runners_book = book.get("runners", [])
            for runner in runners_book:
                if runner.get("selectionId") == over_runner_id:
                    ex = runner.get("ex", {})
                    available_to_back = ex.get("availableToBack", [])
                    if available_to_back:
                        best_back_price = available_to_back[0].get("price", 0)
                        return {
                            "selection_id": over_runner_id,
                            "odds": best_back_price,
                        }
            return None
        except Exception as e:
            logger.error(f"Erro ao extrair seleção Over 2.5: {e}")
            return None

    # ─── Pipeline principal ────────────────────────────────────────────────────

    def run_cycle(self):
        """
        Executa um ciclo completo da estratégia:
        1. Verifica limites diários
        2. Monitora apostas ativas
        3. Busca novas oportunidades
        4. Avalia e aposta
        """
        # 1. Checar limites
        if not self._check_daily_limits():
            return

        # 2. Verificar apostas ativas (settled)
        self._monitor_active_bets()

        # 3. Verificar se pode abrir mais apostas
        if self._count_active() >= self.max_concurrent:
            logger.info(
                f"Máximo de apostas simultâneas atingido ({self.max_concurrent}). Aguardando."
            )
            return

        # 4. Verificar orçamento de API (sem API-Football não avalia novos mercados, mas continua monitorando)
        remaining_api = self.api_football.get_requests_remaining()
        if remaining_api < 5:
            logger.warning(f"Apenas {remaining_api} requisições API restantes hoje. Aguardando reset às meia-noite.")
            return

        # 5. Buscar mercados no Betfair
        markets = self.find_over25_markets()
        if not markets:
            logger.info("Nenhum mercado Over 2.5 disponível no momento.")
            return

        # 6. Avaliar cada mercado
        for market in markets:
            if self._count_active() >= self.max_concurrent:
                break
            if not self._check_daily_limits():
                break
            self._evaluate_and_bet(market)
            time.sleep(1)  # Rate limit gentil

    def _evaluate_and_bet(self, catalogue: dict):
        """Pipeline de avaliação + aposta para um mercado."""
        market_id = catalogue.get("marketId")
        # NÃO adiciona aqui ainda — só após passar o filtro de odds
        # (mercados com odds fora do range devem ser reavaliados se as odds mudarem)

        event = catalogue.get("event", {})
        competition = catalogue.get("competition", {})
        name = event.get("name", "")
        home_team = name.split(" v ")[0].strip() if " v " in name else ""
        away_team = name.split(" v ")[1].strip() if " v " in name else ""
        league_name = competition.get("name", "")

        if not home_team or not away_team:
            self._markets_checked_today.add(market_id)
            logger.debug(f"Nomes de times não identificados no mercado {market_id}: {name}")
            return

        # ── Filtro de qualidade de liga ───────────────────────────────────────
        league_ok, league_reason = _is_league_accepted(league_name)
        if not league_ok:
            logger.info(f"Liga ignorada — {league_reason}. Pulando {home_team} x {away_team}.")
            self._markets_checked_today.add(market_id)
            return

        logger.info(f"Avaliando: {home_team} x {away_team} | {league_name}")

        # ── Passo 1: Odds do Betfair ──────────────────────────────────────────
        book = self.get_market_odds(market_id)
        if not book:
            return

        selection = self._extract_over25_selection(catalogue, book)
        if not selection:
            self._markets_checked_today.add(market_id)
            logger.debug(f"Seleção Over 2.5 não encontrada em {market_id}")
            return

        odds = selection["odds"]
        selection_id = selection["selection_id"]

        if not (self.min_odds <= odds <= self.max_odds):
            logger.info(
                f"Odds {odds} fora do range [{self.min_odds}-{self.max_odds}] "
                f"para {home_team} x {away_team}. Será reavaliado no próximo ciclo."
            )
            # NÃO adiciona ao set — odds podem mudar no próximo ciclo
            return

        # Odds OK → marca como verificado para não re-gastar chamadas de API
        self._markets_checked_today.add(market_id)

        # ── Passo 2: Dados da API-Football (opcional) ─────────────────────────
        home_stats: dict = {}
        away_stats: dict = {}
        h2h_summary: dict = {}
        has_stats = False

        fixture = self.api_football.get_fixture_by_teams(home_team, away_team)
        if fixture:
            league_id = fixture["league"]["id"]
            home_id   = fixture["teams"]["home"]["id"]
            away_id   = fixture["teams"]["away"]["id"]

            home_stats_raw = self.api_football.get_team_stats(home_id, league_id, CURRENT_SEASON)
            away_stats_raw = self.api_football.get_team_stats(away_id, league_id, CURRENT_SEASON)
            h2h_raw        = self.api_football.get_h2h(home_id, away_id)

            home_stats   = self.api_football.extract_goals_stats(home_stats_raw) if home_stats_raw else {}
            away_stats   = self.api_football.extract_goals_stats(away_stats_raw) if away_stats_raw else {}
            h2h_summary  = self.api_football.extract_h2h_summary(h2h_raw, home_id, away_id)
            has_stats    = bool(home_stats and away_stats)
        else:
            logger.info(
                f"Fixture não encontrada na API-Football para {home_team} x {away_team} "
                f"— prosseguindo com análise Groq pura."
            )

        # ── Passo 3: Filtro estatístico (apenas se temos dados) ───────────────
        if has_stats and not self._passes_stats_filter(home_stats, away_stats, h2h_summary):
            logger.info(f"Filtro estatístico rejeitou {home_team} x {away_team}. Pulando.")
            return

        # ── Passo 4: Análise Groq AI ───────────────────────────────────────────
        analysis = self.groq.analyze_match(
            home_team=home_team,
            away_team=away_team,
            home_stats=home_stats,
            away_stats=away_stats,
            h2h_summary=h2h_summary,
            over25_odds=odds,
            league_name=league_name,
            has_stats=has_stats,
        )

        if not analysis:
            logger.warning(f"Groq não retornou análise para {home_team} x {away_team}")
            return

        if not analysis.recommend_bet:
            logger.info(
                f"Groq NÃO recomendou: {home_team} x {away_team} | "
                f"Confiança: {analysis.confidence}% (mín: {self.min_confidence}%) | "
                f"{analysis.reasoning}"
            )
            return

        # ── Passo 5: APOSTAR! ─────────────────────────────────────────────────
        logger.info(
            f"✅ APROVADO: {home_team} x {away_team} | "
            f"Odds: {odds} | Confiança: {analysis.confidence}% | "
            f"Risco: {analysis.risk_level} | {analysis.reasoning}"
        )
        self._place_bet(market_id, selection_id, odds, analysis, home_team, away_team)

    def _passes_stats_filter(self, home_stats: dict, away_stats: dict, h2h: dict) -> bool:
        """
        Filtro estatístico rápido antes de chamar a IA.
        Objetivo: eliminar jogos CLARAMENTE ruins, não ser restritivo demais.
        """
        if not home_stats or not away_stats:
            return False

        home_att = float(home_stats.get("avg_scored_total") or 0)
        away_att = float(away_stats.get("avg_scored_total") or 0)
        combined_attack = home_att + away_att

        # Descarta apenas jogos muito defensivos (menos de 1.4 gols combinados)
        if combined_attack < 1.4:
            return False

        home_def = float(home_stats.get("avg_conceded_total") or 0)
        away_def = float(away_stats.get("avg_conceded_total") or 0)
        combined_defense = home_def + away_def

        # H2H: só bloqueia se tivermos 4+ jogos com taxa Over 2.5 muito baixa (<25%)
        if h2h and h2h.get("matches_analyzed", 0) >= 4:
            if h2h.get("over25_rate", 0) < 0.25:
                return False

        # Passa se: ataque combinado razoável OU defesas permeáveis
        decent_attack    = combined_attack >= 2.0
        weak_defense     = combined_defense >= 1.6

        return decent_attack or weak_defense

    # ─── Execução da aposta ────────────────────────────────────────────────────

    def _place_bet(
        self,
        market_id: str,
        selection_id: int,
        odds: float,
        analysis: MatchAnalysis,
        home_team: str,
        away_team: str,
    ):
        """Coloca a aposta no Betfair e registra."""
        try:
            instructions = [
                {
                    "instructionType": "LIMIT",
                    "selectionId": selection_id,
                    "side": "BACK",
                    "orderType": "LIMIT",
                    "limitOrder": {
                        "size": round(self.stake, 2),
                        "price": round(odds, 2),
                        "persistenceType": "LAPSE",
                    },
                }
            ]

            customer_ref = f"OV25_{uuid.uuid4().hex[:12].upper()}"
            result = self.betfair.place_orders(
                market_id=market_id,
                instructions=instructions,
                customer_ref=customer_ref,
            )

            if not result or result.get("status") != "SUCCESS":
                error_msg = result.get("errorCode", "Desconhecido") if result else "Sem resposta"
                logger.error(f"Falha ao colocar aposta: {error_msg}")
                self._notify_error(home_team, away_team, error_msg)
                return

            # Extrair bet_id
            bet_id = customer_ref
            instruction_reports = result.get("instructionReports", [])
            if instruction_reports:
                bet_id = instruction_reports[0].get("betId", customer_ref)

            potential_profit = round(self.stake * (odds - 1), 2)

            active_bet = ActiveBet(
                bet_id=bet_id,
                market_id=market_id,
                selection_id=selection_id,
                home_team=home_team,
                away_team=away_team,
                odds=odds,
                stake=self.stake,
                potential_profit=potential_profit,
                placed_at=datetime.now(timezone.utc),
                confidence=analysis.confidence,
                reasoning=analysis.reasoning,
            )

            self.active_bets[bet_id] = active_bet
            self.bets_placed_today += 1

            logger.info(
                f"APOSTA COLOCADA | {home_team} x {away_team} | "
                f"Over 2.5 @ {odds} | Stake: R${self.stake} | "
                f"Lucro potencial: R${potential_profit} | BetID: {bet_id}"
            )

            self._notify_bet_placed(active_bet, analysis)

        except Exception as e:
            logger.error(f"Exceção ao colocar aposta {home_team} x {away_team}: {e}")
            self._notify_error(home_team, away_team, str(e))

    # ─── Monitoramento de apostas ativas ──────────────────────────────────────

    def _monitor_active_bets(self):
        """Verifica o status das apostas ativas no Betfair."""
        active_bets = [b for b in self.active_bets.values() if b.status == "ACTIVE"]
        if not active_bets:
            return

        # Limpar apostas muito antigas (>6h) que provavelmente já foram resolvidas
        # mas não pudemos verificar por token expirado — marca como UNKNOWN para desbloquear
        now = datetime.now(timezone.utc)
        for bet in active_bets:
            age_hours = (now - bet.placed_at).total_seconds() / 3600
            if age_hours > 6:
                logger.warning(
                    f"Aposta {bet.bet_id} ({bet.home_team} x {bet.away_team}) "
                    f"está ativa há {age_hours:.1f}h. Marcando como UNKNOWN para desbloquear o bot."
                )
                bet.status = "UNKNOWN"

        active_bets = [b for b in self.active_bets.values() if b.status == "ACTIVE"]
        if not active_bets:
            return

        try:
            market_ids = list({b.market_id for b in active_bets})
            books = self.betfair.list_market_book(
                market_ids=market_ids,
                price_projection={"priceData": ["EX_BEST_OFFERS"]},
            )
            if not books:
                return

            for book in books:
                market_id = book.get("marketId")
                market_status = book.get("status")

                # Mercado fechado = resultado conhecido
                if market_status in ("CLOSED", "SETTLED"):
                    bets_in_market = [
                        b for b in self.active_bets.values()
                        if b.market_id == market_id and b.status == "ACTIVE"
                    ]
                    for bet in bets_in_market:
                        self._resolve_bet(bet, book)

        except Exception as e:
            logger.error(f"Erro ao monitorar apostas ativas: {e}")

    def _resolve_bet(self, bet: ActiveBet, book: dict):
        """Marca aposta como ganha ou perdida com base no resultado do mercado."""
        try:
            # Encontrar o runner correspondente
            runners = book.get("runners", [])
            for runner in runners:
                if runner.get("selectionId") == bet.selection_id:
                    status = runner.get("status", "")
                    if status == "WINNER":
                        bet.status = "WON"
                        bet.profit_loss = bet.potential_profit
                        self.daily_profit += bet.potential_profit
                        self.consecutive_losses = 0
                        logger.info(
                            f"GANHOU | {bet.home_team} x {bet.away_team} | "
                            f"+R${bet.potential_profit:.2f}"
                        )
                        self._notify_result(bet, won=True)
                    elif status == "LOSER":
                        bet.status = "LOST"
                        bet.profit_loss = -bet.stake
                        self.daily_losses += bet.stake
                        self.consecutive_losses += 1
                        logger.info(
                            f"PERDEU | {bet.home_team} x {bet.away_team} | "
                            f"-R${bet.stake:.2f}"
                        )
                        self._notify_result(bet, won=False)
                    break
        except Exception as e:
            logger.error(f"Erro ao resolver aposta {bet.bet_id}: {e}")

    # ─── Notificações Telegram ────────────────────────────────────────────────

    def _notify_bet_placed(self, bet: ActiveBet, analysis: MatchAnalysis):
        if not self.telegram or not self.telegram.enabled:
            return
        msg = (
            f"🎯 <b>NOVA APOSTA — Over 2.5 Gols</b>\n\n"
            f"⚽ <b>{bet.home_team} x {bet.away_team}</b>\n"
            f"📊 Odds: <b>{bet.odds}</b>\n"
            f"💰 Stake: R${bet.stake:.2f} | Lucro pot.: <b>R${bet.potential_profit:.2f}</b>\n"
            f"🤖 Confiança IA: <b>{analysis.confidence}%</b> | Risco: {analysis.risk_level}\n"
            f"📝 {analysis.reasoning}\n"
            f"🔢 Gols esperados: ~{analysis.expected_goals:.1f}\n"
            f"📅 {bet.placed_at.strftime('%d/%m %H:%M')} UTC"
        )
        self.telegram.send_message(msg)

    def _notify_result(self, bet: ActiveBet, won: bool):
        if not self.telegram or not self.telegram.enabled:
            return
        emoji = "✅" if won else "❌"
        result_str = f"+R${bet.profit_loss:.2f}" if won else f"-R${bet.stake:.2f}"
        msg = (
            f"{emoji} <b>RESULTADO — Over 2.5 Gols</b>\n\n"
            f"⚽ <b>{bet.home_team} x {bet.away_team}</b>\n"
            f"{'GANHOU' if won else 'PERDEU'}: <b>{result_str}</b>\n"
            f"📊 P&L dia: R${self.daily_profit - self.daily_losses:.2f} "
            f"(+{self.daily_profit:.2f} / -{self.daily_losses:.2f})\n"
            f"🎯 Apostas hoje: {self.bets_placed_today}"
        )
        self.telegram.send_message(msg)

    def _notify_error(self, home_team: str, away_team: str, error: str):
        if not self.telegram or not self.telegram.enabled:
            return
        msg = (
            f"⚠️ <b>ERRO AO APOSTAR</b>\n"
            f"⚽ {home_team} x {away_team}\n"
            f"❗ {error}"
        )
        self.telegram.send_message(msg)

    # ─── Status ───────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "active_bets": self._count_active(),
            "bets_today": self.bets_placed_today,
            "daily_profit": round(self.daily_profit, 2),
            "daily_losses": round(self.daily_losses, 2),
            "net_today": round(self.daily_profit - self.daily_losses, 2),
            "consecutive_losses": self.consecutive_losses,
            "api_requests_remaining": self.api_football.get_requests_remaining(),
        }
