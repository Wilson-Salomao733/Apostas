#!/usr/bin/env python3
"""
Estratégia Under 4.5 Fixo — aposta SEMPRE no Under 4.5 Gols.

Critério de entrada:
  - Mercado: OVER_UNDER_45 (Under 4.5 Goals)
  - Odd Back: entre min_odds e max_odds (padrão 1.25 – 1.45)
  - IA Groq confirma que o jogo não deve ter 5+ gols

Win rate histórico do Under 4.5: ~88%
Odds-alvo 1.25–1.45 → lucro esperado por aposta: R$5–R$9 (stake R$20)
"""

import json
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
MARKET_TYPE          = "OVER_UNDER_45"
UNDER_LINE           = 4.5
CURRENT_SEASON       = 2025

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.3-70b-versatile"


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
    status: str = "ACTIVE"
    profit_loss: float = 0.0


class StrategyUnder45:
    """
    Aposta fixo no Under 4.5 quando a odd estiver entre min_odds e max_odds.
    IA rejeita jogos com expectativa de alta pontuação.
    """

    def __init__(self, betfair_api, api_football: APIFootball,
                 groq_analyzer: GroqAnalyzer, config, db, telegram):
        self.betfair      = betfair_api
        self.api_football = api_football
        self.groq_key     = groq_analyzer.api_key
        self.db           = db
        self.telegram     = telegram

        self.stake            = float(config.get("under45", "stake",               fallback="20.0"))
        self.min_odds         = float(config.get("under45", "min_odds",            fallback="1.25"))
        self.max_odds         = float(config.get("under45", "max_odds",            fallback="1.45"))
        self.min_confidence   = int(config.get("under45",   "min_confidence",      fallback="70"))
        self.max_concurrent   = int(config.get("under45",   "max_concurrent_bets", fallback="4"))
        self.daily_loss_limit = float(config.get("under45", "daily_loss_limit",    fallback="80.0"))
        self.daily_profit_tgt = float(config.get("under45", "daily_profit_target", fallback="80.0"))

        self.active_bets: Dict[str, ActiveBet] = {}
        self.daily_profit       = 0.0
        self.daily_losses       = 0.0
        self.consecutive_losses = 0
        self.bets_placed_today  = 0
        self._checked_events: set = set()

        logger.info(
            f"[Under45] Estratégia inicializada | "
            f"Stake: R${self.stake} | Odds: {self.min_odds}–{self.max_odds} | "
            f"Confiança mín.: {self.min_confidence}% | Max concorrentes: {self.max_concurrent}"
        )

    # ─── Limites ──────────────────────────────────────────────────────────────

    def _check_limits(self) -> bool:
        if self.daily_losses >= self.daily_loss_limit:
            logger.warning(
                f"[Under45] 🔄 Stop loss do ciclo: R${self.daily_losses:.2f} — "
                f"reiniciando contadores (novo ciclo, apostas retomam)."
            )
            self.daily_profit       = 0.0
            self.daily_losses       = 0.0
            self.consecutive_losses = 0
            self.bets_placed_today  = 0
            self._checked_events.clear()
        if self.daily_profit >= self.daily_profit_tgt:
            logger.info(
                f"[Under45] 🔄 Meta atingida: +R${self.daily_profit:.2f} — "
                f"reiniciando contadores para novo ciclo."
            )
            self.daily_profit       = 0.0
            self.daily_losses       = 0.0
            self.consecutive_losses = 0
            self.bets_placed_today  = 0
            self._checked_events.clear()
        if self.consecutive_losses >= 3:
            logger.warning("[Under45] 3 derrotas seguidas — pausa de proteção.")
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
            logger.info(f"[Under45] Máximo de apostas ativas ({self.max_concurrent}).")
            return

        markets = self._fetch_markets()
        if not markets:
            logger.info("[Under45] Nenhum mercado Under 4.5 disponível.")
            return

        for mkt in markets:
            if self._count_active() >= self.max_concurrent:
                break
            if not self._check_limits():
                break
            event_id = mkt.get("event", {}).get("id", "")
            if event_id and event_id in self._checked_events:
                continue
            self._evaluate(mkt)
            time.sleep(1)

    # ─── Busca de mercados ────────────────────────────────────────────────────

    def _fetch_markets(self) -> List[dict]:
        try:
            now = datetime.now(timezone.utc)
            markets = self.betfair.list_market_catalogue(
                filter_dict={
                    "eventTypeIds": [SOCCER_EVENT_TYPE_ID],
                    "marketTypeCodes": [MARKET_TYPE],
                    "marketStartTime": {
                        "from": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "to": (now + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                    "inPlayOnly": False,
                },
                market_projection=["COMPETITION", "EVENT", "RUNNER_DESCRIPTION", "MARKET_START_TIME"],
                max_results=100,
            )
            logger.info(f"[Under45] Betfair: {len(markets or [])} mercados Under 4.5 encontrados")
            return markets or []
        except Exception as e:
            logger.error(f"[Under45] Erro ao buscar mercados: {e}")
            return []

    # ─── Avaliação ────────────────────────────────────────────────────────────

    def _evaluate(self, mkt: dict):
        event  = mkt.get("event", {})
        comp   = mkt.get("competition", {})
        name   = event.get("name", "")
        home   = name.split(" v ")[0].strip() if " v " in name else ""
        away   = name.split(" v ")[1].strip() if " v " in name else ""
        league = comp.get("name", "")
        event_id = event.get("id", "")

        if not home or not away:
            return

        # Odds
        book = self._get_book(mkt["marketId"])
        if not book:
            return

        sel_id, odds = self._extract_under_selection(mkt, book)
        if sel_id is None or odds <= 0:
            return

        # ── Filtro de odds ─────────────────────────────────────────────────
        if not (self.min_odds <= odds <= self.max_odds):
            logger.debug(
                f"[Under45] {home} x {away}: odd {odds} fora da faixa "
                f"[{self.min_odds}–{self.max_odds}]. Pulando."
            )
            if event_id:
                self._checked_events.add(event_id)
            return

        logger.info(
            f"[Under45] {home} x {away} | {league} | "
            f"Under 4.5 @ {odds} ✓ (faixa [{self.min_odds}–{self.max_odds}])"
        )

        # ── Stats API-Football ─────────────────────────────────────────────
        home_stats, away_stats, h2h = {}, {}, {}
        has_stats = False
        fixture = self.api_football.get_fixture_by_teams(home, away)
        if fixture:
            lid = fixture["league"]["id"]
            hid = fixture["teams"]["home"]["id"]
            aid = fixture["teams"]["away"]["id"]
            hs  = self.api_football.get_team_stats(hid, lid, CURRENT_SEASON)
            as_ = self.api_football.get_team_stats(aid, lid, CURRENT_SEASON)
            h2r = self.api_football.get_h2h(hid, aid)
            home_stats = self.api_football.extract_goals_stats(hs) if hs else {}
            away_stats = self.api_football.extract_goals_stats(as_) if as_ else {}
            h2h = self.api_football.extract_h2h_summary(h2r, hid, aid)
            has_stats = bool(home_stats and away_stats)

        # Rejeita rápido se média histórica combinada > 3.6 gols (muito perto de 4.5)
        if has_stats:
            ha = float(home_stats.get("avg_scored_total") or 0)
            aa = float(away_stats.get("avg_scored_total") or 0)
            if ha + aa > 3.6:
                logger.info(
                    f"[Under45] Filtro stats: {home} x {away} | "
                    f"média gols = {ha+aa:.1f} → risco alto para Under 4.5"
                )
                if event_id:
                    self._checked_events.add(event_id)
                return

        # ── Groq confirma ─────────────────────────────────────────────────
        analysis = self._analyze(
            home=home, away=away, league=league, odds=odds,
            home_stats=home_stats, away_stats=away_stats,
            h2h=h2h, has_stats=has_stats,
        )

        if event_id:
            self._checked_events.add(event_id)

        if not analysis:
            logger.warning(f"[Under45] Sem análise Groq para {home} x {away}")
            return

        confidence = analysis.get("confidence", 0)
        effective_min = self.min_confidence if has_stats else self.min_confidence + 7

        if confidence < effective_min:
            logger.info(
                f"[Under45] Groq NÃO aprovou | {home} x {away} | "
                f"Confiança: {confidence}% (mín: {effective_min}%) | "
                f"{analysis.get('reasoning', '')}"
            )
            return

        logger.info(
            f"[Under45] ✅ APROVADO | {home} x {away} | "
            f"Under 4.5 @ {odds} | Confiança: {confidence}%"
        )
        self._place_bet(
            market_id=mkt["marketId"], selection_id=sel_id,
            odds=odds, confidence=confidence,
            reasoning=analysis.get("reasoning", ""),
            home=home, away=away,
        )

    # ─── Extração da seleção Under ────────────────────────────────────────────

    def _extract_under_selection(self, catalogue: dict, book: dict):
        runners_desc = catalogue.get("runners", [])
        under_id = None

        for rd in runners_desc:
            nm = rd.get("runnerName", "").lower()
            if "under" in nm:
                under_id = rd.get("selectionId")
                break

        if not under_id and len(runners_desc) >= 2:
            under_id = runners_desc[1].get("selectionId")

        if not under_id:
            return None, 0.0

        for runner in book.get("runners", []):
            if runner.get("selectionId") == under_id:
                backs = runner.get("ex", {}).get("availableToBack", [])
                if backs:
                    return under_id, backs[0].get("price", 0.0)

        return None, 0.0

    # ─── Groq analysis ───────────────────────────────────────────────────────

    def _analyze(self, home, away, league, odds,
                 home_stats, away_stats, h2h, has_stats) -> Optional[dict]:
        try:
            if has_stats and home_stats and away_stats:
                ha = float(home_stats.get("avg_scored_total") or 0)
                hd = float(home_stats.get("avg_conceded_total") or 0)
                aa = float(away_stats.get("avg_scored_total") or 0)
                ad = float(away_stats.get("avg_conceded_total") or 0)
                avg_total = ha + aa
                stats_block = (
                    f"ESTATÍSTICAS {home.upper()}:\n"
                    f"- Média gols marcados: {ha}\n"
                    f"- Média gols sofridos: {hd}\n"
                    f"- Forma recente: {home_stats.get('form', 'N/A')}\n\n"
                    f"ESTATÍSTICAS {away.upper()}:\n"
                    f"- Média gols marcados: {aa}\n"
                    f"- Média gols sofridos: {ad}\n"
                    f"- Forma recente: {away_stats.get('form', 'N/A')}\n\n"
                    f"H2H — Média gols nos confrontos: {h2h.get('avg_goals_per_game', 'N/A')}\n"
                    f"H2H — % jogos com 5+ gols: {float(h2h.get('over45_rate', 0.12) or 0.12):.0%}\n"
                    f"Média total combinada: {avg_total:.2f} gols/jogo\n"
                )
            else:
                stats_block = (
                    "Sem dados detalhados disponíveis. "
                    "Use seu conhecimento geral sobre os times e a liga.\n"
                )

            prompt = f"""Analise se este jogo vai terminar com MENOS DE 4,5 GOLS (ou seja, máximo 4 gols):

JOGO: {home} (casa) x {away} (fora)
LIGA: {league}
APOSTA: Under 4.5 Gols | ODD BETFAIR: {odds}

{stats_block}

Responda APENAS em JSON:
{{
  "confidence": <0-100: probabilidade de terminar com 4 ou menos gols>,
  "expected_goals": <total de gols esperados>,
  "risk_level": "<LOW|MEDIUM|HIGH>",
  "reasoning": "<1-2 frases em português explicando a decisão>"
}}

Dê confidence alto (>={self.min_confidence}) quando:
- Média total combinada < 2.8 gols por jogo
- Times com defesas sólidas ou ofensivas fracas
- H2H com poucos jogos de muitos gols
- Nenhum sinal de que o jogo vá ter 5+ gols

Dê confidence baixo quando:
- Times artilheiros (média > 3.5 combinada)
- H2H com histórico de muitos gols
- Jogo de mata-mata onde times precisam marcar muito"""

            headers = {
                "Authorization": f"Bearer {self.groq_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content":
                     "Você é analista de apostas esportivas especialista em mercados de gols. "
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
            result = json.loads(content.strip())
            logger.info(
                f"[Under45] Groq | {home} x {away} | "
                f"Confiança: {result.get('confidence', '?')}% | "
                f"Gols esperados: {result.get('expected_goals', '?')} | "
                f"{result.get('reasoning', '')}"
            )
            return result
        except Exception as e:
            logger.error(f"[Under45] Erro Groq {home} x {away}: {e}")
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
            logger.error(f"[Under45] Erro ao buscar odds {market_id}: {e}")
            return None

    # ─── Apostar ──────────────────────────────────────────────────────────────

    def _place_bet(self, market_id, selection_id, odds, confidence, reasoning, home, away):
        try:
            customer_ref = f"U45_{uuid.uuid4().hex[:12].upper()}"
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
                logger.error(f"[Under45] Falha ao apostar: {err}")
                self._notify_error(home, away, err)
                return

            reports = result.get("instructionReports", [])
            bet_id  = reports[0].get("betId", customer_ref) if reports else customer_ref
            profit  = round(self.stake * (odds - 1), 2)

            bet = ActiveBet(
                bet_id=bet_id, market_id=market_id, selection_id=selection_id,
                home_team=home, away_team=away,
                odds=odds, stake=self.stake, potential_profit=profit,
                placed_at=datetime.now(timezone.utc),
                confidence=confidence, reasoning=reasoning,
            )
            self.active_bets[bet_id] = bet
            self.bets_placed_today += 1

            logger.info(
                f"[Under45] 🎯 APOSTA COLOCADA | {home} x {away} | "
                f"Under 4.5 @ {odds} | Stake: R${self.stake} | "
                f"Lucro pot.: R${profit} | ID: {bet_id}"
            )
            self._notify_placed(bet)

        except Exception as e:
            logger.error(f"[Under45] Exceção ao apostar: {e}")
            self._notify_error(home, away, str(e))

    # ─── Monitor ──────────────────────────────────────────────────────────────

    def _monitor_active_bets(self):
        active = [b for b in self.active_bets.values() if b.status == "ACTIVE"]
        if not active:
            return

        now = datetime.now(timezone.utc)
        for bet in active:
            if (now - bet.placed_at).total_seconds() / 3600 > 6:
                logger.warning(f"[Under45] Aposta {bet.bet_id} antiga (>6h). Marcando UNKNOWN.")
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
            logger.error(f"[Under45] Erro ao monitorar: {e}")

    def _resolve(self, bet: ActiveBet, book: dict):
        for r in book.get("runners", []):
            if r.get("selectionId") == bet.selection_id:
                s = r.get("status", "")
                if s == "WINNER":
                    bet.status = "WON"
                    bet.profit_loss = bet.potential_profit
                    self.daily_profit += bet.potential_profit
                    self.consecutive_losses = 0
                    logger.info(
                        f"[Under45] ✅ GANHOU | {bet.home_team} x {bet.away_team} | "
                        f"Under 4.5 | +R${bet.potential_profit:.2f}"
                    )
                    self._notify_result(bet, won=True)
                elif s == "LOSER":
                    bet.status = "LOST"
                    bet.profit_loss = -bet.stake
                    self.daily_losses += bet.stake
                    self.consecutive_losses += 1
                    logger.info(
                        f"[Under45] ❌ PERDEU | {bet.home_team} x {bet.away_team} | "
                        f"Under 4.5 | -R${bet.stake:.2f}"
                    )
                    self._notify_result(bet, won=False)
                break

    # ─── Notificações ─────────────────────────────────────────────────────────

    def _notify_placed(self, bet: ActiveBet):
        if not self.telegram or not self.telegram.enabled:
            return
        self.telegram.send_message(
            f"🎯 <b>NOVA APOSTA — Under 4.5 Gols</b>\n\n"
            f"⚽ <b>{bet.home_team} x {bet.away_team}</b>\n"
            f"📊 Aposta: <b>Under 4.5 Gols</b> @ {bet.odds}\n"
            f"💰 Stake: R${bet.stake:.2f} | Lucro pot.: <b>R${bet.potential_profit:.2f}</b>\n"
            f"🤖 Confiança IA: <b>{bet.confidence}%</b>\n"
            f"📝 {bet.reasoning}\n"
            f"📅 {bet.placed_at.strftime('%d/%m %H:%M')} UTC"
        )

    def _notify_result(self, bet: ActiveBet, won: bool):
        if not self.telegram or not self.telegram.enabled:
            return
        emoji  = "✅" if won else "❌"
        result = f"+R${bet.profit_loss:.2f}" if won else f"-R${bet.stake:.2f}"
        self.telegram.send_message(
            f"{emoji} <b>RESULTADO — Under 4.5 Gols</b>\n\n"
            f"⚽ <b>{bet.home_team} x {bet.away_team}</b>\n"
            f"{'GANHOU' if won else 'PERDEU'}: <b>{result}</b>\n"
            f"📊 P&L dia: R${self.daily_profit - self.daily_losses:+.2f}\n"
            f"🎯 Apostas hoje: {self.bets_placed_today}"
        )

    def _notify_error(self, home, away, error):
        if not self.telegram or not self.telegram.enabled:
            return
        self.telegram.send_message(
            f"⚠️ <b>ERRO AO APOSTAR [Under45]</b>\n⚽ {home} x {away}\n❗ {error}"
        )

    # ─── Status ───────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "strategy": "under45",
            "strategy_label": "Estratégia 4 — Under 4.5 Gols Fixo",
            "active_bets": self._count_active(),
            "bets_today": self.bets_placed_today,
            "daily_profit": round(self.daily_profit, 2),
            "daily_losses": round(self.daily_losses, 2),
            "net_today": round(self.daily_profit - self.daily_losses, 2),
            "consecutive_losses": self.consecutive_losses,
            "api_requests_remaining": self.api_football.get_requests_remaining(),
        }
