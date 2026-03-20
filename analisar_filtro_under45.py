#!/usr/bin/env python3
"""
Análise e Filtro: Estratégia Under 4.5 baseada no Over 0.5 como indicador

Ideia: em vez de apostar Over 0.5 e correr risco do 0-0,
usar o nível de confiança do Over 0.5 como filtro para escolher
o melhor Under disponível — eliminando o risco do 0-0.

Executar: python3 analisar_filtro_under45.py [arquivo.csv]
"""

import csv
import sys
import os
from collections import defaultdict


CSV_DEFAULT = "ExchangeBets_Settled (31).csv"

# ─────────────────────────────────────────────────────────────
# Leitura e parsing
# ─────────────────────────────────────────────────────────────

def parse_csv(filename):
    bets = []
    with open(filename, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if len(row) < 9:
                continue
            desc    = row[2]
            odds    = row[4].strip()
            stake   = row[5].strip()
            profit  = row[7].strip().replace(" ", "")
            status  = row[8].strip()

            if   "Mais de 0,5 gols"   in desc: btype = "over_05"
            elif "Menos de 4,5 gols"  in desc: btype = "under_45"
            elif "Menos de 5,5 gols"  in desc: btype = "under_55"
            elif "Menos de 6,5 gols"  in desc: btype = "under_65"
            elif "Menos de 3,5 gols"  in desc: btype = "under_35"
            elif "0 - 0" in desc and "Placar correto" in desc: btype = "cs_00"
            else: btype = "other"

            # Nome do jogo: tudo antes do tipo de mercado
            for marker in ["Mais de", "Menos de", "0 - 0", "-Resultado"]:
                if marker in desc:
                    game = desc.split(marker)[0].strip()
                    break
            else:
                game = desc[:50]

            won = status == "Ganhas"
            try:   odds_v   = float(odds.replace(",", "."))
            except: odds_v  = 0.0
            try:   profit_v = float(profit.replace(",", ".").replace("--", "0"))
            except: profit_v = 0.0
            try:   stake_v  = float(stake.replace(",", "."))
            except: stake_v  = 15.0

            bets.append(dict(
                type=btype, won=won, odds=odds_v,
                profit=profit_v, stake=stake_v, game=game
            ))
    return bets


# ─────────────────────────────────────────────────────────────
# Relatório geral
# ─────────────────────────────────────────────────────────────

def relatorio_geral(bets):
    print("\n" + "=" * 70)
    print("  RESUMO GERAL DAS APOSTAS")
    print("=" * 70)

    tipos = {
        "over_05":  "Over 0,5 gols",
        "under_45": "Under 4,5 gols",
        "under_55": "Under 5,5 gols",
        "cs_00":    "Placar Correto 0-0",
        "other":    "Outros",
    }

    header = f"{'Tipo':<22} {'Qtd':>5} {'Win%':>7} {'Odds med':>9} {'Break-even':>11} {'ROI':>8} {'P&L':>10}"
    print(header)
    print("-" * 70)

    for btype, label in tipos.items():
        grupo = [b for b in bets if b["type"] == btype]
        if not grupo:
            continue
        n    = len(grupo)
        wins = sum(1 for b in grupo if b["won"])
        wagered = sum(b["stake"] for b in grupo)
        pl   = sum(b["profit"] for b in grupo)
        avg_odds = sum(b["odds"] for b in grupo) / n
        win_pct  = wins / n * 100
        be_pct   = (1 / avg_odds) * 100 if avg_odds else 0
        roi = pl / wagered * 100 if wagered else 0

        roi_str = f"{roi:+.1f}%"
        flag = " ✅" if roi > 0 else (" ⚠️" if roi > -3 else " ❌")
        print(f"{label:<22} {n:>5} {win_pct:>6.1f}% {avg_odds:>9.3f} {be_pct:>10.1f}% "
              f"{roi_str:>8} R${pl:>8.2f}{flag}")

    total_pl = sum(b["profit"] for b in bets)
    total_w  = sum(b["stake"] for b in bets)
    print("-" * 70)
    print(f"{'TOTAL':<22} {len(bets):>5} {'':>7} {'':>9} {'':>11} "
          f"{total_pl/total_w*100:>+7.1f}% R${total_pl:>8.2f}")


# ─────────────────────────────────────────────────────────────
# Correlação Over 0.5 × Under 4.5 no mesmo jogo
# ─────────────────────────────────────────────────────────────

def correlacionar_jogos(bets):
    """Encontra jogos onde ambas as apostas (Over 0,5 e Under 4,5) foram feitas."""
    por_jogo = defaultdict(list)
    for b in bets:
        if b["game"]:
            por_jogo[b["game"]].append(b)

    pares = []
    for game, lista in por_jogo.items():
        o05s = [b for b in lista if b["type"] == "over_05"]
        u45s = [b for b in lista if b["type"] == "under_45"]
        for o in o05s:
            for u in u45s:
                pares.append(dict(
                    game=game,
                    o05_odds=o["odds"], o05_won=o["won"],
                    u45_odds=u["odds"], u45_won=u["won"],
                ))
    return pares


def analise_filtros(pares):
    print("\n" + "=" * 70)
    print("  ANÁLISE: UNDER 4,5 FILTRADO PELA ODD DO OVER 0,5")
    print("=" * 70)
    print(f"\n  Total de jogos com ambas as apostas: {len(pares)}\n")

    # Resultados combinados
    aa = sum(1 for p in pares if     p["o05_won"] and     p["u45_won"])
    ab = sum(1 for p in pares if     p["o05_won"] and not p["u45_won"])
    ba = sum(1 for p in pares if not p["o05_won"] and     p["u45_won"])
    bb = sum(1 for p in pares if not p["o05_won"] and not p["u45_won"])

    print(f"  Over OK + Under OK   (1-4 gols): {aa:>4}  → ambos ganham")
    print(f"  Over OK + Under FAIL (5+ gols) : {ab:>4}  → jogo explodiu")
    print(f"  Over FAIL + Under OK (0-0)     : {ba:>4}  → jogo zerou")
    print(f"  Ambos falham                   : {bb:>4}")

    # ── Filtro por faixa do Over 0.5 ──────────────────────────
    print("\n" + "-" * 70)
    print("  Under 4,5 win-rate por faixa de odd do Over 0,5\n")

    faixas = [
        (1.00, 1.14, "Muito forte  (1.00–1.14)"),
        (1.14, 1.17, "Forte        (1.14–1.17)"),
        (1.17, 1.21, "Moderado     (1.17–1.21)"),
        (1.21, 1.30, "Elevado      (1.21–1.30)"),
        (1.30, 9.99, "Alto/Live    (1.30+)     "),
    ]

    melhor_roi = -999
    melhor_faixa = None

    for lo, hi, label in faixas:
        grupo = [p for p in pares if lo <= p["o05_odds"] < hi]
        if len(grupo) < 3:
            continue
        n       = len(grupo)
        u45_win = sum(1 for p in grupo if p["u45_won"])
        wr      = u45_win / n * 100
        avg_u45 = sum(p["u45_odds"] for p in grupo) / n
        be      = 1 / avg_u45 * 100

        stake = 15.0
        pl = (u45_win * stake * (avg_u45 - 1)
              - (n - u45_win) * stake)
        roi = pl / (n * stake) * 100

        status = "✅ POSITIVO" if roi > 0 else ("⚠️  quase" if roi > -3 else "❌")
        print(f"  {label}: {n:>4} jogos | Under win {wr:>5.1f}% "
              f"(BE={be:.1f}%) | odds {avg_u45:.3f} | ROI {roi:>+5.1f}%  {status}")

        if roi > melhor_roi:
            melhor_roi   = roi
            melhor_faixa = (lo, hi, label, n, wr, avg_u45, roi)

    return melhor_faixa


# ─────────────────────────────────────────────────────────────
# Backtest da nova estratégia
# ─────────────────────────────────────────────────────────────

def backtest(pares, o05_min=1.17, o05_max=1.30, stake=15.0):
    """
    Simula: apostar Under 4,5 apenas nos jogos em que
    o Over 0,5 estava na faixa [o05_min, o05_max).
    """
    selecionados = [p for p in pares if o05_min <= p["o05_odds"] < o05_max]
    if not selecionados:
        return

    print("\n" + "=" * 70)
    print(f"  BACKTEST — UNDER 4,5 quando Over 0,5 está entre {o05_min} e {o05_max}")
    print("=" * 70)

    n       = len(selecionados)
    wins    = sum(1 for p in selecionados if p["u45_won"])
    losses  = n - wins
    avg_odd = sum(p["u45_odds"] for p in selecionados) / n
    pl      = wins * stake * (avg_odd - 1) - losses * stake
    roi     = pl / (n * stake) * 100
    wr      = wins / n * 100

    # Comparar com: apostar Over 0.5 nos mesmos jogos
    o05_wins   = sum(1 for p in selecionados if p["o05_won"])
    avg_o05    = sum(p["o05_odds"] for p in selecionados) / n
    o05_pl     = o05_wins * stake * (avg_o05 - 1) - (n - o05_wins) * stake
    o05_roi    = o05_pl / (n * stake) * 100

    print(f"\n  Jogos selecionados : {n}")
    print(f"  Stake por aposta   : R$ {stake:.2f}")
    print(f"  Capital necessário : R$ {n * stake:.2f}\n")

    print(f"  ┌─────────────────────────────────────────────────────┐")
    print(f"  │  NOVA ESTRATÉGIA  — Under 4,5                       │")
    print(f"  │  Win rate : {wr:>5.1f}%  (break-even: {1/avg_odd*100:.1f}%)           │")
    print(f"  │  Odds média: {avg_odd:.3f}                               │")
    print(f"  │  P&L total : R$ {pl:>+8.2f}                          │")
    print(f"  │  ROI       : {roi:>+6.1f}%                               │")
    print(f"  └─────────────────────────────────────────────────────┘")

    print(f"\n  ┌─────────────────────────────────────────────────────┐")
    print(f"  │  ESTRATÉGIA ATUAL — Over 0,5 (nos mesmos jogos)     │")
    print(f"  │  Win rate : {o05_wins/n*100:>5.1f}%                                │")
    print(f"  │  Odds média: {avg_o05:.3f}                               │")
    print(f"  │  P&L total : R$ {o05_pl:>+8.2f}                          │")
    print(f"  │  ROI       : {o05_roi:>+6.1f}%                               │")
    print(f"  └─────────────────────────────────────────────────────┘")

    print("\n  Jogos em que Under 4,5 PERDEU (5+ gols):")
    explosoes = [p for p in selecionados if not p["u45_won"]]
    if explosoes:
        for p in explosoes:
            print(f"    {p['game'][:45]:<45} Over0.5={p['o05_odds']:.2f}  U45={p['u45_odds']:.2f}")
    else:
        print("    Nenhum! Win rate 100% nessa faixa.")


# ─────────────────────────────────────────────────────────────
# Decisor em tempo real (função auxiliar para o bot)
# ─────────────────────────────────────────────────────────────

def decidir_aposta(over_05_odd: float, under_45_odd: float,
                   under_55_odd: float = 0.0,
                   under_65_odd: float = 0.0) -> dict:
    """
    Recebe as odds disponíveis para um jogo e retorna a decisão de aposta.

    Regras calibradas pelos dados históricos:

      1. Over 0,5 entre 1.17 e 1.30 → zona "moderada" → Under 4,5 tem ROI positivo
      2. Over 0,5 < 1.17 (muito forte) → jogo pode ser goleada → evitar Under 4,5
      3. Over 0,5 ≥ 1.30 (cota alta, jogo ao vivo / defensivo) → Under mais alto
         como 5,5 ou 6,5 podem ser interessantes se odds ≥ 1.04

    Retorna dict com chaves:
      'apostar'   : bool
      'mercado'   : str   (ex: "Under 4,5 gols")
      'motivo'    : str
      'confianca' : str   ("ALTA" | "MÉDIA" | "BAIXA")
    """
    if over_05_odd <= 0:
        return {"apostar": False, "mercado": "", "motivo": "Odd Over 0,5 inválida", "confianca": ""}

    # Zona moderada — historicamente ROI positivo
    if 1.17 <= over_05_odd < 1.30:
        if under_45_odd >= 1.09:
            return {
                "apostar":    True,
                "mercado":    "Under 4,5 gols",
                "motivo":     f"Over 0,5 em {over_05_odd:.2f} = zona moderada. "
                              f"Under 4,5 @ {under_45_odd:.2f} cobre 0-0 e sai gol.",
                "confianca":  "ALTA",
            }

    # Over muito forte (< 1.17) — jogo "aberto", risco de 5+ gols
    if over_05_odd < 1.17:
        return {
            "apostar":   False,
            "mercado":   "",
            "motivo":    f"Over 0,5 em {over_05_odd:.2f} = jogo muito aberto, "
                         "Under 4,5 falha mais nesses jogos (goleadas).",
            "confianca": "BAIXA",
        }

    # Over alto (≥ 1.30) — jogo defensivo / ao vivo sem gols
    if over_05_odd >= 1.30:
        if under_55_odd >= 1.04:
            return {
                "apostar":    True,
                "mercado":    "Under 5,5 gols",
                "motivo":     f"Over 0,5 em {over_05_odd:.2f} = jogo defensivo. "
                              f"Under 5,5 @ {under_55_odd:.2f} é quase certo.",
                "confianca":  "MÉDIA",
            }
        if under_45_odd >= 1.04:
            return {
                "apostar":    True,
                "mercado":    "Under 4,5 gols",
                "motivo":     f"Over 0,5 em {over_05_odd:.2f} = jogo defensivo. "
                              f"Under 4,5 @ {under_45_odd:.2f}.",
                "confianca":  "MÉDIA",
            }

    return {
        "apostar":   False,
        "mercado":   "",
        "motivo":    "Odds fora das faixas rentáveis.",
        "confianca": "BAIXA",
    }


# ─────────────────────────────────────────────────────────────
# Projeção de lucro
# ─────────────────────────────────────────────────────────────

def projecao_lucro(pares, stake=15.0):
    zona = [p for p in pares if 1.17 <= p["o05_odds"] < 1.30]
    if not zona:
        return
    n       = len(zona)
    wins    = sum(1 for p in zona if p["u45_won"])
    avg_odd = sum(p["u45_odds"] for p in zona) / n
    roi     = (wins * (avg_odd - 1) - (n - wins)) / n

    print("\n" + "=" * 70)
    print("  PROJEÇÃO DE LUCRO (zona 1.17–1.30)")
    print("=" * 70)
    for apostas_dia in [5, 10, 15, 20]:
        lucro_dia = apostas_dia * stake * roi
        lucro_mes = lucro_dia * 26
        print(f"  {apostas_dia:>2} apostas/dia × R${stake:.0f}  →  "
              f"~R$ {lucro_dia:>+7.2f}/dia  |  ~R$ {lucro_mes:>+8.2f}/mês")


# ─────────────────────────────────────────────────────────────
# Demo do decisor
# ─────────────────────────────────────────────────────────────

def demo_decisor():
    print("\n" + "=" * 70)
    print("  DEMO: COMO USAR O DECISOR EM TEMPO REAL")
    print("=" * 70)

    exemplos = [
        ("Jogo com Over 0,5 @ 1.15 (muito forte)",  1.15, 1.10, 1.06, 1.03),
        ("Jogo com Over 0,5 @ 1.19 (moderado)",     1.19, 1.11, 1.07, 1.03),
        ("Jogo com Over 0,5 @ 1.23 (moderado+)",    1.23, 1.12, 1.07, 1.04),
        ("Jogo com Over 0,5 @ 1.40 (ao vivo, 0-0)", 1.40, 1.07, 1.04, 1.02),
        ("Jogo com Over 0,5 @ 2.00 (muito defensivo)",2.00,1.04, 1.02, 1.01),
    ]

    for desc, o05, u45, u55, u65 in exemplos:
        res = decidir_apostar(o05, u45, u55, u65)
        flag = "✅" if res["apostar"] else "❌"
        print(f"\n  {flag} {desc}")
        if res["apostar"]:
            print(f"     Apostar: {res['mercado']}  |  Confiança: {res['confianca']}")
        print(f"     Motivo: {res['motivo']}")


# corrigir nome da função pública
decidir_apostar = decidir_aposta


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    arquivo = sys.argv[1] if len(sys.argv) > 1 else CSV_DEFAULT

    if not os.path.exists(arquivo):
        print(f"Arquivo não encontrado: {arquivo}")
        sys.exit(1)

    print(f"\nLendo: {arquivo}")
    bets = parse_csv(arquivo)
    print(f"Total de registros: {len(bets)}")

    relatorio_geral(bets)

    pares = correlacionar_jogos(bets)
    melhor = analise_filtros(pares)

    # Backtest na zona recomendada
    backtest(pares, o05_min=1.17, o05_max=1.30)

    # Backtest comparativo — zona muito forte (problemática)
    backtest(pares, o05_min=1.00, o05_max=1.17)

    projecao_lucro(pares)
    demo_decisor()

    print("\n" + "=" * 70)
    print("  CONCLUSÃO")
    print("=" * 70)
    print("""
  Zona RECOMENDADA para Under 4,5:
    Over 0,5 entre 1.17 e 1.30

  Lógica:
    - Jogo moderado: gols esperados, mas não é uma goleada
    - Under 4,5 cobre TODOS os resultados (0-0 inclusive)
    - Só perde se o jogo tiver 5+ gols — raro nesses jogos

  Zona a EVITAR para Under 4,5:
    Over 0,5 abaixo de 1.17

  Lógica:
    - Jogo muito "aberto" → goleadas acontecem mais
    - Under 4,5 falha mais nessa faixa

  Para o bot: use a função decidir_apostar(over_05_odd, under_45_odd)
    import analisar_filtro_under45 as filtro
    decisao = filtro.decidir_apostar(odd_over05, odd_under45)
    if decisao['apostar']:
        # fazer aposta no decisao['mercado']
""")
    print("=" * 70)
