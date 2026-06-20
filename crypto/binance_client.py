import os
import hmac
import hashlib
import time
import json
import urllib.parse
import requests
from typing import Dict

BASE_URL = "https://api.binance.com"
MONITORED_COINS = ["BTC", "ETH", "USDT", "USDC", "SOL"]
COIN_SYMBOLS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "USDC": "USDCUSDT",
}


def get_brl_rate() -> float:
    try:
        r = requests.get(
            "https://economia.awesomeapi.com.br/json/last/USD-BRL", timeout=10
        )
        return float(r.json()["USDBRL"]["bid"])
    except Exception:
        return 5.70


def get_prices() -> Dict[str, float]:
    prices: Dict[str, float] = {"USDT": 1.0}
    try:
        r = requests.get(f"{BASE_URL}/api/v3/ticker/price", timeout=10)
        r.raise_for_status()
        all_prices = {item["symbol"]: float(item["price"]) for item in r.json()}
        for coin, symbol in COIN_SYMBOLS.items():
            prices[coin] = all_prices.get(symbol, 0.0)
    except Exception as e:
        print(f"[binance] Erro ao buscar preços: {e}")
    return prices


def get_24h_changes() -> Dict[str, float]:
    changes: Dict[str, float] = {"USDT": 0.0, "USDC": 0.0}
    symbols_list = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "USDCUSDT"]
    reverse_map = {v: k for k, v in COIN_SYMBOLS.items()}
    try:
        r = requests.get(
            f"{BASE_URL}/api/v3/ticker/24hr",
            params={"symbols": json.dumps(symbols_list)},
            timeout=10,
        )
        r.raise_for_status()
        for item in r.json():
            coin = reverse_map.get(item["symbol"])
            if coin:
                changes[coin] = float(item["priceChangePercent"])
    except Exception as e:
        print(f"[binance] Erro ao buscar variações 24h: {e}")
    return changes


def get_balance() -> Dict[str, float]:
    api_key = os.getenv("BINANCE_API_KEY", "")
    secret = os.getenv("BINANCE_SECRET_KEY", "")
    if not api_key or not secret:
        return {}
    try:
        params = {"timestamp": int(time.time() * 1000)}
        query = urllib.parse.urlencode(params)
        sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        url = f"{BASE_URL}/api/v3/account?{query}&signature={sig}"
        headers = {"X-MBX-APIKEY": api_key}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        balances: Dict[str, float] = {}
        for asset in r.json().get("balances", []):
            coin = asset["asset"]
            total = float(asset["free"]) + float(asset["locked"])
            if total > 0 and coin in MONITORED_COINS:
                balances[coin] = total
        return balances
    except Exception as e:
        print(f"[binance] Erro ao buscar saldo: {e}")
        return {}
