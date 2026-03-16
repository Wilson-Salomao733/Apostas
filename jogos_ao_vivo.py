#!/usr/bin/env python3
"""
Script para buscar jogos ao vivo na Betfair e exibir estatísticas (placar quando disponível).

Usa a API Betfair para:
1. Obter token de sessão
2. Listar mercados in-play (jogos ao vivo)
3. Tentar obter placar via In-Play Service (quando disponível)

Nota: A API Exchange da Betfair não fornece placar diretamente.
O In-Play Service (ips.betfair.com) pode fornecer placar para alguns eventos.
"""

import sys
import json
import requests
from configparser import ConfigParser

# Suprimir prints do login
import io
import contextlib

from betfair_login import BetfairLogin
from betfair_api import BetfairAPI


def _extract_elapsed_from_timeline(item):
    """Extrai elapsed_regular_time de um item de timeline (estrutura variável)."""
    for key in ("updateDetail", "update_detail", "updates"):
        updates = item.get(key)
        if not updates:
            continue
        lst = updates if isinstance(updates, list) else [updates]
        for u in reversed(lst):
            if isinstance(u, dict):
                v = u.get("elapsedRegularTime") or u.get("elapsed_regular_time")
                if v is not None:
                    return v
    return None


def get_event_timelines(event_ids, session_token=None, app_key=None):
    """
    Obtém tempo decorrido via Betfair In-Play Service eventTimelines.
    URL: https://ips.betfair.com/inplayservice/v1.1/eventTimelines

    Retorna dict {event_id: elapsed_minutes ou None}
    - elapsed = elapsedRegularTime (minuto numérico: 1, 45, 67, 90, etc.)
    - Pré-live: geralmente None ou vazio
    - 1º tempo: 1-45
    - 2º tempo: 46-90+
    """
    if not event_ids:
        return {}
    url = "https://ips.betfair.com/inplayservice/v1.1/eventTimelines"
    params = {
        "eventIds": ",".join(str(e) for e in event_ids),
        "alt": "json",
        "regionCode": "UK",
        "locale": "en_GB",
    }
    headers = {"Content-Type": "application/json"}
    if session_token and app_key:
        headers["X-Authentication"] = session_token
        headers["X-Application"] = app_key
    result = {}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("eventTypes", [{}])[0].get("eventType", {}).get("events", [])
            if not items:
                items = data.get("events", data.get("eventTypes", []))
        for item in items:
            if isinstance(item, dict):
                eid = item.get("eventId") or item.get("event", {}).get("id")
                elapsed = _extract_elapsed_from_timeline(item)
                if eid:
                    result[str(eid)] = elapsed
    except Exception:
        pass
    return result


def _formatar_tempo(status, elapsed):
    """
    Formata tempo para exibição mais completa e legível.
    status: do scores (ex: "67'", "FirstHalfEnd", "SecondHalf")
    elapsed: do eventTimelines (ex: 67, 45)
    """
    status = (status or "").strip()
    # Status já tem minuto explícito (ex: "67'", "45'")
    if status and (status.endswith("'") or status.replace("'", "").replace(" ", "").isdigit()):
        return status
    # Mapear status conhecidos para formato mais claro
    status_lower = status.lower()
    if "firsthalfend" in status_lower or "halftime" in status_lower or status == "HalfTime":
        return f"{elapsed or 45}' (HT)"
    if "secondhalf" in status_lower or "2nd" in status_lower:
        return f"{elapsed or 46}' (2º tempo)" if elapsed else "46'+ (2º tempo)"
    if "firsthalf" in status_lower or "1st" in status_lower:
        return f"{elapsed or '?'}' (1º tempo)"
    if "inplay" in status_lower or "live" in status_lower:
        return f"{elapsed}'" if elapsed is not None else "Ao vivo"
    if "min" in status_lower:
        return status
    # Fallback: usar elapsed se tiver
    if elapsed is not None:
        return f"{elapsed}'"
    return status if status else "-"


def get_inplay_scores(event_ids, session_token=None, app_key=None):
    """
    Obtém placar e status via Betfair In-Play Service.
    URL: https://ips.betfair.com/inplayservice/v1.1/scores

    Retorna dict {event_id: {home: X, away: Y, status: str, description: str}}

    status típicos:
    - "12'", "45'", "67'" = minuto explícito
    - "FirstHalf", "1st" = 1º tempo
    - "FirstHalfEnd", "HalfTime" = intervalo (45')
    - "SecondHalf", "2nd" = 2º tempo (46+)
    - Pré-live: vazio ou "Scheduled"
    """
    if not event_ids:
        return {}
    
    url = "https://ips.betfair.com/inplayservice/v1.1/scores"
    params = {
        "eventIds": ",".join(str(e) for e in event_ids),
        "alt": "json",
        "regionCode": "UK",
        "locale": "en_GB",
    }
    headers = {"Content-Type": "application/json"}
    if session_token and app_key:
        headers["X-Authentication"] = session_token
        headers["X-Application"] = app_key
    
    scores_by_event = {}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        # Estrutura pode variar; tratar como lista de scores
        items = data if isinstance(data, list) else data.get("eventTypes", [{}])[0].get("eventType", {}).get("events", []) if isinstance(data, dict) else []
        if isinstance(data, dict) and "scores" in data:
            items = data["scores"]
        elif isinstance(data, list):
            items = data
        
        for item in items:
            if isinstance(item, dict):
                eid = item.get("eventId") or item.get("event", {}).get("id")
                score_obj = item.get("score") or item
                home = score_obj.get("home", {})
                away = score_obj.get("away", {})
                if isinstance(home, dict):
                    home_score = home.get("score", home.get("homeScore", "-"))
                else:
                    home_score = home
                if isinstance(away, dict):
                    away_score = away.get("score", away.get("awayScore", "-"))
                else:
                    away_score = away
                scores_by_event[str(eid)] = {
                    "home": home_score,
                    "away": away_score,
                    "status": item.get("status", ""),
                    "description": item.get("description", ""),
                }
    except Exception as e:
        pass  # In-Play Service pode não estar disponível ou formato diferente
    return scores_by_event


def get_live_games_data(api=None):
    """
    Retorna lista de jogos ao vivo para uso pela API/dashboard.
    Cada item: {jogo, tempo, placar, odds}
    Se api=None, faz login internamente.
    """
    import io
    import contextlib
    config = ConfigParser()
    config.read("config.ini")
    app_key = config.get("betfair", "app_key")
    
    if api is None:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            api = BetfairAPI()
            if not api.login():
                return {"error": "Falha no login", "jogos": []}
    
    filter_dict = {"eventTypeIds": [1], "inPlayOnly": True}
    try:
        markets = api.list_market_catalogue(
            filter_dict=filter_dict,
            market_projection=["MARKET_DESCRIPTION", "RUNNER_DESCRIPTION", "EVENT"],
            max_results=100,
        )
    except Exception as e:
        return {"error": str(e), "jogos": []}
    
    if not markets:
        return {"jogos": []}
    
    events_seen = {}
    event_ids = []
    for m in markets:
        ev = m.get("event", {})
        ev_id = ev.get("id")
        ev_name = ev.get("name", "?")
        if ev_id and ev_id not in events_seen:
            events_seen[ev_id] = {"id": ev_id, "name": ev_name, "markets": []}
            event_ids.append(ev_id)
        if ev_id:
            events_seen[ev_id]["markets"].append(m)
    
    for ev_id, info in events_seen.items():
        for m in info["markets"]:
            en = m.get("event", {}).get("name", "")
            if en and (" v " in en or " vs " in en) and len(en) > 10:
                info["name"] = en
                break
    
    scores = get_inplay_scores(event_ids, api.session_token, app_key)
    timelines = get_event_timelines(event_ids, api.session_token, app_key)
    
    for ev_id, info in events_seen.items():
        sc = scores.get(str(ev_id), {})
        desc = sc.get("description", "")
        if desc and (" v " in desc or " vs " in desc) and len(desc) > 10:
            info["name"] = desc
    
    match_odds_keywords = ("Match Odds", "Resultado", "Result", "1X2", "Mandante/Empate/Visitante")
    market_ids = []
    for info in events_seen.values():
        for m in info["markets"]:
            if any(kw in m.get("marketName", "") for kw in match_odds_keywords):
                market_ids.append(m["marketId"])
                break
    
    odds_by_market = {}
    if market_ids:
        try:
            books = api.list_market_book(
                market_ids=market_ids[:50],
                price_projection={"priceData": ["EX_BEST_OFFERS"]},
            )
            for book in books or []:
                mid = book.get("marketId")
                odds = {}
                for r in book.get("runners", []):
                    p = (r.get("ex", {}).get("availableToBack") or [{}])[0].get("price") or r.get("lastPriceTraded")
                    if p:
                        odds[r.get("runnerName", "")] = float(p)
                odds_by_market[mid] = odds
        except Exception:
            pass
    
    jogos = []
    for ev_id, info in events_seen.items():
        sc = scores.get(str(ev_id), {})
        status = sc.get("status", "")
        elapsed = timelines.get(str(ev_id))
        tempo = _formatar_tempo(status, elapsed)
        
        home_s = sc.get("home", "?")
        away_s = sc.get("away", "?")
        placar = f"{home_s} x {away_s}" if (home_s != "?" and away_s != "?") else "Ao vivo"
        
        odds_str = "-"
        for m in info["markets"]:
            if any(kw in m.get("marketName", "") for kw in match_odds_keywords):
                o = odds_by_market.get(m["marketId"], {})
                if o:
                    parts = [f"{v:.2f}" for v in list(o.values())[:3]]
                    if len(parts) >= 3:
                        odds_str = " / ".join(parts)
                break
        
        jogos.append({
            "jogo": info["name"],
            "tempo": tempo,
            "placar": placar,
            "odds": odds_str,
        })
    
    return {"jogos": jogos}


def main():
    print("=" * 60)
    print("  JOGOS AO VIVO - BETFAIR")
    print("=" * 60)
    
    result = get_live_games_data()
    if "error" in result:
        print(f"\n✗ {result['error']}")
        sys.exit(1)
    
    jogos = result["jogos"]
    if not jogos:
        print("\nNenhum jogo ao vivo no momento.")
        sys.exit(0)
    
    print(f"\n{'JOGO':<40} {'TEMPO':<8} {'PLACAR':<10} {'ODDS (1-X-2)':<25}")
    print("-" * 90)
    for j in jogos:
        nome = j["jogo"][:37] + "..." if len(j["jogo"]) > 40 else j["jogo"]
        print(f"{nome:<40} {j['tempo']:<8} {j['placar']:<10} {j['odds']:<25}")
    print("-" * 90)
    print(f"\nTotal: {len(jogos)} jogo(s) ao vivo")


if __name__ == "__main__":
    main()
