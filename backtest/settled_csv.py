#!/usr/bin/env python3
"""Backtest deduplicado de apostas liquidadas exportadas da Betfair."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COMMISSION = 0.065
BET_ID_RE = re.compile(r"ID Aposta Betfair\s+([^ |\r\n]+)", re.IGNORECASE)
PT_MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}


def number(value: str) -> float:
    text = str(value or "").strip().replace("R$", "").replace(" ", "")
    if not text or text == "--":
        return 0.0
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    return float(text)


def parse_date(value: str) -> datetime:
    match = re.match(
        r"(\d{1,2})-([A-Za-zçÇ]+)-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})",
        value.strip(),
    )
    if not match:
        return datetime.min
    day, month, year, hour, minute, second = match.groups()
    return datetime(
        2000 + int(year), PT_MONTHS.get(month.lower()[:3], 1), int(day),
        int(hour), int(minute), int(second),
    )


def parse_market(description: str) -> str:
    lower = description.lower()
    if ("escant" in lower or "corner" in lower) and "10,5" in lower:
        return "Corners O/U 10.5"
    if ("escant" in lower or "corner" in lower) and "8,5" in lower:
        return "Corners O/U 8.5"
    for line in ("0,5", "1,5", "2,5", "3,5", "4,5", "5,5", "6,5"):
        if f"mais/menos de {line} gols" in lower:
            return f"Goals O/U {line}"
    if "placar correto" in lower:
        return "Correct Score"
    if "resultado" in lower or "match odds" in lower:
        return "Match Odds"
    return "Other"


def read_rows(paths: Iterable[Path]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                description = raw.get("Descrição", "")
                match = BET_ID_RE.search(description)
                rows.append({
                    "bet_id": match.group(1) if match else description,
                    "placed_at": parse_date(raw.get("Realizada", "")),
                    "description": description,
                    "market": parse_market(description),
                    "odds": number(raw.get("Cotações", "0")),
                    "stake": number(raw.get("Valor Apostado (R$)", "0")),
                    "profit": number(raw.get("Lucro/Perda", "0")),
                    "won": raw.get("Status", "").strip().lower() == "ganhas",
                    "source": path.name,
                })
    return rows


def deduplicate(rows: Iterable[dict]) -> list[dict]:
    unique: dict[str, dict] = {}
    for row in rows:
        unique[row["bet_id"]] = row
    return sorted(unique.values(), key=lambda row: row["placed_at"])


def wilson_interval(wins: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    p = wins / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def summarize(rows: list[dict], commission: float = DEFAULT_COMMISSION) -> dict:
    if not rows:
        return {"bets": 0}
    wins = sum(row["won"] for row in rows)
    stake = sum(row["stake"] for row in rows)
    reported = sum(row["profit"] for row in rows)
    conservative = sum(
        row["profit"] * (1 - commission) if row["profit"] > 0 else row["profit"]
        for row in rows
    )
    cumulative = peak = drawdown = 0.0
    for row in rows:
        cumulative += row["profit"]
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    low, high = wilson_interval(wins, len(rows))
    return {
        "bets": len(rows),
        "wins": wins,
        "losses": len(rows) - wins,
        "win_rate_pct": round(100 * wins / len(rows), 2),
        "win_rate_ci95_pct": [round(100 * low, 2), round(100 * high, 2)],
        "stake": round(stake, 2),
        "average_odds": round(sum(row["odds"] for row in rows) / len(rows), 3),
        "reported_profit": round(reported, 2),
        "conservative_profit": round(conservative, 2),
        "roi_pct": round(100 * reported / stake, 2) if stake else 0.0,
        "conservative_roi_pct": round(100 * conservative / stake, 2) if stake else 0.0,
        "max_drawdown": round(drawdown, 2),
    }


def odds_segments(rows: list[dict]) -> dict[str, dict]:
    bins = (
        (1.01, 1.10), (1.10, 1.20), (1.20, 1.30), (1.30, 1.40),
        (1.40, 1.50), (1.50, 2.00), (2.00, 1001.0),
    )
    return {
        f"{low:.2f}-{high:.2f}": summarize([
            row for row in rows if low <= row["odds"] < high
        ])
        for low, high in bins
        if any(low <= row["odds"] < high for row in rows)
    }


def walk_forward(
    rows: list[dict],
    market: str = "Goals O/U 4,5",
    min_odds: float = 1.30,
    max_odds: float = 1.40,
    train_fraction: float = 0.70,
) -> dict:
    candidates = [
        row for row in rows
        if row["market"] == market and min_odds <= row["odds"] < max_odds
    ]
    split = int(len(candidates) * train_fraction)
    return {
        "rule": {
            "market": market,
            "min_odds": min_odds,
            "max_odds": max_odds,
            "train_fraction": train_fraction,
        },
        "train": summarize(candidates[:split]),
        "test": summarize(candidates[split:]),
    }


def analyze(paths: Iterable[Path], commission: float = DEFAULT_COMMISSION) -> dict:
    raw = read_rows(paths)
    rows = deduplicate(raw)
    by_market: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_market[row["market"]].append(row)
    return {
        "source_rows": len(raw),
        "unique_bets": len(rows),
        "duplicates_removed": len(raw) - len(rows),
        "commission_assumption_pct": commission * 100,
        "overall": summarize(rows, commission),
        "by_market": {
            market: summarize(market_rows, commission)
            for market, market_rows in sorted(by_market.items())
        },
        "by_odds": odds_segments(rows),
        "u45_walk_forward": walk_forward(rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest deduplicado Betfair")
    parser.add_argument("files", nargs="*")
    parser.add_argument("--commission", type=float, default=DEFAULT_COMMISSION)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    paths = [Path(value) for value in args.files] if args.files else sorted(
        ROOT.glob("ExchangeBets_Settled*.csv")
    )
    if not paths:
        print("Nenhum CSV encontrado.", file=sys.stderr)
        return 1
    report = analyze(paths, args.commission)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"Linhas: {report['source_rows']} | IDs únicos: {report['unique_bets']}")
    print(f"Duplicatas removidas: {report['duplicates_removed']}")
    overall = report["overall"]
    print(
        f"P/L reportado: R$ {overall['reported_profit']:+.2f} | "
        f"ROI: {overall['roi_pct']:+.2f}% | "
        f"Drawdown: R$ {overall['max_drawdown']:.2f}"
    )
    for market, result in report["by_market"].items():
        print(
            f"{market}: {result['bets']} apostas | "
            f"ROI {result['roi_pct']:+.2f}% | P/L R$ {result['reported_profit']:+.2f}"
        )
    test = report["u45_walk_forward"]["test"]
    print(
        "Teste temporal U4.5 1.30-1.40: "
        f"{test.get('bets', 0)} apostas | ROI {test.get('roi_pct', 0):+.2f}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
