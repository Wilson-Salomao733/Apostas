import os
import hmac
import hashlib
import time
import urllib.parse
import requests

BASE_URL = "https://api.binance.com"
MIN_USDT_ORDER = 11.0
MIN_BTC_QTY = 0.00001


def _creds() -> tuple[str, str]:
    return os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_SECRET_KEY", "")


def _creds_ok() -> bool:
    api_key, secret = _creds()
    return bool(api_key and secret)


def _signed_post(endpoint: str, params: dict) -> dict:
    api_key, secret = _creds()
    params["timestamp"] = int(time.time() * 1000)
    query = urllib.parse.urlencode(params)
    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    body = query + "&signature=" + sig
    url = f"{BASE_URL}{endpoint}"
    r = requests.post(
        url,
        data=body,
        headers={
            "X-MBX-APIKEY": api_key,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def _get_free_balance() -> dict:
    api_key, secret = _creds()
    params = {"timestamp": int(time.time() * 1000)}
    query = urllib.parse.urlencode(params)
    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"{BASE_URL}/api/v3/account?{query}&signature={sig}"
    r = requests.get(url, headers={"X-MBX-APIKEY": api_key}, timeout=15)
    r.raise_for_status()
    return {b["asset"]: float(b["free"]) for b in r.json().get("balances", [])}


def buy_btc_with_usdt() -> str:
    if not _creds_ok():
        return "⚠️ Chaves da Binance não configuradas."
    try:
        balance = _get_free_balance()
        usdt = balance.get("USDT", 0.0)
        if usdt < MIN_USDT_ORDER:
            return (
                f"⚠️ Saldo USDT insuficiente.\n"
                f"Disponível: <b>${usdt:.2f} USDT</b>\n"
                f"Mínimo: <b>${MIN_USDT_ORDER:.0f}</b>"
            )
        spend = round(usdt * 0.999, 2)
        result = _signed_post("/api/v3/order", {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": spend,
        })
        btc_qty = float(result.get("executedQty", 0))
        spent = float(result.get("cummulativeQuoteQty", spend))
        avg_price = spent / btc_qty if btc_qty > 0 else 0
        return (
            f"✅ <b>COMPRA EXECUTADA!</b>\n\n"
            f"₿ BTC: <b>{btc_qty:.8f}</b>\n"
            f"💵 Gasto: <b>${spent:.2f} USDT</b>\n"
            f"📈 Preço médio: <b>${avg_price:,.2f}</b>"
        )
    except Exception as e:
        return f"❌ Erro ao comprar BTC: {e}"


def sell_btc_to_usdt() -> str:
    if not _creds_ok():
        return "⚠️ Chaves da Binance não configuradas."
    try:
        balance = _get_free_balance()
        btc = balance.get("BTC", 0.0)
        if btc < MIN_BTC_QTY:
            return f"⚠️ Saldo BTC insuficiente: <b>{btc:.8f} BTC</b>"
        qty_to_sell = round(btc * 0.999, 5)
        result = _signed_post("/api/v3/order", {
            "symbol": "BTCUSDT",
            "side": "SELL",
            "type": "MARKET",
            "quantity": qty_to_sell,
        })
        btc_sold = float(result.get("executedQty", qty_to_sell))
        usdt_recv = float(result.get("cummulativeQuoteQty", 0))
        avg_price = usdt_recv / btc_sold if btc_sold > 0 else 0
        return (
            f"✅ <b>VENDA EXECUTADA!</b>\n\n"
            f"₿ BTC: <b>{btc_sold:.8f}</b>\n"
            f"💵 USDT: <b>${usdt_recv:.2f}</b>\n"
            f"📉 Preço médio: <b>${avg_price:,.2f}</b>"
        )
    except Exception as e:
        return f"❌ Erro ao vender BTC: {e}"
