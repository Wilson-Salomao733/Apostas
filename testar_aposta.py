#!/usr/bin/env python3
"""
Script para testar se consegue fazer uma aposta
"""

from betfair_api import BetfairAPI
import json

api = BetfairAPI()
api.login()

print("=== Testando Mercados de Futebol ===\n")

# Buscar mercados
filter_dict = {
    'eventTypeIds': ['1'],
    'marketTypeCodes': ['OVER_UNDER_25'],
    'inPlay': True,
}

markets = api.list_market_catalogue(
    filter_dict=filter_dict,
    market_projection=['MARKET_DESCRIPTION', 'RUNNER_DESCRIPTION', 'EVENT'],
    max_results=5
)

print(f"Encontrados {len(markets)} mercados\n")

for i, market in enumerate(markets[:3], 1):
    market_id = market.get('marketId')
    market_name = market.get('marketName')
    event = market.get('event', {})
    event_name = event.get('name', 'N/A')
    
    print(f"{i}. {event_name}")
    print(f"   Market: {market_name}")
    print(f"   Market ID: {market_id}")
    
    # Obter runners do catalogue
    runners_catalogue = market.get('runners', [])
    print(f"   Runners no catalogue: {len(runners_catalogue)}")
    for r in runners_catalogue:
        print(f"     - ID: {r.get('id')}, Name: {r.get('runnerName')}")
    
    # Obter market book
    market_book = api.list_market_book(
        market_ids=[market_id],
        price_projection={'priceData': ['EX_BEST_OFFERS']}
    )
    
    if market_book:
        mb = market_book[0]
        print(f"   Status: {mb.get('status')}")
        mb_runners = mb.get('runners', [])
        print(f"   Runners no market book: {len(mb_runners)}")
        
        # Procurar Under 2.5
        under_runner_id = None
        for r_cat in runners_catalogue:
            if 'UNDER' in r_cat.get('runnerName', '').upper() and '2.5' in r_cat.get('runnerName', '').upper():
                under_runner_id = r_cat.get('id')
                print(f"   ✓ Under 2.5 encontrado no catalogue: ID {under_runner_id}")
                break
        
        if under_runner_id:
            # Procurar no market book pelo ID
            for r_mb in mb_runners:
                if r_mb.get('id') == under_runner_id:
                    lay = r_mb.get('ex', {}).get('availableToLay', [])
                    if lay:
                        price = lay[0].get('price')
                        size = lay[0].get('size')
                        print(f"   ✓ LAY disponível: Price {price}, Size {size}")
                        
                        # Tentar fazer aposta de teste
                        if size >= 15.0:  # Stake mínimo
                            print(f"\n   🎯 TENTANDO FAZER APOSTA DE TESTE...")
                            try:
                                instructions = [{
                                    'instructionType': 'PLACE',
                                    'handicap': 0,
                                    'side': 'LAY',
                                    'orderType': 'LIMIT',
                                    'limitOrder': {
                                        'size': 15.0,
                                        'price': price,
                                        'persistenceType': 'LAPSE'
                                    },
                                    'selectionId': int(under_runner_id)
                                }]
                                
                                result = api.place_orders(
                                    market_id=market_id,
                                    instructions=instructions,
                                    customer_ref="teste_manual"
                                )
                                
                                print(f"   Resultado: {json.dumps(result, indent=2)}")
                                
                                if result and 'instructionReports' in result:
                                    report = result['instructionReports'][0]
                                    if report.get('status') == 'SUCCESS':
                                        bet_id = report.get('betId')
                                        print(f"   ✅✅✅ APOSTA FEITA COM SUCESSO! Bet ID: {bet_id}")
                                    else:
                                        print(f"   ❌ Falha: {report.get('errorCode')} - {report.get('sizeMatched')}")
                            except Exception as e:
                                print(f"   ❌ Erro: {e}")
                        else:
                            print(f"   ⚠️ Liquidez insuficiente: {size} < 15.0")
                    else:
                        print(f"   ❌ Sem LAY disponível para este runner")
                    break
        print()

