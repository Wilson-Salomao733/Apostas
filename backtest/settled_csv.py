#!/usr/bin/env python3
"""Analisa CSVs de apostas liquidadas da Betfair (backtest offline)."""

from __future__ import annotations

import argparse
import csv
import glob
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMISSION = 0.05


def parse_market(desc: str) -> str:
    m = re.search(r"(Mais/Menos de [^|]+|Match Odds|Resultado)", desc)
    return (m.group(1).strip() if m else "outro")


def parse_league(desc: str) -> str:
    parts = desc.split("|")
    if parts:
        game = parts[0].split("-")[0].strip()
        return game[:60]
    return "?"


def analyze_file(path: Path) -> dict:
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    total_pl = 0.0
    total_pl_net = 0.0
    wins = losses = 0
    by_market: dict[str, list[float]] = defaultdict(list)
    odds_list: list[float] = []

    for r in rows:
        pl = float(r["Lucro/Perda"].strip().replace(",", "."))
        total_pl += pl
        net = pl * (1 - COMMISSION) if pl > 0 else pl
        total_pl_net += net
        if r["Status"] == "Ganhas":
            wins += 1
        else:
            losses += 1
        odds = float(r["Cotações"].replace(",", "."))
        odds_list.append(odds)
        by_market[parse_market(r["Descrição"])].append(pl)

    n = len(rows) or 1
    return {
        "file": path.name,
        "bets": len(rows),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / n * 100,
        "pl_gross": round(total_pl, 2),
        "pl_net": round(total_pl_net, 2),
        "avg_odds": round(sum(odds_list) / n, 3) if odds_list else 0,
        "by_market": {k: round(sum(v), 2) for k, v in by_market.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest de CSVs Betfair liquidados")
    parser.add_argument(
        "files",
        nargs="*",
        help="Arquivos CSV (padrão: ExchangeBets_Settled*.csv no diretório raiz)",
    )
    args = parser.parse_args()

    if args.files:
        paths = [Path(f) for f in args.files]
    else:
        paths = sorted(ROOT.glob("ExchangeBets_Settled*.csv"))

    if not paths:
        print("Nenhum CSV encontrado.", file=sys.stderr)
        return 1

    print("=" * 60)
    print("BACKTEST — Apostas liquidadas Betfair")
    print(f"Comissão estimada nos ganhos: {COMMISSION * 100:.0f}%")
    print("=" * 60)

    grand_pl = 0.0
    grand_net = 0.0
    grand_bets = 0

    for path in paths:
        if not path.exists():
            print(f"Arquivo não encontrado: {path}")
            continue
        r = analyze_file(path)
        grand_pl += r["pl_gross"]
        grand_net += r["pl_net"]
        grand_bets += r["bets"]
        print(f"\n📁 {r['file']}")
        print(f"   Apostas: {r['bets']} | Win rate: {r['win_rate']:.1f}%")
        print(f"   Odd média: {r['avg_odds']:.3f}")
        print(f"   P/L bruto: R$ {r['pl_gross']:+.2f}")
        print(f"   P/L líquido (~comissão): R$ {r['pl_net']:+.2f}")
        if r["by_market"]:
            print("   Por mercado:")
            for mkt, pl in sorted(r["by_market"].items(), key=lambda x: -abs(x[1])):
                print(f"     - {mkt}: R$ {pl:+.2f}")

    print("\n" + "=" * 60)
    print(f"TOTAL: {grand_bets} apostas")
    print(f"P/L bruto: R$ {grand_pl:+.2f}")
    print(f"P/L líquido: R$ {grand_net:+.2f}")
    if grand_net <= 0 and grand_bets > 50:
        print("\n⚠️  Estratégia sem edge após comissão — não recomendado full-auto.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
