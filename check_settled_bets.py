#!/usr/bin/env python3
"""
Script para verificar apostas finalizadas e buscar dados da API de atividade da Betfair
Atualiza placar, resultado (ganhou/perdeu) e lucro/prejuízo das apostas
"""

import logging
from datetime import datetime, timedelta
from betfair_api import BetfairAPI
from database import BetDatabase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_and_update_settled_bets():
    """Verifica e atualiza apostas com dados da API de atividade"""
    try:
        db = BetDatabase()
        api = BetfairAPI()
        
        if not api.login():
            logger.error("Falha no login da API")
            return
        
        # Buscar apostas ativas ou fechadas recentemente (últimas 48 horas)
        from_date = datetime.now() - timedelta(hours=48)
        bets = db.get_bets_by_date_range(
            from_date.strftime('%Y-%m-%d'),
            datetime.now().strftime('%Y-%m-%d')
        )
        
        logger.info(f"Verificando {len(bets)} apostas...")
        
        updated_count = 0
        
        for bet in bets:
            bet_id = bet['bet_id']
            market_id = bet['market_id']
            
            # Buscar dados do mercado para verificar status e placar
            try:
                market_result = api.get_market_result(market_id)
                
                if market_result:
                    # Atualizar status do mercado
                    market_status = market_result.get('market_status')
                    if market_status:
                        db.update_bet_game_info(
                            bet_id,
                            market_status=market_status
                        )
                    
                    # Se o mercado está fechado, tentar determinar resultado
                    if market_status == 'CLOSED':
                        runners = market_result.get('runners', [])
                        for runner in runners:
                            if str(runner.get('selection_id')) == str(bet['selection_id']):
                                runner_status = runner.get('status', '')
                                result = runner.get('result', '')
                                
                                # Atualizar status do runner
                                db.update_bet_game_info(
                                    bet_id,
                                    runner_status=runner_status
                                )
                                
                                # Se a aposta ainda está ACTIVE mas o mercado fechou, atualizar status
                                if bet['status'] == 'ACTIVE':
                                    if result == 'WIN':
                                        # Verificar se é BACK ou LAY
                                        if bet['side'] == 'BACK':
                                            new_status = 'CLOSED_PROFIT'
                                        else:  # LAY
                                            new_status = 'CLOSED_LOSS'
                                    elif result == 'LOSE':
                                        if bet['side'] == 'BACK':
                                            new_status = 'CLOSED_LOSS'
                                        else:  # LAY
                                            new_status = 'CLOSED_PROFIT'
                                    else:
                                        new_status = 'CLOSED_TIMEOUT'
                                    
                                    if new_status:
                                        db.update_bet(bet_id, {
                                            'status': new_status,
                                            'close_time': datetime.now().isoformat(),
                                            'close_reason': f'Mercado fechado - Runner: {result}'
                                        })
                                        updated_count += 1
                                        logger.info(f"✓ Atualizada aposta {bet_id[:12]}... - Status: {new_status}")
                
                # Tentar buscar dados da API de atividade (settled bets)
                # Nota: Esta API pode requerer autenticação via cookies de sessão web
                settled_data = api.get_settled_bets(bet_ids=[bet_id])
                
                if settled_data and 'bets' in settled_data:
                    for settled_bet in settled_data['bets']:
                        if settled_bet.get('betId') == bet_id or settled_bet.get('betId') == f"1:{bet_id}":
                            # Atualizar com dados da API de atividade
                            db.update_bet_settled_data(bet_id, settled_bet)
                            updated_count += 1
                            logger.info(f"✓ Atualizada aposta {bet_id[:12]}... com dados da API de atividade")
                            break
                
            except Exception as e:
                logger.warning(f"Erro ao verificar aposta {bet_id[:12]}...: {e}")
                continue
        
        logger.info(f"✓ Verificação concluída. {updated_count} apostas atualizadas.")
        
    except Exception as e:
        logger.error(f"Erro ao verificar apostas finalizadas: {e}")


if __name__ == '__main__':
    check_and_update_settled_bets()
