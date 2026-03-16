#!/usr/bin/env python3
"""
Relatório de Performance — Teste R$100
Lê o banco de dados SQLite e gera análise completa de todas as apostas.
Uso: python3 relatorio_teste.py
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

DB_PATH = "data/bets.db"

SEP  = "=" * 65
SEP2 = "-" * 65


def conn():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def fmt(v):
    if v is None:
        return "  —  "
    sign = "+" if v >= 0 else ""
    return f"{sign}R$ {v:.2f}"


def pct(num, den):
    if not den:
        return "—"
    return f"{num/den*100:.1f}%"


def get_actual_profit(row):
    """Retorna o lucro real em R$. Lay Draw já armazena em BRL; outros armazenam em %."""
    apb = row["actual_profit_brl"]
    if apb is not None:
        return float(apb)
    pl = row["profit_loss"]
    stake = row["stake"]
    if pl is not None and stake:
        return float(stake) * float(pl) / 100.0
    return None


def main():
    if not Path(DB_PATH).exists():
        print(f"Banco de dados não encontrado em {DB_PATH}")
        print("Rode o bot pelo menos uma vez antes.")
        sys.exit(1)

    db = conn()
    rows = db.execute("""
        SELECT * FROM bets ORDER BY entry_time
    """).fetchall()

    closed = [r for r in rows if r["status"] not in ("ACTIVE", "active")]
    active = [r for r in rows if r["status"] in ("ACTIVE", "active")]

    if not rows:
        print("Nenhuma aposta registrada ainda.")
        sys.exit(0)

    print(f"\n{SEP}")
    print("  RELATÓRIO DE PERFORMANCE — TESTE R$100")
    print(f"  Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(SEP)

    # ── RESUMO GERAL ────────────────────────────────────────────────
    total     = len(rows)
    n_closed  = len(closed)
    n_active  = len(active)
    n_profit  = sum(1 for r in closed if r["status"] in ("CLOSED_PROFIT", "closed_profit"))
    n_loss    = sum(1 for r in closed if r["status"] in ("CLOSED_LOSS",   "closed_loss"))
    n_timeout = sum(1 for r in closed if "TIMEOUT" in (r["status"] or "").upper()
                                      or "TIMEOUT" in (r["close_reason"] or "").upper())

    profits = [get_actual_profit(r) for r in closed if get_actual_profit(r) is not None]
    total_pl = sum(profits) if profits else 0.0
    total_stake = sum(float(r["stake"]) for r in closed)
    roi = (total_pl / total_stake * 100) if total_stake else 0

    print(f"\n  Total de apostas registradas : {total}")
    print(f"  Apostas encerradas           : {n_closed}")
    print(f"  Apostas ainda ativas         : {n_active}")
    print(f"  Ganhas                       : {n_profit}  ({pct(n_profit, n_closed)})")
    print(f"  Perdidas                     : {n_loss}   ({pct(n_loss,   n_closed)})")
    print(f"  Fechadas por tempo           : {n_timeout}")
    print(f"  Volume apostado total        : R$ {total_stake:.2f}")
    print(f"  Lucro / Perda total          : {fmt(total_pl)}")
    print(f"  ROI                          : {roi:+.2f}%")

    # ── POR ESTRATÉGIA ───────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  POR ESTRATÉGIA")
    print(SEP2)

    by_strategy = defaultdict(list)
    for r in closed:
        by_strategy[r["strategy"] or "Desconhecida"].append(r)

    for strat, bets in sorted(by_strategy.items()):
        g = sum(1 for b in bets if b["status"] in ("CLOSED_PROFIT","closed_profit"))
        l = sum(1 for b in bets if b["status"] in ("CLOSED_LOSS","closed_loss"))
        pl_list = [get_actual_profit(b) for b in bets if get_actual_profit(b) is not None]
        pl_total = sum(pl_list)
        stake_t  = sum(float(b["stake"]) for b in bets)
        r_roi    = (pl_total / stake_t * 100) if stake_t else 0
        print(f"\n  [{strat}]")
        print(f"    Apostas: {len(bets)}  |  {g}G / {l}P  ({pct(g, len(bets))} win)")
        print(f"    Volume : R$ {stake_t:.2f}  |  P&L: {fmt(pl_total)}  |  ROI: {r_roi:+.2f}%")

    # ── POR DIA ──────────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  POR DIA")
    print(SEP2)

    by_day = defaultdict(list)
    for r in closed:
        day = (r["entry_time"] or "")[:10]
        by_day[day].append(r)

    for day in sorted(by_day.keys()):
        bets = by_day[day]
        g = sum(1 for b in bets if b["status"] in ("CLOSED_PROFIT","closed_profit"))
        l = sum(1 for b in bets if b["status"] in ("CLOSED_LOSS","closed_loss"))
        pl_list = [get_actual_profit(b) for b in bets if get_actual_profit(b) is not None]
        pl_day = sum(pl_list)
        print(f"  {day}  {len(bets):>3} apostas  {g}G/{l}P  {fmt(pl_day)}")

    # ── MAIORES GANHOS ───────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  TOP 5 MAIORES GANHOS")
    print(SEP2)

    winners = sorted(
        [(get_actual_profit(r), r) for r in closed if (get_actual_profit(r) or 0) > 0],
        key=lambda x: x[0], reverse=True
    )[:5]
    for pl, r in winners:
        ev = r["event_name"] or r["event_id"] or r["market_id"]
        print(f"  {fmt(pl):>12}  {r['strategy']:<18}  {ev[:35]}  @ {r['entry_price']:.2f}")

    # ── MAIORES PERDAS ───────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  TOP 5 MAIORES PERDAS")
    print(SEP2)

    losers = sorted(
        [(get_actual_profit(r), r) for r in closed if (get_actual_profit(r) or 0) < 0],
        key=lambda x: x[0]
    )[:5]
    for pl, r in losers:
        ev = r["event_name"] or r["event_id"] or r["market_id"]
        reason = r["close_reason"] or "—"
        print(f"  {fmt(pl):>12}  {r['strategy']:<18}  {ev[:30]}  motivo: {reason[:20]}")

    # ── ANÁLISE DE ODDS ──────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  ANÁLISE POR FAIXA DE ODD DE ENTRADA")
    print(SEP2)

    buckets = defaultdict(lambda: {"g": 0, "p": 0, "pl": 0.0})
    for r in closed:
        odd = float(r["entry_price"] or 0)
        if odd <= 0:
            continue
        b = f"{int(odd*10)/10:.1f}"
        pl_v = get_actual_profit(r) or 0
        if r["status"] in ("CLOSED_PROFIT","closed_profit"):
            buckets[b]["g"] += 1
        else:
            buckets[b]["p"] += 1
        buckets[b]["pl"] += pl_v

    print(f"  {'Odd':>5}  {'G':>4}  {'P':>4}  {'Win%':>6}  {'P&L':>10}")
    for odd_b in sorted(buckets.keys(), key=float):
        d = buckets[odd_b]
        tot = d["g"] + d["p"]
        win = pct(d["g"], tot)
        print(f"  {odd_b:>5}  {d['g']:>4}  {d['p']:>4}  {win:>6}  {fmt(d['pl']):>10}")

    # ── MOTIVOS DE SAÍDA ─────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  MOTIVOS DE SAÍDA")
    print(SEP2)

    reasons = defaultdict(lambda: {"n": 0, "pl": 0.0})
    for r in closed:
        reason = (r["close_reason"] or "Desconhecido").split("@")[0].strip()
        pl_v = get_actual_profit(r) or 0
        reasons[reason]["n"] += 1
        reasons[reason]["pl"] += pl_v

    for reason, d in sorted(reasons.items(), key=lambda x: x[1]["pl"]):
        print(f"  {d['n']:>3}x  {fmt(d['pl']):>12}  {reason}")

    # ── APOSTAS ATIVAS ───────────────────────────────────────────────
    if active:
        print(f"\n{SEP2}")
        print(f"  APOSTAS AINDA ATIVAS ({len(active)})")
        print(SEP2)
        for r in active:
            ev = r["event_name"] or r["event_id"] or r["market_id"]
            elapsed = ""
            if r["entry_time"]:
                try:
                    t = datetime.fromisoformat(r["entry_time"])
                    mins = int((datetime.now() - t).total_seconds() / 60)
                    elapsed = f" [{mins} min aberta]"
                except Exception:
                    pass
            print(f"  {r['strategy']:<18}  {ev[:35]}  @ {r['entry_price']:.2f}"
                  f"  stake R${r['stake']:.2f}{elapsed}")

    # ── RECOMENDAÇÕES ────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  RECOMENDAÇÕES AUTOMÁTICAS")
    print(SEP)

    # Lay Draw
    ld = [r for r in closed if r["strategy"] == "Lay Draw"]
    if ld:
        ld_g = sum(1 for r in ld if r["status"] in ("CLOSED_PROFIT","closed_profit"))
        ld_pl = sum(get_actual_profit(r) or 0 for r in ld)
        ld_tp = sum(1 for r in ld if "Take Profit" in (r["close_reason"] or ""))
        ld_sl = sum(1 for r in ld if "Stop Loss" in (r["close_reason"] or ""))
        ld_to = sum(1 for r in ld if "Timeout" in (r["close_reason"] or ""))
        print(f"\n  [Lay Draw] {len(ld)} apostas | {ld_g}G | TP:{ld_tp} SL:{ld_sl} Timeout:{ld_to} | P&L: {fmt(ld_pl)}")
        if ld_sl > ld_tp:
            print("  ⚠️  Mais Stop Loss do que Take Profit → mercado movendo contra antes do gol.")
            print("     Considere: min_odd 3.0, max_odd 3.3 (odds mais altas = mais gols)")
        if ld_to > 0 and ld_to > len(ld) * 0.3:
            print("  ⚠️  Muitos timeouts → jogos sem gol no 1º tempo.")
            print("     Considere: exit_max_minute 40, ou filtrar só ligas de alto ataque.")
        if ld_pl > 0:
            print("  ✅  Estratégia com resultado positivo — manter parâmetros.")

    # Under Goals
    ug = [r for r in closed if "Under" in (r["strategy"] or "") or "Back Under" in (r["strategy"] or "")]
    if ug:
        ug_g = sum(1 for r in ug if r["status"] in ("CLOSED_PROFIT","closed_profit"))
        ug_pl = sum(get_actual_profit(r) or 0 for r in ug)
        print(f"\n  [Under Goals] {len(ug)} apostas | {ug_g}G | P&L: {fmt(ug_pl)}")
        if ug_pl < 0:
            print("  ⚠️  Resultado negativo. Verifique se max_odd está respeitado nos logs.")

    print(f"\n{SEP}\n")
    db.close()


if __name__ == "__main__":
    main()
