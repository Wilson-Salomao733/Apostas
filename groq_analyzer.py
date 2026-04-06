#!/usr/bin/env python3
"""
Análise de jogos usando Groq AI (LLaMA 3.3 70B)
Avalia se um jogo tem potencial para Over 2.5 gols
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional
import requests

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"


@dataclass
class MatchAnalysis:
    confidence: int          # 0-100: confiança em Over 2.5 gols
    recommend_bet: bool      # True se recomenda apostar
    expected_goals: float    # Previsão de gols totais
    risk_level: str          # LOW / MEDIUM / HIGH
    reasoning: str           # Justificativa curta
    home_team: str
    away_team: str
    over25_odds: float


class GroqAnalyzer:
    def __init__(self, api_key: str, min_confidence: int = 65):
        self.api_key = api_key
        self.min_confidence = min_confidence

    def analyze_match(
        self,
        home_team: str,
        away_team: str,
        home_stats: dict,
        away_stats: dict,
        h2h_summary: dict,
        over25_odds: float,
        league_name: str = "",
        has_stats: bool = True,
    ) -> Optional[MatchAnalysis]:
        """
        Envia estatísticas para Groq e obtém análise de Over 2.5 gols.
        Retorna None em caso de erro.
        """
        prompt = self._build_prompt(
            home_team, away_team, home_stats, away_stats, h2h_summary, over25_odds, league_name, has_stats
        )
        # Quando não há dados estatísticos, exige confiança maior para compensar a incerteza
        effective_min = self.min_confidence + 10 if not has_stats else self.min_confidence

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": GROQ_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Você é um analista especializado em apostas esportivas de futebol. "
                            "Sua única função é avaliar se um jogo tem alta probabilidade de ter "
                            "3 ou mais gols (Over 2.5). Responda SEMPRE em JSON válido, sem texto fora do JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 400,
            }

            resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=20,
                                 proxies={'http': None, 'https': None})
            resp.raise_for_status()
            data = resp.json()

            content = data["choices"][0]["message"]["content"].strip()
            # Remover markdown se presente
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            content = content.strip()

            result = json.loads(content)

            confidence = int(result.get("confidence", 50))
            expected_goals = float(result.get("expected_goals", 2.0))
            risk_level = str(result.get("risk_level", "MEDIUM")).upper()
            reasoning = str(result.get("reasoning", ""))

            recommend = confidence >= effective_min

            logger.info(
                f"Groq Analysis | {home_team} x {away_team} | "
                f"Confiança: {confidence}% | Gols esperados: {expected_goals:.1f} | "
                f"Risco: {risk_level} | Recomenda: {'SIM' if recommend else 'NÃO'}"
            )

            return MatchAnalysis(
                confidence=confidence,
                recommend_bet=recommend,
                expected_goals=expected_goals,
                risk_level=risk_level,
                reasoning=reasoning,
                home_team=home_team,
                away_team=away_team,
                over25_odds=over25_odds,
            )

        except json.JSONDecodeError as e:
            logger.error(f"Groq retornou JSON inválido: {e} | Resposta: {content[:200]}")
            return None
        except Exception as e:
            logger.error(f"Erro na análise Groq para {home_team} x {away_team}: {e}")
            return None

    def _build_prompt(
        self,
        home_team: str,
        away_team: str,
        home_stats: dict,
        away_stats: dict,
        h2h: dict,
        over25_odds: float,
        league_name: str,
        has_stats: bool = True,
    ) -> str:
        """Monta o prompt com as estatísticas do jogo."""

        if has_stats and home_stats and away_stats:
            home_info = (
                f"- Média gols marcados (geral): {home_stats.get('avg_scored_total', 'N/A')}\n"
                f"- Média gols marcados (casa): {home_stats.get('avg_scored_home', 'N/A')}\n"
                f"- Média gols sofridos (geral): {home_stats.get('avg_conceded_total', 'N/A')}\n"
                f"- Forma recente: {home_stats.get('form', 'N/A')}\n"
                f"- Jogos disputados: {home_stats.get('games_played', 'N/A')}"
            )
            away_info = (
                f"- Média gols marcados (geral): {away_stats.get('avg_scored_total', 'N/A')}\n"
                f"- Média gols marcados (fora): {away_stats.get('avg_scored_away', 'N/A')}\n"
                f"- Média gols sofridos (geral): {away_stats.get('avg_conceded_total', 'N/A')}\n"
                f"- Forma recente: {away_stats.get('form', 'N/A')}\n"
                f"- Jogos disputados: {away_stats.get('games_played', 'N/A')}"
            )
            h2h_info = (
                f"- Jogos analisados: {h2h.get('matches_analyzed', 'N/A')}\n"
                f"- Média de gols nos confrontos: {h2h.get('avg_goals_per_game', 'N/A')}\n"
                f"- Jogos com 3+ gols nos últimos 5: {h2h.get('over25_in_last_5', 'N/A')}/5\n"
                f"- Taxa Over 2.5 no H2H: {h2h.get('over25_rate', 'N/A')}\n"
                f"- Gols por partida (mais recentes primeiro): {h2h.get('goals_per_match', [])}"
            )
            try:
                ha = float(home_stats.get("avg_scored_home") or home_stats.get("avg_scored_total") or 1.2)
                aa = float(away_stats.get("avg_scored_away") or away_stats.get("avg_scored_total") or 1.0)
                hd = float(home_stats.get("avg_conceded_home") or home_stats.get("avg_conceded_total") or 1.2)
                ad = float(away_stats.get("avg_conceded_away") or away_stats.get("avg_conceded_total") or 1.2)
                xg_hint = round((ha + ad) / 2 + (aa + hd) / 2, 2)
            except Exception:
                xg_hint = 2.5

            stats_block = f"""
ESTATÍSTICAS {home_team.upper()} (mandante):
{home_info}

ESTATÍSTICAS {away_team.upper()} (visitante):
{away_info}

HISTÓRICO DE CONFRONTOS DIRETOS:
{h2h_info}

xG ESTIMADO (referência): {xg_hint}
"""
            criteria = (
                "Critérios para confidence alto (>65):\n"
                "- Média combinada de gols > 2.0\n"
                "- H2H com 3+ jogos terminando 3+ gols nos últimos 5\n"
                "- Defesas sofrendo média > 1.2 gols\n"
                "- Odds >= 1.75"
            )
        else:
            stats_block = (
                "\nNOTA: Sem dados estatísticos detalhados disponíveis. "
                "Use seu conhecimento sobre os times e o contexto da liga para avaliar.\n"
            )
            criteria = (
                "Critérios para confidence alto (>75, pois sem estatísticas detalhadas):\n"
                "- Times reconhecidamente ofensivos na liga\n"
                "- Liga com histórico de jogos abertos e com gols\n"
                "- Odds >= 1.75 (mercado indicando jogo relativamente equilibrado em gols)"
            )

        return f"""Analise este jogo de futebol e avalie a probabilidade de ter 3 ou mais gols (Over 2.5):

JOGO: {home_team} (casa) x {away_team} (fora)
LIGA: {league_name}
ODDS BETFAIR para Over 2.5: {over25_odds}
{stats_block}
Responda APENAS com JSON no formato exato:
{{
  "confidence": <inteiro 0-100 representando % de chance de Over 2.5>,
  "expected_goals": <número decimal com gols totais esperados>,
  "risk_level": "<LOW|MEDIUM|HIGH>",
  "reasoning": "<explicação em 1-2 frases em português>"
}}

{criteria}
"""
