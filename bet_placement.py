"""Coloca apostas simples ou múltiplas (mesmo jogo) na Betfair Exchange."""

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


def build_instructions(opp: dict) -> tuple[list[dict], float]:
    """Retorna instruções e exposição total em R$."""
    stake = float(opp["stake"])
    legs = opp.get("legs") or []
    if not legs:
        return [_leg_instruction(opp, stake)], stake

    leg_stake = round(stake / len(legs), 2)
    if leg_stake < 2.0:
        leg_stake = 2.0
    instructions = [_leg_instruction(leg, leg_stake) for leg in legs]
    return instructions, leg_stake * len(legs)


def place_opportunity(betfair, opp: dict, ref_prefix: str = "BOT") -> tuple[bool, str]:
    """Aposta real na Betfair. Retorna (sucesso, mensagem HTML)."""
    legs = opp.get("legs") or []
    instructions, exposure = build_instructions(opp)
    ref = f"{ref_prefix}_{uuid.uuid4().hex[:10].upper()}"

    try:
        if len(instructions) == 1:
            result = betfair.place_orders(
                market_id=opp["market_id"],
                instructions=instructions,
                customer_ref=ref,
            )
        else:
            # Exchange: uma placeOrders por mercado
            bet_ids = []
            for leg, instr in zip(legs, instructions):
                r = betfair.place_orders(
                    market_id=leg["market_id"],
                    instructions=[instr],
                    customer_ref=f"{ref}_{leg['key']}",
                )
                if not r or r.get("status") != "SUCCESS":
                    err = r.get("errorCode", "?") if r else "sem resposta"
                    return False, f"❌ Falha na perna <b>{leg.get('label', leg['key'])}</b>: <code>{err}</code>"
                reports = r.get("instructionReports", [])
                bet_ids.append(reports[0].get("betId", ref) if reports else ref)
            record_bet(opp, bet_id=",".join(str(b) for b in bet_ids))
            combined = float(opp.get("combined_odds") or opp.get("odds", 0))
            profit = round(float(opp["stake"]) * (combined - 1) * 0.95, 2)
            legs_txt = "\n".join(
                f"  • {leg.get('label', '')} @ {leg['odds']:.2f}"
                for leg in legs
            )
            return True, (
                f"✅ <b>Múltipla OK!</b> (2 pernas Exchange)\n\n"
                f"⚽ {opp['home']} x {opp['away']}\n"
                f"{legs_txt}\n"
                f"📈 Odd combinada: <b>{combined:.2f}</b>\n"
                f"💵 Exposição: R$ {exposure:.2f} | Lucro se ambas: ~R$ {profit:.2f}\n"
                f"🆔 <code>{','.join(str(b) for b in bet_ids)}</code>"
            )

        if not result or result.get("status") != "SUCCESS":
            err = result.get("errorCode", "?") if result else "sem resposta"
            return False, f"❌ Falha: <code>{err}</code>"
        reports = result.get("instructionReports", [])
        bet_id = reports[0].get("betId", ref) if reports else ref
        record_bet(opp, bet_id=str(bet_id))
        return True, (
            f"✅ <b>Aposta OK!</b>\n\n"
            f"⚽ {opp['home']} x {opp['away']}\n"
            f"📊 {opp['bet_type']} @ {opp['odds']:.2f}\n"
            f"💵 R$ {opp['stake']:.2f}\n"
            f"🆔 <code>{bet_id}</code>"
        )
    except Exception as e:
        return False, f"❌ Erro: {e}"
