#!/usr/bin/env python3
"""
Script para analisar o histórico de apostas e sugerir melhorias na estratégia
"""

import csv
import re
from collections import defaultdict
from datetime import datetime

def parse_csv(filename):
    """Lê e analisa o CSV de apostas"""
    bets = []
    
    with open(filename, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                # Extrair odd
                odd_str = row['Cotações'].replace(',', '.')
                odd = float(odd_str)
                
                # Extrair lucro/perda
                lucro_str = row['Lucro/Perda'].replace(' ', '').replace(',', '.')
                lucro = float(lucro_str)
                
                # Extrair stake
                stake_str = row['Valor Apostado (R$)'].replace(',', '.')
                stake = float(stake_str)
                
                # Status
                status = row['Status']
                
                # Extrair tipo de mercado (Under X.5)
                descricao = row['Descrição']
                under_match = re.search(r'Menos de ([\d.]+) gols', descricao)
                under_goals = float(under_match.group(1)) if under_match else None
                
                bets.append({
                    'odd': odd,
                    'lucro': lucro,
                    'stake': stake,
                    'status': status,
                    'under_goals': under_goals,
                    'descricao': descricao
                })
            except Exception as e:
                continue
    
    return bets

def analisar_por_faixa_odd(bets):
    """Analisa performance por faixa de odd"""
    print("\n" + "="*80)
    print("📊 ANÁLISE POR FAIXA DE ODD")
    print("="*80)
    
    faixas = [
        (1.01, 1.10, "1.01 - 1.10"),
        (1.10, 1.20, "1.10 - 1.20"),
        (1.20, 1.30, "1.20 - 1.30"),
        (1.30, 1.50, "1.30 - 1.50"),
        (1.50, 2.00, "1.50 - 2.00"),
        (2.00, 3.00, "2.00 - 3.00"),
        (3.00, 10.00, "3.00+"),
    ]
    
    for min_odd, max_odd, label in faixas:
        faixa_bets = [b for b in bets if min_odd <= b['odd'] < max_odd]
        if not faixa_bets:
            continue
        
        ganhas = [b for b in faixa_bets if b['status'] == 'Ganhas']
        perdidas = [b for b in faixa_bets if b['status'] == 'Perdidas']
        
        total = len(faixa_bets)
        ganhas_count = len(ganhas)
        perdidas_count = len(perdidas)
        
        lucro_total = sum(b['lucro'] for b in faixa_bets)
        lucro_medio = lucro_total / total if total > 0 else 0
        
        win_rate = (ganhas_count / total * 100) if total > 0 else 0
        
        print(f"\n{label}:")
        print(f"  Total: {total} apostas")
        print(f"  Ganhas: {ganhas_count} ({win_rate:.1f}%)")
        print(f"  Perdidas: {perdidas_count} ({100-win_rate:.1f}%)")
        print(f"  Lucro Total: R$ {lucro_total:.2f}")
        print(f"  Lucro Médio: R$ {lucro_medio:.2f}")
        
        if ganhas_count > 0:
            lucro_medio_ganhas = sum(b['lucro'] for b in ganhas) / ganhas_count
            print(f"  Lucro Médio (Ganhas): R$ {lucro_medio_ganhas:.2f}")
        
        if perdidas_count > 0:
            lucro_medio_perdidas = sum(b['lucro'] for b in perdidas) / perdidas_count
            print(f"  Lucro Médio (Perdidas): R$ {lucro_medio_perdidas:.2f}")

def analisar_por_under_goals(bets):
    """Analisa performance por tipo de Under"""
    print("\n" + "="*80)
    print("⚽ ANÁLISE POR TIPO DE UNDER")
    print("="*80)
    
    under_types = defaultdict(list)
    for bet in bets:
        if bet['under_goals']:
            under_types[bet['under_goals']].append(bet)
    
    if not under_types:
        print("\n⚠️ Não foi possível extrair informações de Under Goals do CSV")
        return
    
    for under_goals in sorted(under_types.keys()):
        under_bets = under_types[under_goals]
        ganhas = [b for b in under_bets if b['status'] == 'Ganhas']
        perdidas = [b for b in under_bets if b['status'] == 'Perdidas']
        
        total = len(under_bets)
        ganhas_count = len(ganhas)
        perdidas_count = len(perdidas)
        
        lucro_total = sum(b['lucro'] for b in under_bets)
        lucro_medio = lucro_total / total if total > 0 else 0
        win_rate = (ganhas_count / total * 100) if total > 0 else 0
        
        print(f"\nUnder {under_goals} gols:")
        print(f"  Total: {total} apostas")
        print(f"  Ganhas: {ganhas_count} ({win_rate:.1f}%)")
        print(f"  Perdidas: {perdidas_count} ({100-win_rate:.1f}%)")
        print(f"  Lucro Total: R$ {lucro_total:.2f}")
        print(f"  Lucro Médio: R$ {lucro_medio:.2f}")

def analise_geral(bets):
    """Análise geral das apostas"""
    print("\n" + "="*80)
    print("📈 ANÁLISE GERAL")
    print("="*80)
    
    total = len(bets)
    ganhas = [b for b in bets if b['status'] == 'Ganhas']
    perdidas = [b for b in bets if b['status'] == 'Perdidas']
    
    ganhas_count = len(ganhas)
    perdidas_count = len(perdidas)
    
    lucro_total = sum(b['lucro'] for b in bets)
    lucro_medio = lucro_total / total if total > 0 else 0
    
    win_rate = (ganhas_count / total * 100) if total > 0 else 0
    
    # Odds médias
    odd_media_ganhas = sum(b['odd'] for b in ganhas) / ganhas_count if ganhas_count > 0 else 0
    odd_media_perdidas = sum(b['odd'] for b in perdidas) / perdidas_count if perdidas_count > 0 else 0
    odd_media_geral = sum(b['odd'] for b in bets) / total if total > 0 else 0
    
    print(f"\nTotal de Apostas: {total}")
    print(f"Ganhas: {ganhas_count} ({win_rate:.1f}%)")
    print(f"Perdidas: {perdidas_count} ({100-win_rate:.1f}%)")
    print(f"\nLucro Total: R$ {lucro_total:.2f}")
    print(f"Lucro Médio: R$ {lucro_medio:.2f}")
    print(f"\nOdd Média Geral: {odd_media_geral:.2f}")
    print(f"Odd Média (Ganhas): {odd_media_ganhas:.2f}")
    print(f"Odd Média (Perdidas): {odd_media_perdidas:.2f}")
    
    # Análise de risco/retorno
    if ganhas_count > 0:
        lucro_medio_ganhas = sum(b['lucro'] for b in ganhas) / ganhas_count
        print(f"\nLucro Médio por Vitória: R$ {lucro_medio_ganhas:.2f}")
    
    if perdidas_count > 0:
        lucro_medio_perdidas = sum(b['lucro'] for b in perdidas) / perdidas_count
        print(f"Lucro Médio por Derrota: R$ {lucro_medio_perdidas:.2f}")
        
        # Calcular expectativa matemática
        if ganhas_count > 0:
            expectativa = (win_rate/100 * lucro_medio_ganhas) + ((100-win_rate)/100 * lucro_medio_perdidas)
            print(f"\n🎯 Expectativa Matemática: R$ {expectativa:.2f} por aposta")
            
            if expectativa < 0:
                print("⚠️ ATENÇÃO: Expectativa negativa! A estratégia está perdendo dinheiro a longo prazo.")
            else:
                print("✅ Expectativa positiva! A estratégia está lucrativa a longo prazo.")

def sugerir_melhorias(bets):
    """Sugere melhorias baseadas na análise"""
    print("\n" + "="*80)
    print("💡 SUGESTÕES DE MELHORIA")
    print("="*80)
    
    # Analisar faixas de odd mais lucrativas
    faixas = [
        (1.01, 1.15, "1.01 - 1.15"),
        (1.15, 1.25, "1.15 - 1.25"),
        (1.25, 1.35, "1.25 - 1.35"),
        (1.35, 1.50, "1.35 - 1.50"),
        (1.50, 2.00, "1.50 - 2.00"),
    ]
    
    melhor_faixa = None
    melhor_lucro = float('-inf')
    
    for min_odd, max_odd, label in faixas:
        faixa_bets = [b for b in bets if min_odd <= b['odd'] < max_odd]
        if len(faixa_bets) < 10:  # Mínimo de 10 apostas para considerar
            continue
        
        lucro_total = sum(b['lucro'] for b in faixa_bets)
        lucro_medio = lucro_total / len(faixa_bets)
        
        if lucro_medio > melhor_lucro:
            melhor_lucro = lucro_medio
            melhor_faixa = (min_odd, max_odd, label)
    
    if melhor_faixa:
        print(f"\n✅ Faixa de odd mais lucrativa: {melhor_faixa[2]}")
        print(f"   Lucro médio: R$ {melhor_lucro:.2f}")
        print(f"   Sugestão: Configure odd mínima = {melhor_faixa[0]:.2f} e máxima = {melhor_faixa[1]:.2f}")
    
    # Analisar Under mais lucrativo
    under_types = defaultdict(list)
    for bet in bets:
        if bet['under_goals']:
            under_types[bet['under_goals']].append(bet)
    
    if under_types:
        melhor_under = None
        melhor_lucro_under = float('-inf')
        
        for under_goals, under_bets in under_types.items():
            if len(under_bets) < 10:
                continue
            
            lucro_total = sum(b['lucro'] for b in under_bets)
            lucro_medio = lucro_total / len(under_bets)
            
            if lucro_medio > melhor_lucro_under:
                melhor_lucro_under = lucro_medio
                melhor_under = under_goals
        
        if melhor_under:
            print(f"\n✅ Under mais lucrativo: Under {melhor_under} gols")
            print(f"   Lucro médio: R$ {melhor_lucro_under:.2f}")
            print(f"   Sugestão: Use Under {melhor_under} como prioridade")
    
    # Análise de win rate
    total = len(bets)
    ganhas = [b for b in bets if b['status'] == 'Ganhas']
    win_rate = (len(ganhas) / total * 100) if total > 0 else 0
    
    print(f"\n📊 Taxa de Sucesso Atual: {win_rate:.1f}%")
    
    if win_rate < 60:
        print("⚠️ Taxa de sucesso baixa! Considere:")
        print("   - Aumentar odd mínima (odds mais altas = menos apostas, mas mais seletivas)")
        print("   - Reduzir Under (ex: Under 4.5 em vez de 5.5)")
        print("   - Entrar mais tarde no jogo (ex: minuto 5-10 em vez de 1)")
    
    # Análise de expectativa
    if ganhas:
        lucro_medio_ganhas = sum(b['lucro'] for b in ganhas) / len(ganhas)
        perdidas = [b for b in bets if b['status'] == 'Perdidas']
        if perdidas:
            lucro_medio_perdidas = sum(b['lucro'] for b in perdidas) / len(perdidas)
            expectativa = (win_rate/100 * lucro_medio_ganhas) + ((100-win_rate)/100 * lucro_medio_perdidas)
            
            print(f"\n🎯 Expectativa Matemática: R$ {expectativa:.2f} por aposta")
            
            if expectativa < 0:
                print("\n❌ PROBLEMA CRÍTICO: Expectativa negativa!")
                print("\n🔧 AÇÕES RECOMENDADAS:")
                print("   1. AUMENTE a odd mínima para pelo menos 1.20-1.25")
                print("   2. REDUZA o Under para 4.5 ou até 3.5")
                print("   3. AUMENTE o minuto mínimo de entrada para 5-10")
                print("   4. REDUZA o número máximo de apostas simultâneas")
                print("   5. Considere usar Under 2.5 como segunda prioridade")
            else:
                print("✅ Expectativa positiva, mas pode ser melhorada")

if __name__ == '__main__':
    print("🔍 Analisando histórico de apostas...")
    print("="*80)
    
    filename = 'ExchangeBets_Settled (8).csv'
    bets = parse_csv(filename)
    
    if not bets:
        print("❌ Nenhuma aposta encontrada no arquivo!")
        exit(1)
    
    analise_geral(bets)
    analisar_por_faixa_odd(bets)
    analisar_por_under_goals(bets)
    sugerir_melhorias(bets)
    
    print("\n" + "="*80)
    print("✅ Análise concluída!")
    print("="*80)

