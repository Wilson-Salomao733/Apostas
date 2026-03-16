#!/usr/bin/env python3
"""
Script para verificar apostas ativas na Betfair
"""

from betfair_api import BetfairAPI
import json

def main():
    print("=" * 60)
    print("VERIFICANDO APOSTAS ATIVAS NA BETFAIR")
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
        
        if orders:
            current_orders = orders.get('currentOrders', [])
            more_available = orders.get('moreAvailable', False)
            
            print(f"✓ Encontradas {len(current_orders)} apostas ativas")
            if more_available:
                print("⚠️ Há mais apostas disponíveis (use filtros para ver todas)")
            print()
            
            if current_orders:
                print("Detalhes das Apostas:")
                print("-" * 60)
                
                for i, order in enumerate(current_orders, 1):
                    bet_id = order.get('betId', 'N/A')
                    market_id = order.get('marketId', 'N/A')
                    selection_id = order.get('selectionId', 'N/A')
                    side = order.get('side', 'N/A')
                    price = order.get('priceSize', {}).get('price', 'N/A')
                    size = order.get('priceSize', {}).get('size', 'N/A')
                    status = order.get('status', 'N/A')
                    placed_date = order.get('placedDate', 'N/A')
                    
                    print(f"\n{i}. Aposta ID: {bet_id}")
                    print(f"   Market ID: {market_id}")
                    print(f"   Selection ID: {selection_id}")
                    print(f"   Tipo: {side}")
                    print(f"   Preço: {price}")
                    print(f"   Tamanho: {size}")
                    print(f"   Status: {status}")
                    print(f"   Data: {placed_date}")
                
                # Salvar em arquivo JSON
                with open('logs/betfair_orders.json', 'w') as f:
                    json.dump(orders, f, indent=2, default=str)
                print(f"\n✓ Dados salvos em logs/betfair_orders.json")
            else:
                print("ℹ️ Nenhuma aposta ativa encontrada")
        else:
            print("ℹ️ Nenhuma resposta da API")
            
    except Exception as e:
        print(f"✗ Erro: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
