"""Coloca múltiplas (2 condições no mesmo jogo) na Betfair Exchange."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from bet_ledger import record_order
from risk_manager import record_bet

logger = logging.getLogger(__name__)


def _leg_instruction(leg: dict, stake: float) -> dict:
    return {
        "instructionType": "LIMIT",
        "selectionId": int(leg["selection_id"]),
        "side": "BACK",
        "orderType": "LIMIT",
        "limitOrder": {
            "size": round(stake, 2),
            "price": round(float(leg["odds"]), 2),
            "persistenceType": "LAPSE",
        },
    }


def _parlay_leg_stakes(
    total_stake: float,
    odds1: float,
    odds2: float,
    leg2_ratio: float | None = None,
) -> tuple[float, float]:
    """
    Divide o stake total entre as 2 pernas (máx. perda = total_stake se ambas falharem).
    Com leg2_ratio, fixa a fração na perna 2 (ex.: escanteios).
    """
    if leg2_ratio is not None and 0.0 < leg2_ratio < 1.0:
        s2 = round(total_stake * leg2_ratio, 2)
        s1 = round(total_stake - s2, 2)
    else:
        combined = odds1 * odds2
        if combined <= 1:
            half = round(total_stake / 2, 2)
            return max(half, 2.0), max(half, 2.0)
        s1 = round(total_stake * odds2 / combined, 2)
        s2 = round(total_stake - s1, 2)
    if s1 < 2.0:
        s1, s2 = 2.0, max(round(total_stake - 2.0, 2), 2.0)
    if s2 < 2.0:
        s2, s1 = 2.0, max(round(total_stake - 2.0, 2), 2.0)
    return s1, s2


def build_instructions(opp: dict) -> tuple[list[dict], float, list[float]]:
    """Retorna instruções, exposição total e stake por perna."""
    stake = float(opp["stake"])
    legs = opp.get("legs") or []
    if not legs:
        return [_leg_instruction(opp, stake)], stake, [stake]

    explicit_stakes = opp.get("leg_stakes")
    if not explicit_stakes:
        values = [leg.get("stake") for leg in legs]
        if all(value is not None for value in values):
            explicit_stakes = values
    if explicit_stakes:
        stakes = [round(float(value), 2) for value in explicit_stakes]
        if len(stakes) != len(legs) or any(value < 2.0 for value in stakes):
            raise ValueError("Stakes explícitas inválidas para as pernas")
        instructions = [_leg_instruction(leg, s) for leg, s in zip(legs, stakes)]
        return instructions, round(sum(stakes), 2), stakes

    if len(legs) == 2:
        leg2_ratio = opp.get("leg2_stake_ratio")
        if leg2_ratio is not None:
            leg2_ratio = float(leg2_ratio)
        s1, s2 = _parlay_leg_stakes(
            stake,
            float(legs[0]["odds"]),
            float(legs[1]["odds"]),
            leg2_ratio=leg2_ratio,
        )
        stakes = [s1, s2]
    else:
        leg_stake = round(stake / len(legs), 2)
        if leg_stake < 2.0:
            leg_stake = 2.0
        stakes = [leg_stake] * len(legs)

    instructions = [_leg_instruction(leg, s) for leg, s in zip(legs, stakes)]
    return instructions, sum(stakes), stakes


def _extract_bet_id(result: dict | None, fallback: str) -> str:
    if not result:
        return fallback
    reports = result.get("instructionReports", [])
    if reports:
        return str(reports[0].get("betId", fallback))
    return fallback


def _instruction_succeeded(result: dict | None) -> bool:
    if not result or result.get("status") != "SUCCESS":
        return False
    reports = result.get("instructionReports", [])
    return bool(reports) and reports[0].get("status") == "SUCCESS"


def projected_profit(odds: float, stake: float, commission_rate: float = 0.065) -> float:
    """Projeção conservadora; a liquidação usa sempre o profit retornado pela API."""
    return round(max(0.0, stake * (odds - 1)) * (1 - commission_rate), 2)


def place_opportunity(betfair, opp: dict, ref_prefix: str = "BOT") -> tuple[bool, str]:
    """Aposta múltipla na Betfair. Retorna (sucesso, mensagem HTML)."""
    legs = opp.get("legs") or []
    instructions, exposure, leg_stakes = build_instructions(opp)
    link = f"{ref_prefix}_{uuid.uuid4().hex[:8].upper()}"

    try:
        if len(instructions) == 1:
            result = betfair.place_orders(
                market_id=opp["market_id"],
                instructions=instructions,
                customer_ref=link,
            )
            if not _instruction_succeeded(result):
                err = result.get("errorCode", "?") if result else "sem resposta"
                return False, f"❌ Falha: <code>{err}</code>"
            bet_id = _extract_bet_id(result, link)
            try:
                record_bet(opp, bet_id=bet_id, leg_stakes=leg_stakes)
                record_order(opp, [bet_id], leg_stakes)
            except Exception:
                logger.exception("Aposta aceita, mas falhou ao persistir bet_id=%s", bet_id)
            return True, (
                f"✅ <b>Aposta OK!</b>\n\n"
                f"⚽ {opp['home']} x {opp['away']}\n"
                f"📊 {opp['bet_type']} @ {opp['odds']:.2f}\n"
                f"💵 R$ {opp['stake']:.2f}\n"
                f"🆔 <code>{bet_id}</code>"
            )

        bet_ids: list[str] = []
        for i, (leg, instr, leg_stake) in enumerate(zip(legs, instructions, leg_stakes)):
            r = betfair.place_orders(
                market_id=leg["market_id"],
                instructions=[instr],
                customer_ref=f"{link}_L{i+1}",
            )
            if not _instruction_succeeded(r):
                err = r.get("errorCode", "?") if r else "sem resposta"
                # Desfaz pernas já colocadas (só cancela se ainda EXECUTABLE)
                for j, prev_id in enumerate(bet_ids):
                    try:
                        betfair.cancel_orders(
                            market_id=legs[j]["market_id"],
                            bet_ids=[prev_id],
                        )
                    except Exception:
                        pass
                return False, (
                    f"❌ Múltipla <b>cancelada</b> — falhou na condição "
                    f"<b>{leg.get('label', leg['key'])}</b>: <code>{err}</code>"
                )
            bet_ids.append(_extract_bet_id(r, f"{link}_L{i+1}"))

        try:
            record_bet(
                opp,
                bet_id=",".join(bet_ids),
                leg_stakes=leg_stakes,
            )
            record_order(opp, bet_ids, leg_stakes)
        except Exception:
            logger.exception("Carteira aceita, mas falhou ao persistir bet_ids=%s", bet_ids)
        commission = float(opp.get("commission_rate", 0.065))
        profit = round(sum(
            projected_profit(float(leg["odds"]), leg_stakes[index], commission)
            for index, leg in enumerate(legs)
        ), 2)
        legs_txt = "\n".join(
            f"  {i+1}. {leg.get('label', '')} — R$ {leg_stakes[i]:.2f}"
            for i, leg in enumerate(legs)
        )
        return True, (
            f"✅ <b>Carteira de 2 apostas OK!</b> (ordens independentes)\n\n"
            f"⚽ {opp['home']} x {opp['away']}\n"
            f"{legs_txt}\n"
            f"💵 Exposição total: R$ {exposure:.2f} | "
            f"Lucro estimado se ambas vencerem: ~R$ {profit:.2f}\n"
            f"🆔 <code>{','.join(bet_ids)}</code>"
        )
    except Exception as e:
        return False, f"❌ Erro: {e}"
