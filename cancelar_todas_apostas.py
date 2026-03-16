#!/usr/bin/env python3
"""
Script para cancelar todas as apostas ativas na Betfair
"""

from betfair_api import BetfairAPI
import json
from datetime import datetime

def main():
    print("=" * 60)
    print("CANCELANDO TODAS AS APOSTAS ATIVAS")
    print("=" * 60)
    print()

    try:
        api = BetfairAPI()

        print("Fazendo login...")
        if not api.login():
            print("✗ Falha no login")
            return
        print("✓ Login realizado com sucesso\n")

        print("Buscando apostas ativas...")
        orders = api.list_current_orders()

        if not orders:
            print("ℹ️ Nenhuma resposta da API")
            return

        current_orders = orders.get('currentOrders', [])
        more_available = orders.get('moreAvailable', False)

        if not current_orders:
            print("ℹ️ Nenhuma aposta ativa encontrada")
            return

        print(f"✓ Encontradas {len(current_orders)} apostas ativas")
        if more_available:
            print("⚠️ Há mais apostas disponíveis")
        print()

        # Agrupar por market_id para cancelar em lote
        bets_by_market = {}
        for order in current_orders:
            market_id = order.get('marketId')
            bet_id = order.get('betId')
            status = order.get('status', 'N/A')
            
            if market_id and bet_id:
                if market_id not in bets_by_market:
                    bets_by_market[market_id] = []
                bets_by_market[market_id].append({
                    'bet_id': bet_id,
                    'status': status,
                    'order': order
                })

        print(f"📊 Apostas agrupadas em {len(bets_by_market)} mercados diferentes\n")

        total_canceled = 0
        total_failed = 0

        # Cancelar apostas por mercado
        for market_id, bets in bets_by_market.items():
            print(f"📌 Mercado: {market_id}")
            print(f"   Apostas neste mercado: {len(bets)}")
            
            bet_ids = [b['bet_id'] for b in bets]
            
            try:
                result = api.cancel_orders(
                    market_id=market_id,
                    bet_ids=bet_ids,
                    customer_ref=f"cancel_all_{int(datetime.now().timestamp())}"
                )
                
                if result and 'instructionReports' in result:
                    for i, report in enumerate(result['instructionReports']):
                        bet_id = bet_ids[i] if i < len(bet_ids) else 'N/A'
                        status = report.get('status', 'N/A')
                        
                        if status == 'SUCCESS':
                            print(f"   ✅ Cancelada: Bet ID {bet_id}")
                            total_canceled += 1
                        else:
                            error_code = report.get('errorCode', 'N/A')
                            error_message = report.get('errorMessage', 'N/A')
                            print(f"   ❌ Falha: Bet ID {bet_id} - {error_code}: {error_message}")
                            total_failed += 1
                else:
                    print(f"   ⚠️ Resposta inesperada da API")
                    total_failed += len(bet_ids)
                    
            except Exception as e:
                print(f"   ❌ Erro ao cancelar: {e}")
                total_failed += len(bet_ids)
            
            print()

        print("=" * 60)
        print("RESUMO")
        print("=" * 60)
        print(f"✅ Canceladas com sucesso: {total_canceled}")
        print(f"❌ Falhas: {total_failed}")
        print(f"📊 Total processadas: {len(current_orders)}")
        print()

        if total_canceled > 0:
            print("✓ Algumas apostas foram canceladas com sucesso!")
        if total_failed > 0:
            print("⚠️ Algumas apostas não puderam ser canceladas")
            print("   (Pode ser que já tenham sido executadas ou o mercado esteja fechado)")

    except Exception as e:
        print(f"✗ Erro: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
