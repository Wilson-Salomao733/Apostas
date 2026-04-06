#!/usr/bin/env python3
"""
Estratégia Under Máximo — aposta no MAIOR Under X.5 disponível.

Lógica:
  Para cada jogo, verifica todos os mercados Under disponíveis na Betfair
  (Under 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5) e aposta no maior cuja
  odd Back seja >= min_odds.

  Exemplo:
    - Under 8.5 @ 1.03 → ignora (abaixo de min_odds)
    - Under 6.5 @ 1.08 → ignora
    - Under 4.5 @ 1.18 → ✅ APOSTA (maior Under com odd suficiente)

  Win rate esperado por linha:
    Under 2.5 → ~52%   Under 3.5 → ~73%
    Under 4.5 → ~88%   Under 5.5 → ~95%
    Under 6.5 → ~98%   Under 7.5+→ ~99%
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import requests

from api_football import APIFootball
from groq_analyzer import GroqAnalyzer

logger = logging.getLogger(__name__)

SOCCER_EVENT_TYPE_ID = "1"

# Mercados Under disponíveis na Betfair, do maior para o menor
UNDER_MARKETS_ORDERED = [
    ("OVER_UNDER_85", 8.5),
    ("OVER_UNDER_75", 7.5),
    ("OVER_UNDER_65", 6.5),
    ("OVER_UNDER_55", 5.5),
    ("OVER_UNDER_45", 4.5),
    ("OVER_UNDER_35", 3.5),
    ("OVER_UNDER_25", 2.5),
]

# IDs de todos os tipos para busca em batch
ALL_MARKET_TYPES = [m[0] for m in UNDER_MARKETS_ORDERED]

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.3-70b-versatile"
CURRENT_SEASON = 2025


@dataclass
class ActiveBet:
    bet_id: str
    market_id: str
    selection_id: int
    home_team: str
    away_team: str
    under_line: float       # ex: 4.5
    odds: float
    stake: float
    potential_profit: float
    placed_at: datetime
    confidence: int
    reasoning: str
    status: str = "ACTIVE"
    profit_loss: float = 0.0


class StrategyUnderMax:
    """
    Aposta no maior Under X.5 disponível com odds >= min_odds.
    A IA confirma que o jogo não será de alta pontuação.
    """

    def __init__(self, betfair_api, api_football: APIFootball,
                 groq_analyzer: GroqAnalyzer, config, db, telegram):
        self.betfair      = betfair_api
        self.api_football = api_football
        self.groq_key     = groq_analyzer.api_key
        self.db           = db
        self.telegram     = telegram

        self.stake            = float(config.get("under_max", "stake",              fallback="20.0"))
        self.min_odds         = float(config.get("under_max", "min_odds",           fallback="1.12"))
        self.max_under_line   = float(config.get("under_max", "max_under_line",     fallback="6.5"))
        self.min_under_line   = float(config.get("under_max", "min_under_line",     fallback="2.5"))
        self.min_confidence   = int(config.get("under_max",   "min_confidence",     fallback="68"))
        self.max_concurrent   = int(config.get("under_max",   "max_concurrent_bets",fallback="4"))
        self.daily_loss_limit = float(config.get("under_max", "daily_loss_limit",   fallback="60.0"))
        self.daily_profit_tgt = float(config.get("under_max", "daily_profit_target",fallback="80.0"))

        self.active_bets: Dict[str, ActiveBet] = {}
        self.daily_profit       = 0.0
        self.daily_losses       = 0.0
        self.consecutive_losses = 0
        self.bets_placed_today  = 0
        self._checked_events: set = set()  # event_id já processado

        logger.info(
            f"[UnderMax] Estratégia inicializada | "
            f"Stake: R${self.stake} | Min odds: {self.min_odds} | "
            f"Under range: {self.min_under_line}-{self.max_under_line} | "
            f"Confiança: {self.min_confidence}% | Max: {self.max_concurrent}"
        )

    # ─── Limites ──────────────────────────────────────────────────────────────

    def _check_limits(self) -> bool:
        if self.daily_losses >= self.daily_loss_limit:
            logger.warning(f"[UnderMax] Stop loss: R${self.daily_losses:.2f}")
            return False
        if self.daily_profit >= self.daily_profit_tgt:
            logger.info(f"[UnderMax] Meta atingida: +R${self.daily_profit:.2f}")
            return False
        if self.consecutive_losses >= 3:
            logger.warning("[UnderMax] 3 derrotas consecutivas. Pausando.")
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
            logger.info(f"[UnderMax] Máximo de apostas ativas ({self.max_concurrent}).")
            return

        # Buscar todos os mercados Under de uma vez
        events = self._fetch_all_under_markets()
        if not events:
            logger.info("[UnderMax] Nenhum mercado Under disponível.")
            return

        for event_id, markets_by_line in events.items():
            if self._count_active() >= self.max_concurrent:
                break
            if not self._check_limits():
                break
            if event_id in self._checked_events:
                continue
            self._evaluate_event(event_id, markets_by_line)
            time.sleep(1)

    # ─── Busca de mercados (batch) ────────────────────────────────────────────

    def _fetch_all_under_markets(self) -> Dict[str, Dict[float, dict]]:
        """
        Busca todos os mercados Under em um único lote.
        Retorna: {event_id: {under_line: catalogue_dict}}
        """
        try:
            now = datetime.now(timezone.utc)
            all_markets = self.betfair.list_market_catalogue(
                filter_dict={
                    "eventTypeIds": [SOCCER_EVENT_TYPE_ID],
                    "marketTypeCodes": ALL_MARKET_TYPES,
                    "marketStartTime": {
                        "from": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "to": (now + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                    "inPlayOnly": False,
                },
                market_projection=["COMPETITION", "EVENT", "RUNNER_DESCRIPTION", "MARKET_START_TIME"],
                max_results=200,
            )

            if not all_markets:
                return {}

            # Agrupar por evento: {event_id: {under_line: catalogue}}
            events: Dict[str, Dict[float, dict]] = {}
            for mkt in all_markets:
                event_id = mkt.get("event", {}).get("id", "")
                if not event_id:
                    continue

                # Determinar o Under line deste mercado
                mtype = mkt.get("marketType", "")
                under_line = self._market_type_to_line(mtype)
                if under_line is None:
                    continue

                # Filtrar range configurado
                if not (self.min_under_line <= under_line <= self.max_under_line):
                    continue

                if event_id not in events:
                    events[event_id] = {}
                events[event_id][under_line] = mkt

            logger.info(
                f"[UnderMax] Betfair: {len(all_markets)} mercados Under → "
                f"{len(events)} eventos distintos"
            )
            return events

        except Exception as e:
            logger.error(f"[UnderMax] Erro ao buscar mercados: {e}")
            return {}

    @staticmethod
    def _market_type_to_line(market_type: str) -> Optional[float]:
        mapping = {
            "OVER_UNDER_25": 2.5, "OVER_UNDER_35": 3.5,
            "OVER_UNDER_45": 4.5, "OVER_UNDER_55": 5.5,
            "OVER_UNDER_65": 6.5, "OVER_UNDER_75": 7.5,
            "OVER_UNDER_85": 8.5,
        }
        return mapping.get(market_type)

    # ─── Avaliação do evento ──────────────────────────────────────────────────

    def _evaluate_event(self, event_id: str, markets_by_line: Dict[float, dict]):
        """
        Para um evento, acha o maior Under X.5 com odds >= min_odds e aposta.
        """
        # Pegar metadados de qualquer mercado do evento
        sample_mkt = next(iter(markets_by_line.values()))
        event  = sample_mkt.get("event", {})
        comp   = sample_mkt.get("competition", {})
        name   = event.get("name", "")
        home   = name.split(" v ")[0].strip() if " v " in name else ""
        away   = name.split(" v ")[1].strip() if " v " in name else ""
        league = comp.get("name", "")

        if not home or not away:
            self._checked_events.add(event_id)
            return

        # ── Encontrar melhor Under X.5 ─────────────────────────────────────
        best_line, best_mkt, best_sel, best_odds = self._find_best_under(
            markets_by_line, home, away
        )

        if best_line is None:
            logger.info(
                f"[UnderMax] {home} x {away}: nenhum Under com odds >= {self.min_odds}"
            )
            self._checked_events.add(event_id)
            return

        # Marca evento como processado para não repetir chamadas de API
        self._checked_events.add(event_id)

        logger.info(
            f"[UnderMax] {home} x {away} | {league} | "
            f"Melhor Under: {best_line} @ {best_odds}"
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

        # ── Filtro rápido: evitar jogos de muitos gols ─────────────────────
        if has_stats and not self._stats_filter(home_stats, away_stats, best_line):
            logger.info(f"[UnderMax] Filtro estatístico: {home} x {away} parece de muitos gols. Pulando.")
            return

        # ── Groq confirma que jogo não vai ter gols demais ─────────────────
        analysis = self._analyze_under(
            home=home, away=away, league=league, under_line=best_line,
            odds=best_odds, home_stats=home_stats, away_stats=away_stats,
            h2h=h2h, has_stats=has_stats,
        )

        if not analysis:
            logger.warning(f"[UnderMax] Sem análise Groq para {home} x {away}")
            return

        confidence = analysis.get("confidence", 0)
        effective_min = self.min_confidence if has_stats else self.min_confidence + 7

        if confidence < effective_min:
            logger.info(
                f"[UnderMax] Groq NÃO aprovou: {home} x {away} | "
                f"Under {best_line} | Confiança: {confidence}% (mín: {effective_min}%) | "
                f"{analysis.get('reasoning', '')}"
            )
            return

        logger.info(
            f"[UnderMax] ✅ APROVADO: {home} x {away} | "
            f"Under {best_line} @ {best_odds} | Confiança: {confidence}%"
        )
        self._place_bet(
            market_id=best_mkt.get("marketId"),
            selection_id=best_sel,
            under_line=best_line,
            odds=best_odds,
            confidence=confidence,
            reasoning=analysis.get("reasoning", ""),
            home=home, away=away,
        )

    # ─── Encontrar melhor Under X.5 com odds suficientes ─────────────────────

    def _find_best_under(
        self,
        markets_by_line: Dict[float, dict],
        home: str,
        away: str,
    ) -> Tuple[Optional[float], Optional[dict], Optional[int], float]:
        """
        Percorre do Under mais alto para o mais baixo.
        Retorna (line, catalogue, selection_id, odds) do primeiro que passar min_odds.
        """
        # Ordenar do maior Under para o menor
        sorted_lines = sorted(markets_by_line.keys(), reverse=True)

        for line in sorted_lines:
            mkt = markets_by_line[line]
            market_id = mkt.get("marketId")

            book = self._get_book(market_id)
            if not book:
                continue

            sel_id, odds = self._extract_under_selection(mkt, book)
            if sel_id is None or odds <= 0:
                continue

            if odds >= self.min_odds:
                logger.debug(
                    f"[UnderMax] {home} x {away} | Under {line} @ {odds} ✓"
                )
                return line, mkt, sel_id, odds
            else:
                logger.debug(
                    f"[UnderMax] {home} x {away} | Under {line} @ {odds} → odds abaixo do mínimo {self.min_odds}"
                )

        return None, None, None, 0.0

    def _extract_under_selection(self, catalogue: dict, book: dict) -> Tuple[Optional[int], float]:
        """Extrai selectionId e best odds para a seleção Under."""
        runners_desc = catalogue.get("runners", [])
        under_id = None

        for rd in runners_desc:
            nm = rd.get("runnerName", "").lower()
            if "under" in nm:
                under_id = rd.get("selectionId")
                break

        # Fallback: segundo runner (geralmente Under)
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

    # ─── Filtro estatístico ───────────────────────────────────────────────────

    def _stats_filter(self, home: dict, away: dict, under_line: float) -> bool:
        """
        Rejeita apenas se a média de gols combinada sugere que o Under vai perder.
        Exemplo: Under 2.5 mas times marcam em média 2.5 cada = 5.0 total → rejeita.
        """
        ha = float(home.get("avg_scored_total") or 0)
        aa = float(away.get("avg_scored_total") or 0)
        avg_total = ha + aa
        # Se média histórica de gols > 80% do Under line → risco alto
        return avg_total <= (under_line * 0.80)

    # ─── Groq analysis ───────────────────────────────────────────────────────

    def _analyze_under(
        self, home, away, league, under_line, odds,
        home_stats, away_stats, h2h, has_stats,
    ) -> Optional[dict]:
        """Groq confirma se o jogo deve terminar com menos de X.5 gols."""
        try:
            if has_stats and home_stats and away_stats:
                stats_block = (
                    f"ESTATÍSTICAS {home.upper()}:\n"
                    f"- Média gols marcados: {home_stats.get('avg_scored_total', 'N/A')}\n"
                    f"- Média gols sofridos: {home_stats.get('avg_conceded_total', 'N/A')}\n"
                    f"- Forma recente: {home_stats.get('form', 'N/A')}\n\n"
                    f"ESTATÍSTICAS {away.upper()}:\n"
                    f"- Média gols marcados: {away_stats.get('avg_scored_total', 'N/A')}\n"
                    f"- Média gols sofridos: {away_stats.get('avg_conceded_total', 'N/A')}\n"
                    f"- Forma recente: {away_stats.get('form', 'N/A')}\n\n"
                    f"H2H — Média gols nos confrontos: {h2h.get('avg_goals_per_game', 'N/A')}\n"
                    f"H2H — Taxa Under 2.5 histórica: {1 - float(h2h.get('over25_rate', 0.5) or 0.5):.0%}\n"
                )
            else:
                stats_block = "Sem dados detalhados. Use conhecimento geral sobre os times.\n"

            prompt = f"""Analise se este jogo de futebol vai terminar com MENOS DE {under_line} gols:

JOGO: {home} (casa) x {away} (fora)
LIGA: {league}
APOSTA: Under {under_line} Gols | ODDS BETFAIR: {odds}

{stats_block}

Responda APENAS em JSON:
{{
  "confidence": <0-100: % de chance de terminar com MENOS DE {under_line} gols>,
  "expected_goals": <total de gols esperados>,
  "risk_level": "<LOW|MEDIUM|HIGH>",
  "reasoning": "<1-2 frases em português>"
}}

Confidence alto (>{self.min_confidence}) quando:
- Média de gols combinada bem abaixo de {under_line}
- Times defensivos ou em forma fraca
- H2H com poucos gols
- Nenhum sinal de jogo de alta pontuação"""

            headers = {
                "Authorization": f"Bearer {self.groq_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content":
                     "Você é analista de apostas esportivas. "
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
            logger.info(
                f"[UnderMax] Groq | {home} x {away} | Under {under_line} | "
                f"Confiança: {result.get('confidence', '?')}% | {result.get('reasoning', '')}"
            )
            return result
        except Exception as e:
            logger.error(f"[UnderMax] Erro Groq {home} x {away}: {e}")
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
            logger.error(f"[UnderMax] Erro ao buscar odds {market_id}: {e}")
            return None

    # ─── Apostar ──────────────────────────────────────────────────────────────

    def _place_bet(self, market_id, selection_id, under_line, odds,
                   confidence, reasoning, home, away):
        try:
            customer_ref = f"UND_{uuid.uuid4().hex[:12].upper()}"
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
                logger.error(f"[UnderMax] Falha ao apostar: {err}")
                self._notify_error(home, away, err)
                return

            reports = result.get("instructionReports", [])
            bet_id  = reports[0].get("betId", customer_ref) if reports else customer_ref
            profit  = round(self.stake * (odds - 1), 2)

            bet = ActiveBet(
                bet_id=bet_id, market_id=market_id, selection_id=selection_id,
                home_team=home, away_team=away, under_line=under_line,
                odds=odds, stake=self.stake, potential_profit=profit,
                placed_at=datetime.now(timezone.utc),
                confidence=confidence, reasoning=reasoning,
            )
            self.active_bets[bet_id] = bet
            self.bets_placed_today += 1

            logger.info(
                f"[UnderMax] 🎯 APOSTA COLOCADA | {home} x {away} | "
                f"Under {under_line} @ {odds} | Stake: R${self.stake} | "
                f"Lucro pot.: R${profit} | ID: {bet_id}"
            )
            self._notify_placed(bet)

        except Exception as e:
            logger.error(f"[UnderMax] Exceção ao apostar: {e}")
            self._notify_error(home, away, str(e))

    # ─── Monitor ──────────────────────────────────────────────────────────────

    def _monitor_active_bets(self):
        active = [b for b in self.active_bets.values() if b.status == "ACTIVE"]
        if not active:
            return

        now = datetime.now(timezone.utc)
        for bet in active:
            if (now - bet.placed_at).total_seconds() / 3600 > 6:
                logger.warning(f"[UnderMax] Aposta {bet.bet_id} antiga (>6h). Marcando UNKNOWN.")
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
            logger.error(f"[UnderMax] Erro ao monitorar: {e}")

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
                        f"[UnderMax] ✅ GANHOU | {bet.home_team} x {bet.away_team} | "
                        f"Under {bet.under_line} | +R${bet.potential_profit:.2f}"
                    )
                    self._notify_result(bet, won=True)
                elif s == "LOSER":
                    bet.status = "LOST"
                    bet.profit_loss = -bet.stake
                    self.daily_losses += bet.stake
                    self.consecutive_losses += 1
                    logger.info(
                        f"[UnderMax] ❌ PERDEU | {bet.home_team} x {bet.away_team} | "
                        f"Under {bet.under_line} | -R${bet.stake:.2f}"
                    )
                    self._notify_result(bet, won=False)
                break

    # ─── Notificações ─────────────────────────────────────────────────────────

    def _notify_placed(self, bet: ActiveBet):
        if not self.telegram or not self.telegram.enabled:
            return
        self.telegram.send_message(
            f"🎯 <b>NOVA APOSTA — Under {bet.under_line} Gols</b>\n\n"
            f"⚽ <b>{bet.home_team} x {bet.away_team}</b>\n"
            f"📊 Aposta: <b>Under {bet.under_line} Gols</b> @ {bet.odds}\n"
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
            f"{emoji} <b>RESULTADO — Under {bet.under_line} Gols</b>\n\n"
            f"⚽ <b>{bet.home_team} x {bet.away_team}</b>\n"
            f"{'GANHOU' if won else 'PERDEU'}: <b>{result}</b>\n"
            f"📊 P&L dia: R${self.daily_profit - self.daily_losses:+.2f}\n"
            f"🎯 Apostas hoje: {self.bets_placed_today}"
        )

    def _notify_error(self, home, away, error):
        if not self.telegram or not self.telegram.enabled:
            return
        self.telegram.send_message(
            f"⚠️ <b>ERRO AO APOSTAR [UnderMax]</b>\n⚽ {home} x {away}\n❗ {error}"
        )

    # ─── Status ───────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "strategy": "under_max",
            "strategy_label": "Estratégia 3 — Under Máximo",
            "active_bets": self._count_active(),
            "bets_today": self.bets_placed_today,
            "daily_profit": round(self.daily_profit, 2),
            "daily_losses": round(self.daily_losses, 2),
            "net_today": round(self.daily_profit - self.daily_losses, 2),
            "consecutive_losses": self.consecutive_losses,
            "api_requests_remaining": self.api_football.get_requests_remaining(),
        }
