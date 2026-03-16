#!/usr/bin/env python3
"""
Script para analisar o impacto de diferentes limites de odd máxima
"""

import csv
import re
from collections import defaultdict

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
                
                # Data
                data = row.get('Resolvida', '')
                
                bets.append({
                    'odd': odd,
                    'lucro': lucro,
                    'stake': stake,
                    'status': status,
                    'data': data
                })
            except Exception as e:
                continue
    
    return bets

def analisar_impacto_odd_maxima(bets, odd_maxima):
    """Analisa o impacto de usar uma odd máxima específica"""
    apostas_aceitas = []
    apostas_rejeitadas = []
    
    for bet in bets:
        if bet['odd'] <= odd_maxima:
            apostas_aceitas.append(bet)
        else:
            apostas_rejeitadas.append(bet)
    
    # Calcular estatísticas das apostas aceitas
    total_apostas = len(apostas_aceitas)
    ganhas = [b for b in apostas_aceitas if b['status'] == 'Ganhas']
    perdidas = [b for b in apostas_aceitas if b['status'] == 'Perdidas']
    
    ganhas_count = len(ganhas)
    perdidas_count = len(perdidas)
    
    lucro_total = sum(b['lucro'] for b in apostas_aceitas)
    lucro_medio = lucro_total / total_apostas if total_apostas > 0 else 0
    
    win_rate = (ganhas_count / total_apostas * 100) if total_apostas > 0 else 0
    
    # Calcular o que seria perdido com as apostas rejeitadas
    lucro_perdido = sum(b['lucro'] for b in apostas_rejeitadas)
    apostas_perdidas_rejeitadas = len([b for b in apostas_rejeitadas if b['status'] == 'Perdidas'])
    apostas_ganhas_rejeitadas = len([b for b in apostas_rejeitadas if b['status'] == 'Ganhas'])
    
    return {
        'odd_maxima': odd_maxima,
        'total_apostas': total_apostas,
        'ganhas': ganhas_count,
        'perdidas': perdidas_count,
        'win_rate': win_rate,
        'lucro_total': lucro_total,
        'lucro_medio': lucro_medio,
        'apostas_rejeitadas': len(apostas_rejeitadas),
        'lucro_perdido': lucro_perdido,
        'apostas_perdidas_rejeitadas': apostas_perdidas_rejeitadas,
        'apostas_ganhas_rejeitadas': apostas_ganhas_rejeitadas,
        'apostas_rejeitadas_detalhes': apostas_rejeitadas
    }

def main():
    filename = 'ExchangeBets_Settled (8).csv'
    
    print("=" * 80)
    print("📊 ANÁLISE DE IMPACTO: DIFERENTES LIMITES DE ODD MÁXIMA")
    print("=" * 80)
    
    bets = parse_csv(filename)
    print(f"\n✅ Total de apostas no histórico: {len(bets)}")
    
    # Calcular lucro total atual (sem filtro)
    lucro_total_sem_filtro = sum(b['lucro'] for b in bets)
    print(f"💰 Lucro total SEM filtro de odd máxima: R$ {lucro_total_sem_filtro:.2f}\n")
    
    # Testar diferentes limites de odd máxima
    limites = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 10.0, 20.0, 100.0]
    
    resultados = []
    for limite in limites:
        resultado = analisar_impacto_odd_maxima(bets, limite)
        resultados.append(resultado)
    
    # Mostrar tabela comparativa
    print("\n" + "=" * 80)
    print("📈 COMPARAÇÃO DE DIFERENTES LIMITES DE ODD MÁXIMA")
    print("=" * 80)
    print(f"{'Odd Máx':<10} {'Apostas':<10} {'Ganhas':<10} {'Perdidas':<10} {'Win Rate':<12} {'Lucro Total':<15} {'Lucro Médio':<15} {'Rejeitadas':<12}")
    print("-" * 80)
    
    for r in resultados:
        print(f"{r['odd_maxima']:<10.1f} {r['total_apostas']:<10} {r['ganhas']:<10} {r['perdidas']:<10} "
              f"{r['win_rate']:<12.1f}% R$ {r['lucro_total']:<12.2f} R$ {r['lucro_medio']:<13.2f} {r['apostas_rejeitadas']:<12}")
    
    # Mostrar detalhes das apostas rejeitadas para odd máxima de 1.5
    print("\n" + "=" * 80)
    print("🚫 APOSTAS QUE SERIAM REJEITADAS COM ODD MÁXIMA = 1.5")
    print("=" * 80)
    
    resultado_1_5 = analisar_impacto_odd_maxima(bets, 1.5)
    apostas_rejeitadas = resultado_1_5['apostas_rejeitadas_detalhes']
    
    if apostas_rejeitadas:
        print(f"\nTotal de apostas rejeitadas: {len(apostas_rejeitadas)}")
        print(f"Lucro total dessas apostas: R$ {resultado_1_5['lucro_perdido']:.2f}")
        print(f"  - Apostas ganhas rejeitadas: {resultado_1_5['apostas_ganhas_rejeitadas']}")
        print(f"  - Apostas perdidas rejeitadas: {resultado_1_5['apostas_perdidas_rejeitadas']}")
        
        print("\n📋 Detalhes das apostas rejeitadas:")
        print(f"{'Odd':<10} {'Status':<12} {'Lucro/Perda':<15} {'Data':<20}")
        print("-" * 60)
        for bet in sorted(apostas_rejeitadas, key=lambda x: x['odd'], reverse=True):
            status_emoji = "✅" if bet['status'] == 'Ganhas' else "❌"
            print(f"{bet['odd']:<10.2f} {status_emoji} {bet['status']:<10} R$ {bet['lucro']:<12.2f} {bet['data'][:20]:<20}")
    
    # Mostrar melhor opção
    melhor_resultado = max(resultados, key=lambda x: x['lucro_total'])
    print("\n" + "=" * 80)
    print("🏆 MELHOR CONFIGURAÇÃO (MAIOR LUCRO TOTAL)")
    print("=" * 80)
    print(f"Odd Máxima: {melhor_resultado['odd_maxima']:.1f}")
    print(f"Total de Apostas: {melhor_resultado['total_apostas']}")
    print(f"Ganhas: {melhor_resultado['ganhas']} | Perdidas: {melhor_resultado['perdidas']}")
    print(f"Win Rate: {melhor_resultado['win_rate']:.1f}%")
    print(f"💰 Lucro Total: R$ {melhor_resultado['lucro_total']:.2f}")
    print(f"💰 Lucro Médio por Aposta: R$ {melhor_resultado['lucro_medio']:.2f}")
    
    # Comparar com configuração atual (1.5)
    print("\n" + "=" * 80)
    print("📊 COMPARAÇÃO: ODD MÁXIMA 1.5 vs SEM LIMITE")
    print("=" * 80)
    resultado_1_5 = analisar_impacto_odd_maxima(bets, 1.5)
    resultado_sem_limite = analisar_impacto_odd_maxima(bets, 1000.0)  # Praticamente sem limite
    
    diferenca_lucro = resultado_sem_limite['lucro_total'] - resultado_1_5['lucro_total']
    diferenca_apostas = resultado_sem_limite['total_apostas'] - resultado_1_5['total_apostas']
    
    print(f"\nCom Odd Máxima 1.5:")
    print(f"  - Apostas: {resultado_1_5['total_apostas']}")
    print(f"  - Lucro Total: R$ {resultado_1_5['lucro_total']:.2f}")
    print(f"  - Lucro Médio: R$ {resultado_1_5['lucro_medio']:.2f}")
    
    print(f"\nSem Limite de Odd Máxima:")
    print(f"  - Apostas: {resultado_sem_limite['total_apostas']}")
    print(f"  - Lucro Total: R$ {resultado_sem_limite['lucro_total']:.2f}")
    print(f"  - Lucro Médio: R$ {resultado_sem_limite['lucro_medio']:.2f}")
    
    print(f"\n📈 Diferença:")
    print(f"  - Apostas adicionais: {diferenca_apostas}")
    print(f"  - Lucro adicional: R$ {diferenca_lucro:.2f}")
    
    if diferenca_lucro > 0:
        print(f"\n✅ CONCLUSÃO: Sem limite de odd máxima, você teria ganhado R$ {diferenca_lucro:.2f} a mais")
    else:
        print(f"\n❌ CONCLUSÃO: Com limite de odd máxima 1.5, você evitou perder R$ {abs(diferenca_lucro):.2f}")

if __name__ == '__main__':
    main()

