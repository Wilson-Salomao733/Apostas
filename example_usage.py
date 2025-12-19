#!/usr/bin/env python3
"""
Exemplo completo de uso da API Betfair
"""

from betfair_api import BetfairAPI
import json

def main():
    print("=" * 60)
    print("EXEMPLO DE USO DA API BETFAIR")
    print("=" * 60)
    print()
    
    try:
        # 1. Criar cliente da API
        print("1. Inicializando cliente da API...")
        api = BetfairAPI()
        print("   ✓ Cliente criado")
        print()
        
        # 2. Fazer login
        print("2. Fazendo login...")
        if not api.login():
            print("   ✗ Falha no login")
            return
        print("   ✓ Login realizado com sucesso")
        print()
        
        # 3. Obter informações da conta
        print("3. Obtendo informações da conta...")
        funds = api.get_account_funds()
        print(f"   ✓ Saldo disponível: {funds.get('availableToBetBalance', 'N/A')}")
        print(f"   ✓ Saldo total: {funds.get('totalBalance', 'N/A')}")
        print()
        
        # 4. Listar tipos de eventos
        print("4. Listando tipos de eventos disponíveis...")
        event_types = api.list_event_types()
        print(f"   ✓ Encontrados {len(event_types)} tipos de eventos")
        
        # Mostrar os 10 primeiros
        for i, event_type in enumerate(event_types[:10], 1):
            name = event_type.get('eventType', {}).get('name', 'N/A')
            event_id = event_type.get('eventType', {}).get('id', 'N/A')
            print(f"   {i}. {name} (ID: {event_id})")
        print()
        
        # 5. Buscar mercados de futebol (ID 1)
        print("5. Buscando mercados de futebol...")
        filter_dict = {
            'eventTypeIds': ['1'],  # 1 = Futebol
            'marketCountries': ['GB'],  # Reino Unido
            'marketTypeCodes': ['MATCH_ODDS']  # Odds de partida
        }
        
        markets = api.list_market_catalogue(
            filter_dict=filter_dict,
            market_projection=['MARKET_DESCRIPTION', 'RUNNER_DESCRIPTION'],
            max_results=5
        )
        
        print(f"   ✓ Encontrados {len(markets)} mercados")
        
        if markets:
            print("\n   Primeiros mercados encontrados:")
            for i, market in enumerate(markets[:3], 1):
                market_name = market.get('marketName', 'N/A')
                event_name = market.get('event', {}).get('name', 'N/A')
                print(f"   {i}. {market_name}")
                print(f"      Evento: {event_name}")
                print(f"      ID: {market.get('marketId', 'N/A')}")
        print()
        
        # 6. Exemplo de como obter odds de um mercado específico
        if markets:
            print("6. Exemplo: Obtendo odds de um mercado...")
            market_id = markets[0].get('marketId')
            if market_id:
                market_book = api.list_market_book(
                    market_ids=[market_id],
                    price_projection={'priceData': ['EX_BEST_OFFERS']}
                )
                
                if market_book:
                    print(f"   ✓ Dados obtidos para mercado {market_id}")
                    runners = market_book[0].get('runners', [])
                    print(f"   ✓ {len(runners)} runners encontrados")
                    
                    # Mostrar odds dos primeiros 3 runners
                    for runner in runners[:3]:
                        runner_name = runner.get('runnerName', 'N/A')
                        odds = runner.get('ex', {}).get('availableToBack', [])
                        if odds:
                            best_odds = odds[0].get('price', 'N/A')
                            print(f"      {runner_name}: {best_odds}")
        print()
        
        print("=" * 60)
        print("EXEMPLO CONCLUÍDO COM SUCESSO!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ Erro: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()

