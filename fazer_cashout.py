#!/usr/bin/env python3
"""
Script para fazer Cash Out (fechar posições) das apostas ativas
Faz uma aposta oposta (hedge) para fechar cada posição
"""

from betfair_api import BetfairAPI
import json
from datetime import datetime

def calculate_hedge_stake(back_stake, back_price, lay_price):
    """
    Calcula o stake necessário para fazer hedge (fechar posição)
    
    Args:
        back_stake: Stake da aposta BACK original
        back_price: Preço da aposta BACK original
        lay_price: Preço atual disponível para LAY
    
    Returns:
        float: Stake necessário para o hedge
    """
    # Para fechar uma posição BACK, fazemos LAY
    # Stake do hedge = (back_stake * back_price) / lay_price
    hedge_stake = (back_stake * back_price) / lay_price
    return round(hedge_stake, 2)

def calculate_lay_hedge_stake(lay_stake, lay_price, back_price):
    """
    Calcula o stake necessário para fazer hedge de uma posição LAY
    
    Args:
        lay_stake: Stake da aposta LAY original
        lay_price: Preço da aposta LAY original
        back_price: Preço atual disponível para BACK
    
    Returns:
        float: Stake necessário para o hedge
    """
    # Para fechar uma posição LAY, fazemos BACK
    # Stake do hedge = lay_stake / back_price
    hedge_stake = lay_stake / back_price
    return round(hedge_stake, 2)

def main():
    print("=" * 60)
    print("CASH OUT - FECHAR POSIÇÕES")
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

        print(f"✓ Encontradas {len(current_orders)} apostas ativas\n")

        # Agrupar por market_id e selection_id
        positions_by_market = {}
        for order in current_orders:
            market_id = order.get('marketId')
            selection_id = order.get('selectionId')
            side = order.get('side')
            status = order.get('status')
            size_matched = order.get('sizeMatched', 0)
            
            # Só processar apostas executadas
            if status != 'EXECUTION_COMPLETE' or size_matched == 0:
                continue
            
            key = f"{market_id}_{selection_id}"
            if key not in positions_by_market:
                positions_by_market[key] = {
                    'market_id': market_id,
                    'selection_id': selection_id,
                    'back_stake': 0,
                    'back_price': 0,
                    'lay_stake': 0,
                    'lay_price': 0,
                    'orders': []
                }
            
            pos = positions_by_market[key]
            pos['orders'].append(order)
            
            if side == 'BACK':
                price = order.get('averagePriceMatched', order.get('priceSize', {}).get('price', 0))
                pos['back_stake'] += size_matched
                if pos['back_price'] == 0:
                    pos['back_price'] = price
            elif side == 'LAY':
                price = order.get('averagePriceMatched', order.get('priceSize', {}).get('price', 0))
                pos['lay_stake'] += size_matched
                if pos['lay_price'] == 0:
                    pos['lay_price'] = price

        if not positions_by_market:
            print("ℹ️ Nenhuma posição executada encontrada para fazer cashout")
            return

        print(f"📊 Encontradas {len(positions_by_market)} posições únicas\n")

        total_cashout = 0
        total_failed = 0

        # Fazer cashout de cada posição
        for key, position in positions_by_market.items():
            market_id = position['market_id']
            selection_id = position['selection_id']
            
            print(f"📌 Market: {market_id} | Selection: {selection_id}")
            
            # Obter odds atuais do mercado
            try:
                market_book = api.list_market_book(
                    market_ids=[market_id],
                    price_projection={'priceData': ['EX_BEST_OFFERS']}
                )
                
                if not market_book:
                    print(f"   ⚠️ Não foi possível obter odds atuais do mercado")
                    total_failed += 1
                    continue
                
                market = market_book[0]
                if market.get('status') != 'OPEN':
                    print(f"   ⚠️ Mercado não está aberto (status: {market.get('status')})")
                    total_failed += 1
                    continue
                
                # Encontrar runner
                runners = market.get('runners', [])
                runner = None
                for r in runners:
                    r_id = r.get('id') or r.get('selectionId')
                    if str(r_id) == str(selection_id):
                        runner = r
                        break
                
                if not runner:
                    print(f"   ⚠️ Runner não encontrado no mercado")
                    total_failed += 1
                    continue
                
                # Determinar qual hedge fazer
                hedge_side = None
                hedge_stake = 0
                hedge_price = 0
                
                if position['back_stake'] > 0:
                    # Tem posição BACK, precisa fazer LAY para fechar
                    available_to_lay = runner.get('ex', {}).get('availableToLay', [])
                    if not available_to_lay:
                        print(f"   ⚠️ Sem odds disponíveis para LAY")
                        total_failed += 1
                        continue
                    
                    lay_price = available_to_lay[0].get('price', 0)
                    available_size = available_to_lay[0].get('size', 0)
                    
                    if lay_price == 0:
                        print(f"   ⚠️ Preço LAY inválido")
                        total_failed += 1
                        continue
                    
                    hedge_side = 'LAY'
                    hedge_price = lay_price
                    hedge_stake = calculate_hedge_stake(
                        position['back_stake'],
                        position['back_price'],
                        lay_price
                    )
                    
                    print(f"   📊 Posição BACK: R$ {position['back_stake']:.2f} @ {position['back_price']:.2f}")
                    print(f"   💰 Hedge LAY necessário: R$ {hedge_stake:.2f} @ {lay_price:.2f}")
                    
                    if available_size < hedge_stake:
                        print(f"   ⚠️ Liquidez insuficiente: {available_size:.2f} < {hedge_stake:.2f}")
                        total_failed += 1
                        continue
                
                elif position['lay_stake'] > 0:
                    # Tem posição LAY, precisa fazer BACK para fechar
                    available_to_back = runner.get('ex', {}).get('availableToBack', [])
                    if not available_to_back:
                        print(f"   ⚠️ Sem odds disponíveis para BACK")
                        total_failed += 1
                        continue
                    
                    back_price = available_to_back[0].get('price', 0)
                    available_size = available_to_back[0].get('size', 0)
                    
                    if back_price == 0:
                        print(f"   ⚠️ Preço BACK inválido")
                        total_failed += 1
                        continue
                    
                    hedge_side = 'BACK'
                    hedge_price = back_price
                    hedge_stake = calculate_lay_hedge_stake(
                        position['lay_stake'],
                        position['lay_price'],
                        back_price
                    )
                    
                    print(f"   📊 Posição LAY: R$ {position['lay_stake']:.2f} @ {position['lay_price']:.2f}")
                    print(f"   💰 Hedge BACK necessário: R$ {hedge_stake:.2f} @ {back_price:.2f}")
                    
                    if available_size < hedge_stake:
                        print(f"   ⚠️ Liquidez insuficiente: {available_size:.2f} < {hedge_stake:.2f}")
                        total_failed += 1
                        continue
                
                if hedge_side and hedge_stake > 0:
                    # Fazer a aposta de hedge
                    print(f"   🔄 Fazendo hedge ({hedge_side})...")
                    
                    try:
                        instruction = {
                            'instructionType': 'PLACE',
                            'selectionId': int(selection_id),
                            'handicap': 0.0,
                            'side': hedge_side,
                            'orderType': 'LIMIT',
                            'limitOrder': {
                                'size': hedge_stake,
                                'price': hedge_price,
                                'persistenceType': 'LAPSE'
                            }
                        }
                        
                        result = api.place_orders(
                            market_id=market_id,
                            instructions=[instruction],
                            customer_ref=f"cashout_{int(datetime.now().timestamp())}"
                        )
                        
                        if result and 'instructionReports' in result:
                            report = result['instructionReports'][0]
                            if report.get('status') == 'SUCCESS':
                                bet_id = report.get('betId', 'N/A')
                                print(f"   ✅ Cash Out realizado! Bet ID: {bet_id}")
                                total_cashout += 1
                            else:
                                error_code = report.get('errorCode', 'N/A')
                                error_message = report.get('errorMessage', 'N/A')
                                print(f"   ❌ Falha: {error_code} - {error_message}")
                                total_failed += 1
                        else:
                            print(f"   ❌ Resposta inesperada da API")
                            total_failed += 1
                            
                    except Exception as e:
                        print(f"   ❌ Erro ao fazer hedge: {e}")
                        total_failed += 1
                
                print()
                
            except Exception as e:
                print(f"   ❌ Erro ao processar: {e}")
                total_failed += 1
                print()

        print("=" * 60)
        print("RESUMO")
        print("=" * 60)
        print(f"✅ Cash Out realizados: {total_cashout}")
        print(f"❌ Falhas: {total_failed}")
        print()

        if total_cashout > 0:
            print("✓ Algumas posições foram fechadas com sucesso!")
            print("  As apostas originais continuam ativas, mas agora você tem")
            print("  apostas opostas que garantem um resultado fixo (lucro ou perda)")
        if total_failed > 0:
            print("⚠️ Algumas posições não puderam ser fechadas")
            print("  (Pode ser falta de liquidez, mercado fechado, etc)")

    except Exception as e:
        print(f"✗ Erro: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
