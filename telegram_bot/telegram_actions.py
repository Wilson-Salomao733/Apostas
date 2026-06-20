"""Telegram + Crypto + Apostas — lógica compartilhada (GitHub Actions)."""

import json
import os
import sys
import uuid
from configparser import ConfigParser
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "crypto"))

import binance_client as bc
import binance_trader as trader
from api_football import APIFootball
from betfair_api import BetfairAPI
from opportunity_scanner import Opportunity, OpportunityScanner

OFFSET_FILE = ROOT / "data" / "telegram_offset.txt"

MAIN_INLINE = {
    "inline_keyboard": [
        [
            {"text": "📊 Preços", "callback_data": "crypto_prices"},
            {"text": "🔍 Varredura", "callback_data": "apostas_scan"},
        ],
        [
            {"text": "🟢 Comprar BTC", "callback_data": "crypto_buy"},
            {"text": "🔴 Vender BTC", "callback_data": "crypto_sell"},
        ],
        [{"text": "💰 Saldo Betfair", "callback_data": "apostas_balance"}],
    ]
}

CRYPTO_INLINE = {
    "inline_keyboard": [[
        {"text": "🟢 Comprar BTC", "callback_data": "crypto_buy"},
        {"text": "🔴 Vender BTC", "callback_data": "crypto_sell"},
    ]]
}


def _cfg() -> ConfigParser:
    c = ConfigParser()
    c.read(ROOT / "bot_config.ini")
    return c


def telegram_creds() -> tuple[str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        cfg = _cfg()
        token = token or cfg.get("telegram", "bot_token", fallback="")
        chat = chat or str(cfg.get("telegram", "chat_id", fallback=""))
    return token, chat


def allowed_chat() -> str:
    return str(telegram_creds()[1])


def api_post(token: str, method: str, payload: dict) -> dict:
    r = requests.post(
        f"https://api.telegram.org/bot{token}/{method}",
        json=payload,
        timeout=60,
        proxies={"http": None, "https": None},
    )
    r.raise_for_status()
    return r.json()


def send(chat_id: str, text: str, reply_markup: dict | None = None) -> None:
    token, _ = telegram_creds()
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    api_post(token, "sendMessage", payload)


def answer_callback(callback_id: str, text: str = "") -> None:
    token, _ = telegram_creds()
    api_post(token, "answerCallbackQuery", {
        "callback_query_id": callback_id,
        "text": text[:200],
    })


def load_offset() -> int:
    try:
        if OFFSET_FILE.exists():
            return int(OFFSET_FILE.read_text().strip())
    except Exception:
        pass
    return 0


def save_offset(offset: int) -> None:
    OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
    OFFSET_FILE.write_text(str(offset))


def format_prices(scheduled: bool = False) -> str:
    brl = bc.get_brl_rate()
    prices = bc.get_prices()
    changes = bc.get_24h_changes()
    balance = bc.get_balance()
    total_usd = sum(prices.get(c, 0) * q for c, q in balance.items())
    total_brl = total_usd * brl
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    header = "📊 <b>Preços Crypto</b>"
    if scheduled:
        header += " — atualização automática"
    lines = [header, f"🕐 {now}", f"💱 1 USD = R$ {brl:.2f}", "", "<b>📈 Cotação de mercado</b>"]
    for coin in ["BTC", "ETH", "SOL", "USDT", "USDC"]:
        p = prices.get(coin, 0)
        ch = changes.get(coin, 0)
        arrow = "🔴" if ch < 0 else "🟢"
        lines.append(f"{arrow} <b>{coin}</b>: ${p:,.2f} (R$ {p * brl:,.2f}) {ch:+.2f}%")
    lines.append("")
    lines.append("<b>💼 Seu saldo Binance</b>")
    if balance:
        for coin in ["BTC", "ETH", "SOL", "USDT", "USDC"]:
            q = balance.get(coin, 0)
            if q > 0:
                val = q * prices.get(coin, 0)
                lines.append(f"  {coin}: {q:.6g} (~${val:,.2f})")
        lines.append(f"Total: ~${total_usd:,.2f} / R$ {total_brl:,.2f}")
    else:
        lines.append("  (vazio ou indisponível — GitHub bloqueia API Binance)")
    lines.append("\n👇 <i>Botões respondem em até ~5 min</i>")
    return "\n".join(lines)


def _betfair_geo_hint(err: str) -> str | None:
    if any(x in err.upper() for x in ("RESTRICTED_LOCATION", "RE-LOGIN", "RELOGIN")):
        if os.getenv("GITHUB_ACTIONS") == "true":
            return (
                "⚠️ <b>Betfair bloqueada no GitHub Actions</b>\n"
                "Servidores nos EUA — use o hub no seu PC para apostas/saldo."
            )
    return None


def _stake() -> float:
    return float(_cfg().get("manual", "stake", fallback="20"))


def _apostas_keys() -> tuple[str, str]:
    cfg = _cfg()
    fk = os.getenv("API_FOOTBALL_KEY") or cfg.get("api_keys", "api_football_key", fallback="")
    gk = os.getenv("GROQ_API_KEY") or cfg.get("api_keys", "groq_api_key", fallback="")
    return fk, gk


def _betfair() -> BetfairAPI:
    os.chdir(ROOT)
    bf = BetfairAPI(str(ROOT / "config.ini"))
    bf.login()
    return bf


def run_scan(chat_id: str) -> None:
    send(chat_id, "🔍 <b>Varredura iniciada</b>\nAnalisando jogos (~1–3 min)...")
    os.chdir(ROOT)
    fk, gk = _apostas_keys()
    try:
        scanner = OpportunityScanner(_betfair(), APIFootball(fk), gk, stake=_stake())
        opps = scanner.scan()
        stats = scanner.last_stats
    except Exception as e:
        hint = _betfair_geo_hint(str(e))
        send(chat_id, hint or f"❌ Erro na varredura: {e}", MAIN_INLINE)
        return

    if not opps:
        mkts = stats.get("markets_total", 0)
        err = stats.get("betfair_error", "")
        if err:
            hint = _betfair_geo_hint(err)
            send(chat_id, hint or f"❌ Betfair: {err}", MAIN_INLINE)
            return
        msg = (
            "😴 <b>Nenhuma oportunidade aprovada.</b>\n\n"
            f"Mercados analisados: ~{mkts}\n"
        )
        if mkts == 0:
            msg += (
                "\nEm época de Copa do Mundo, ligas nacionais param — "
                "só jogos da Copa aparecem na Betfair.\n"
                "A varredura já inclui Copa do Mundo."
            )
        else:
            msg += "Nenhum jogo passou nos filtros (odd + IA)."
        send(chat_id, msg, MAIN_INLINE)
        return

    note = " (⚠️ candidatos — IA cautelosa)" if stats.get("fallback") else ""
    send(chat_id, f"✅ <b>{len(opps)} oportunidade(s)</b>{note}", MAIN_INLINE)
    for opp in opps:
        risk = {"baixo": "🟢", "médio": "🟡"}.get(opp.risk, "⚪")
        text = (
            f"{risk} <b>{opp.bet_type}</b>\n\n"
            f"⚽ <b>{opp.home}</b> x <b>{opp.away}</b>\n"
            f"🏆 {opp.league}\n"
            f"📊 {opp.selection_label} @ <b>{opp.odds:.2f}</b>\n"
            f"💵 Stake R$ {opp.stake:.0f} → Lucro R$ {opp.potential_profit:.2f}\n"
            f"🤖 IA: {opp.confidence}%\n"
            f"💬 <i>{opp.reasoning}</i>"
        )
        kb = {"inline_keyboard": [[
            {"text": f"✅ Apostar R$ {opp.stake:.0f}", "callback_data": f"bet:{opp.opp_id}"},
            {"text": "❌ Ignorar", "callback_data": "noop"},
        ]]}
        send(chat_id, text, kb)


def place_bet(chat_id: str, opp_id: str) -> None:
    os.chdir(ROOT)
    opp = OpportunityScanner.load_pending(opp_id)
    if not opp:
        send(chat_id, "⚠️ Oportunidade expirada. Faça nova varredura.", MAIN_INLINE)
        return
    send(chat_id, f"⏳ Apostando em <b>{opp['home']} x {opp['away']}</b>...")
    try:
        ref = f"GH_{uuid.uuid4().hex[:10].upper()}"
        result = _betfair().place_orders(
            market_id=opp["market_id"],
            instructions=[{
                "instructionType": "LIMIT",
                "selectionId": int(opp["selection_id"]),
                "side": "BACK",
                "orderType": "LIMIT",
                "limitOrder": {
                    "size": round(float(opp["stake"]), 2),
                    "price": round(float(opp["odds"]), 2),
                    "persistenceType": "LAPSE",
                },
            }],
            customer_ref=ref,
        )
        if not result or result.get("status") != "SUCCESS":
            err = result.get("errorCode", "?") if result else "sem resposta"
            send(chat_id, f"❌ Falha: <code>{err}</code>", MAIN_INLINE)
            return
        reports = result.get("instructionReports", [])
        bet_id = reports[0].get("betId", ref) if reports else ref
        send(
            chat_id,
            f"✅ <b>Aposta OK!</b>\n\n"
            f"⚽ {opp['home']} x {opp['away']}\n"
            f"📊 {opp['bet_type']} @ {opp['odds']:.2f}\n"
            f"💵 R$ {opp['stake']:.2f}\n"
            f"🆔 <code>{bet_id}</code>",
            MAIN_INLINE,
        )
    except Exception as e:
        send(chat_id, f"❌ Erro: {e}", MAIN_INLINE)


def betfair_balance(chat_id: str) -> None:
    try:
        funds = _betfair().get_account_funds()
        av = float(funds.get("availableToBetBalance", 0))
        ex = float(funds.get("exposure", 0))
        send(
            chat_id,
            f"💰 <b>Saldo Betfair</b>\n\nDisponível: <b>R$ {av:.2f}</b>\nExposição: R$ {ex:.2f}",
            MAIN_INLINE,
        )
    except Exception as e:
        hint = _betfair_geo_hint(str(e))
        send(chat_id, hint or f"❌ {e}", MAIN_INLINE)


def confirm_crypto(chat_id: str, action: str) -> None:
    if action == "crypto_buy":
        kb = {"inline_keyboard": [[
            {"text": "✅ Confirmar COMPRAR", "callback_data": "confirm_buy"},
            {"text": "❌ Cancelar", "callback_data": "noop"},
        ]]}
        send(chat_id, "⚠️ <b>Comprar BTC</b> com todo USDT disponível?", kb)
    else:
        kb = {"inline_keyboard": [[
            {"text": "✅ Confirmar VENDER", "callback_data": "confirm_sell"},
            {"text": "❌ Cancelar", "callback_data": "noop"},
        ]]}
        send(chat_id, "⚠️ <b>Vender</b> todo BTC para USDT?", kb)


TEXT_ACTIONS = {
    "📊 ver preços crypto": "crypto_prices",
    "🔍 varredura apostas": "apostas_scan",
    "🟢 comprar btc": "crypto_buy",
    "🔴 vender btc": "crypto_sell",
    "💰 saldo betfair": "apostas_balance",
    "/start": "menu",
    "/menu": "menu",
    "menu": "menu",
    "📋 menu": "menu",
}


def dispatch(chat_id: str, action: str) -> None:
    if action == "menu":
        send(
            chat_id,
            "🏠 <b>Menu Investimentos</b>\n\n"
            "📊 Preços Crypto\n"
            "🔍 Varredura Apostas\n"
            "🟢 Comprar / 🔴 Vender BTC\n"
            "💰 Saldo Betfair\n\n"
            "<i>Botões respondem em até ~5 min</i>",
            MAIN_INLINE,
        )
    elif action == "crypto_prices":
        send(chat_id, format_prices(), CRYPTO_INLINE)
    elif action == "crypto_buy":
        confirm_crypto(chat_id, "crypto_buy")
    elif action == "crypto_sell":
        confirm_crypto(chat_id, "crypto_sell")
    elif action == "apostas_scan":
        run_scan(chat_id)
    elif action == "apostas_balance":
        betfair_balance(chat_id)
    elif action == "confirm_buy":
        send(chat_id, "⏳ Comprando BTC...")
        send(chat_id, trader.buy_btc_with_usdt(), MAIN_INLINE)
    elif action == "confirm_sell":
        send(chat_id, "⏳ Vendendo BTC...")
        send(chat_id, trader.sell_btc_to_usdt(), MAIN_INLINE)


def handle_callback(chat_id: str, callback_id: str, data: str) -> None:
    answer_callback(callback_id)
    if data == "noop":
        return
    if data.startswith("bet:"):
        place_bet(chat_id, data.split(":", 1)[1])
        return
    dispatch(chat_id, data)


def handle_message(chat_id: str, text: str) -> None:
    action = TEXT_ACTIONS.get(text.strip().lower())
    if action:
        dispatch(chat_id, action)
    else:
        send(chat_id, "Use os botões abaixo 👇", MAIN_INLINE)


def poll_once() -> int:
    """Processa updates pendentes. Retorna quantidade processada."""
    token, _ = telegram_creds()
    offset = load_offset()
    r = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={"timeout": 0, "offset": offset, "allowed_updates": json.dumps(["message", "callback_query"])},
        timeout=15,
        proxies={"http": None, "https": None},
    )
    r.raise_for_status()
    updates = r.json().get("result", [])
    allowed = allowed_chat()
    count = 0

    for upd in updates:
        save_offset(upd["update_id"] + 1)
        count += 1

        if "callback_query" in upd:
            cb = upd["callback_query"]
            chat = str(cb.get("message", {}).get("chat", {}).get("id", ""))
            if chat != allowed:
                continue
            handle_callback(chat, cb["id"], cb.get("data", ""))
            continue

        msg = upd.get("message", {})
        chat = str(msg.get("chat", {}).get("id", ""))
        if chat != allowed:
            continue
        text = msg.get("text", "")
        if text:
            handle_message(chat, text)

    return count
