"""Coloca múltiplas (2 condições no mesmo jogo) na Betfair Exchange."""

from __future__ import annotations

import uuid
from typing import Any

from risk_manager import record_bet


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


def _parlay_leg_stakes(total_stake: float, odds1: float, odds2: float) -> tuple[float, float]:
    """
    Divide o stake total entre as 2 pernas (máx. perda = total_stake se ambas falharem).
    Ajuste leve para aproximar lucro de odd combinada o1*o2.
    """
    combined = odds1 * odds2
    if combined <= 1:
        half = round(total_stake / 2, 2)
        return max(half, 2.0), max(half, 2.0)
    # Perna 1 proporcional à "força" da odd 2
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

    if len(legs) == 2:
        s1, s2 = _parlay_leg_stakes(stake, float(legs[0]["odds"]), float(legs[1]["odds"]))
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
            if not result or result.get("status") != "SUCCESS":
                err = result.get("errorCode", "?") if result else "sem resposta"
                return False, f"❌ Falha: <code>{err}</code>"
            bet_id = _extract_bet_id(result, link)
            record_bet(opp, bet_id=bet_id)
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
            if not r or r.get("status") != "SUCCESS":
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

        record_bet(opp, bet_id=",".join(bet_ids))
        combined = float(opp.get("combined_odds") or opp.get("odds", 0))
        profit = round(float(opp["stake"]) * (combined - 1) * 0.95, 2)
        legs_txt = "\n".join(
            f"  {i+1}. {leg.get('label', '')} — R$ {leg_stakes[i]:.2f}"
            for i, leg in enumerate(legs)
        )
        return True, (
            f"✅ <b>Múltipla OK!</b> (2 condições — só ganha se <b>ambas</b> baterem)\n\n"
            f"⚽ {opp['home']} x {opp['away']}\n"
            f"{legs_txt}\n"
            f"📈 Odd combinada: <b>{combined:.2f}</b>\n"
            f"💵 Total apostado: R$ {exposure:.2f} | Lucro se ambas: ~R$ {profit:.2f}\n"
            f"🆔 <code>{','.join(bet_ids)}</code>"
        )
    except Exception as e:
        return False, f"❌ Erro: {e}"
