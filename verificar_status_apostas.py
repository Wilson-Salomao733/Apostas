#!/usr/bin/env python3
"""
Script para verificar o status detalhado das apostas ativas
"""

from betfair_api import BetfairAPI
import json

def main():
    print("=" * 60)
    print("VERIFICANDO STATUS DAS APOSTAS ATIVAS")
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

        if not current_orders:
            print("ℹ️ Nenhuma aposta ativa encontrada")
            return

        print(f"✓ Encontradas {len(current_orders)} apostas\n")
        print("=" * 60)
        print("DETALHES DAS APOSTAS")
        print("=" * 60)
        print()

        for i, order in enumerate(current_orders, 1):
            bet_id = order.get('betId', 'N/A')
            market_id = order.get('marketId', 'N/A')
            status = order.get('status', 'N/A')
            side = order.get('side', 'N/A')
            price = order.get('priceSize', {}).get('price', 'N/A')
            size = order.get('priceSize', {}).get('size', 'N/A')
            size_matched = order.get('sizeMatched', 0)
            size_remaining = order.get('sizeRemaining', 0)
            size_lapsed = order.get('sizeLapsed', 0)
            size_cancelled = order.get('sizeCancelled', 0)
            placed_date = order.get('placedDate', 'N/A')
            
            print(f"{i}. Bet ID: {bet_id}")
            print(f"   Market ID: {market_id}")
            print(f"   Status: {status}")
            print(f"   Tipo: {side}")
            print(f"   Preço: {price} | Tamanho: {size}")
            print(f"   Matched: {size_matched} | Remaining: {size_remaining}")
            print(f"   Lapsed: {size_lapsed} | Cancelled: {size_cancelled}")
            print(f"   Data: {placed_date}")
            
            # Explicar o status
            if status == 'EXECUTION_COMPLETE':
                print(f"   ⚠️ Esta aposta já foi EXECUTADA (matched)")
                print(f"   → Não pode ser cancelada, já está em jogo")
            elif status == 'LAPSED':
                print(f"   ⚠️ Esta aposta EXPIROU (lapsed)")
                print(f"   → Não pode ser cancelada, já expirou")
            elif size_remaining > 0:
                print(f"   ✅ Esta aposta ainda tem {size_remaining} disponível para cancelar")
            else:
                print(f"   ⚠️ Status: {status} - Verifique manualmente")
            
            print()

        print("=" * 60)
        print("EXPLICAÇÃO")
        print("=" * 60)
        print()
        print("Status das apostas:")
        print("  • EXECUTION_COMPLETE = Aposta foi executada (matched)")
        print("    → Não pode ser cancelada, já está em jogo")
        print()
        print("  • LAPSED = Aposta expirou")
        print("    → Não pode ser cancelada, já expirou")
        print()
        print("  • Se sizeRemaining > 0 = Ainda há parte disponível")
        print("    → Pode tentar cancelar a parte restante")
        print()

    except Exception as e:
        print(f"✗ Erro: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
