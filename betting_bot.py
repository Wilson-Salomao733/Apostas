#!/usr/bin/env python3
"""Bot de apostas standalone — Telegram + worker automático."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from auto_worker import AutoWorker
from betfair_api import BetfairAPI
from bet_placement import place_opportunity
from config_loader import (
    VALID_MODES,
    VALID_STRATEGIES,
    combo_label,
    get_active_strategy,
    get_telegram_creds,
    load_mode,
    resolve_combo_key,
    save_mode,
)
from opportunity_scanner import Opportunity, OpportunityScanner
from risk_manager import can_bet, status_summary

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)

_betfair: BetfairAPI | None = None
_worker: AutoWorker | None = None
_app: Application | None = None
_main_loop: asyncio.AbstractEventLoop | None = None


def _allowed_chat() -> int:
    _, chat = get_telegram_creds()
    return int(chat or "0")


def _get_betfair() -> BetfairAPI:
    global _betfair
    if _betfair is None:
        _betfair = BetfairAPI(str(ROOT / "config.ini"))
        _betfair.login()
    return _betfair


def _mode_label(mode: str) -> str:
    return {
        "off": "⏹ Parado",
        "manual": "👆 Manual",
        "semi": "🔔 Semi-auto",
        "auto": "🤖 Full auto",
    }.get(mode, mode)


def _strategy_label(key: str) -> str:
    return combo_label(resolve_combo_key(key))


def main_keyboard() -> InlineKeyboardMarkup:
    strategy = get_active_strategy()
    strat_btn = "all_combos" if strategy == "all_combos" else strategy
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Varredura", callback_data="scan"),
            InlineKeyboardButton("💰 Saldo", callback_data="balance"),
        ],
        [
            InlineKeyboardButton("📊 Status", callback_data="status"),
        ],
        [
            InlineKeyboardButton("👆 Manual", callback_data="mode:manual"),
            InlineKeyboardButton("🔔 Semi", callback_data="mode:semi"),
        ],
        [
            InlineKeyboardButton("🤖 Auto", callback_data="mode:auto"),
            InlineKeyboardButton("⏹ Parar", callback_data="mode:off"),
        ],
        [
            InlineKeyboardButton(
                f"📌 {_strategy_label(strat_btn)}",
                callback_data="noop",
            ),
        ],
        [
            InlineKeyboardButton("🎯 Todas", callback_data="strat:all_combos"),
            InlineKeyboardButton("U4.5+O8.5", callback_data="strat:combo_u45_o85"),
        ],
        [
            InlineKeyboardButton("U4.5+BTTS❌", callback_data="strat:combo_u45_btts_no"),
            InlineKeyboardButton("U3.5+O8.5", callback_data="strat:combo_u35_o85"),
        ],
        [
            InlineKeyboardButton("O1.5+O8.5", callback_data="strat:combo_o15_o85"),
            InlineKeyboardButton("Fav+U4.5", callback_data="strat:combo_fav_u45"),
        ],
    ])


MENU_TEXT = (
    "🤖 <b>Bot de Múltiplas</b> (Betfair Exchange)\n\n"
    "Só apostas <b>combinadas no mesmo jogo</b> — 2 pernas.\n\n"
    "🎯 <b>Todas</b> — varre as 5 múltiplas abaixo\n"
    "👆 Manual | 🔔 Semi | 🤖 Auto\n"
)


def _opp_keyboard(opp: Opportunity) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"✅ Apostar R$ {opp.stake:.0f}",
            callback_data=f"bet:{opp.opp_id}",
        ),
        InlineKeyboardButton("❌ Ignorar", callback_data="noop"),
    ]])


def _format_opp(opp: Opportunity) -> str:
    risk = {"baixo": "🟢", "médio": "🟡"}.get(opp.risk, "⚪")
    lines = [
        f"{risk} <b>{opp.bet_type}</b>",
        "",
        f"⚽ <b>{opp.home}</b> x <b>{opp.away}</b>",
        f"🏆 {opp.league}",
    ]
    if opp.legs:
        lines.append("<b>Pernas:</b>")
        for leg in opp.legs:
            lines.append(f"  • {leg.get('label', '')}")
        lines.append(f"📈 Odd combinada: <b>{opp.combined_odds or opp.odds:.2f}</b>")
    else:
        lines.append(f"📊 {opp.selection_label} @ <b>{opp.odds:.2f}</b>")
    lines.extend([
        f"💵 Stake R$ {opp.stake:.0f} → Lucro ~R$ {opp.potential_profit:.2f}",
        f"🤖 IA: {opp.confidence}%",
        f"💬 <i>{opp.reasoning}</i>",
    ])
    if opp.legs:
        lines.append("<i>Exchange: 2 apostas no mesmo jogo — ambas devem bater.</i>")
    return "\n".join(lines)


async def _send(chat_id: int, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    if _app and _app.bot:
        await _app.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=markup or main_keyboard(),
        )


def _sync_notify(text: str, _markup: dict | None) -> None:
    chat = _allowed_chat()
    if _main_loop and chat:
        asyncio.run_coroutine_threadsafe(
            _send(chat, text, main_keyboard()),
            _main_loop,
        )


def _sync_notify_opp(opp: Opportunity) -> None:
    chat = _allowed_chat()
    if _main_loop and chat:
        asyncio.run_coroutine_threadsafe(
            _send(chat, f"🔔 <b>Oportunidade</b>\n\n{_format_opp(opp)}", _opp_keyboard(opp)),
            _main_loop,
        )


def _guard(update: Update) -> bool:
    chat = update.effective_chat
    allowed = _allowed_chat()
    if not chat:
        return False
    if chat.id != allowed:
        log.warning("Mensagem ignorada — chat_id %s (esperado %s)", chat.id, allowed)
        return False
    return True


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _guard(update):
        return
    mode = load_mode()
    await update.message.reply_text(
        f"{MENU_TEXT}\n\nModo: <b>{_mode_label(mode)}</b>\nEstratégia: <b>{_strategy_label(get_active_strategy())}</b>",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _guard(update):
        return
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data == "noop":
        return

    if data == "scan":
        await query.edit_message_text("🔍 <b>Varredura iniciada...</b>", parse_mode="HTML")
        loop = asyncio.get_event_loop()
        opps, stats = await loop.run_in_executor(None, _worker.run_scan_once if _worker else _manual_scan)
        await _send_scan_results(query.message.chat_id, opps, stats)
        return

    if data == "balance":
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, _fetch_balance)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_keyboard())
        return

    if data == "status":
        text = (
            f"📊 <b>Status</b>\n\n"
            f"Modo: {_mode_label(load_mode())}\n"
            f"Estratégia: {combo_label(get_active_strategy())}\n\n"
            f"{status_summary()}"
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_keyboard())
        return

    if data.startswith("mode:"):
        mode = data.split(":", 1)[1]
        if mode in VALID_MODES:
            save_mode(mode)
            await query.edit_message_text(
                f"Modo alterado: <b>{_mode_label(mode)}</b>",
                parse_mode="HTML",
                reply_markup=main_keyboard(),
            )
        return

    if data.startswith("strat:"):
        key = resolve_combo_key(data.split(":", 1)[1])
        if key in VALID_STRATEGIES:
            _set_strategy(key)
            await query.edit_message_text(
                f"Estratégia: <b>{combo_label(key)}</b>",
                parse_mode="HTML",
                reply_markup=main_keyboard(),
            )
        return

    if data.startswith("bet:"):
        opp_id = data.split(":", 1)[1]
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, _place_bet, opp_id)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_keyboard())


def _set_strategy(key: str) -> None:
    from configparser import ConfigParser
    path = ROOT / "bot_config.ini"
    cfg = ConfigParser()
    cfg.read(path)
    if not cfg.has_section("bot"):
        cfg.add_section("bot")
    cfg.set("bot", "active_strategy", key)
    with open(path, "w") as f:
        cfg.write(f)


def _manual_scan():
    from auto_worker import AutoWorker
    w = AutoWorker(_get_betfair(), _sync_notify, _sync_notify_opp)
    return w.run_scan_once()


async def _send_scan_results(chat_id: int, opps: list, stats: dict) -> None:
    if not opps:
        mkts = stats.get("markets_total", 0)
        err = stats.get("betfair_error", "")
        msg = "😴 <b>Nenhuma oportunidade aprovada.</b>\n\n"
        if err:
            msg += f"Erro Betfair: {err}"
        else:
            msg += f"Mercados analisados: ~{mkts}"
        await _send(chat_id, msg)
        return
    note = " (⚠️ candidatos — IA cautelosa)" if stats.get("fallback") else ""
    await _send(chat_id, f"✅ <b>{len(opps)} oportunidade(s)</b>{note}")
    for opp in opps:
        await _send(chat_id, _format_opp(opp), _opp_keyboard(opp))


def _fetch_balance() -> str:
    try:
        funds = _get_betfair().get_account_funds()
        av = float(funds.get("availableToBetBalance", 0))
        ex = float(funds.get("exposure", 0))
        return f"💰 <b>Saldo Betfair</b>\n\nDisponível: <b>R$ {av:.2f}</b>\nExposição: R$ {ex:.2f}"
    except Exception as e:
        return f"❌ {e}"


def _place_bet(opp_id: str) -> str:
    opp_data = OpportunityScanner.load_pending(opp_id)
    if not opp_data:
        return "⚠️ Oportunidade expirada. Faça nova varredura."
    ok, reason = can_bet(opp_data)
    if not ok:
        return f"⛔ Aposta bloqueada: {reason}"
    ok, msg = place_opportunity(_get_betfair(), opp_data, ref_prefix="TG")
    return msg


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _guard(update):
        return
    await cmd_start(update, context)


async def _post_init(application: Application) -> None:
    global _main_loop
    _main_loop = asyncio.get_running_loop()
    chat = _allowed_chat()
    if not chat:
        return
    mode = load_mode()
    try:
        await application.bot.send_message(
            chat_id=chat,
            text=(
                f"🤖 <b>Bot de Apostas online</b>\n\n"
                f"Bot: @betwilson_bot\n"
                f"Modo: <b>{_mode_label(mode)}</b>\n"
                f"Estratégia: <b>{_strategy_label(get_active_strategy())}</b>\n\n"
                f"{MENU_TEXT}"
            ),
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        log.info("Mensagem de boas-vindas enviada ao chat %s", chat)
    except Exception as e:
        log.error("Falha ao enviar boas-vindas: %s", e)


def main() -> None:
    global _worker, _app
    token, _ = get_telegram_creds()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN não configurado")

    bf = _get_betfair()
    _worker = AutoWorker(bf, _sync_notify, _sync_notify_opp)
    _worker.start()

    _app = (
        Application.builder()
        .token(token)
        .post_init(_post_init)
        .build()
    )
    _app.add_handler(CommandHandler("start", cmd_start))
    _app.add_handler(CommandHandler("menu", cmd_start))
    _app.add_handler(CallbackQueryHandler(on_callback))
    _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    log.info("Bot de apostas iniciado | modo=%s | chat=%s", load_mode(), _allowed_chat())
    _app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
