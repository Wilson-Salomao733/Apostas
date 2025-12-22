#!/usr/bin/env python3
"""
Bot de Trading Betfair - Opção A (Time Decay)
Suporta: Futebol, Hóquei e Tênis
"""

import time
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum
from betfair_api import BetfairAPI
from configparser import ConfigParser
from database import BetDatabase
from telegram_notifier import TelegramNotifier

        # Configurar logging
logging.basicConfig(
    level=logging.DEBUG,  # Mudado para DEBUG para ver mais informações
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Reduzir verbosidade de algumas bibliotecas
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)


class SportType(Enum):
    """Tipos de esportes suportados"""
    SOCCER = "Soccer"  # Futebol
    ICE_HOCKEY = "Ice Hockey"  # Hóquei
    TENNIS = "Tennis"  # Tênis


class BetStatus(Enum):
    """Status de uma aposta"""
    PENDING = "pending"  # Aguardando entrada
    ACTIVE = "active"  # Aposta ativa
    CLOSED_PROFIT = "closed_profit"  # Fechada com lucro
    CLOSED_LOSS = "closed_loss"  # Fechada com perda
    CLOSED_TIMEOUT = "closed_timeout"  # Fechada por timeout


@dataclass
class ActiveBet:
    """Representa uma aposta ativa"""
    bet_id: str
    market_id: str
    event_id: str
    sport: SportType
    strategy: str
    side: str  # "LAY" ou "BACK"
    selection_id: str
    entry_price: float
    entry_time: datetime
    stake: float
    liability: float
    take_profit_pct: float
    stop_loss_pct: float
    status: BetStatus = BetStatus.ACTIVE
    current_price: Optional[float] = None
    profit_loss: Optional[float] = None
    close_reason: Optional[str] = None


class BetfairTradingBot:
    """Bot de trading para Betfair com estratégias de Time Decay"""
    
    def __init__(self, config_file='config.ini', bot_config_file='bot_config.ini'):
        """Inicializa o bot"""
        self.config = ConfigParser()
        self.config.read(config_file)
        
        self.bot_config = ConfigParser()
        self.bot_config.read(bot_config_file)
        
        # Configurações do bot
        self.stake = float(self.bot_config.get('bot', 'stake', fallback='50.0'))
        self.max_bets_per_sport = int(self.bot_config.get('bot', 'max_bets_per_sport', fallback='10'))
        self.check_interval = int(self.bot_config.get('bot', 'check_interval', fallback='30'))  # segundos
        
        # Configurações por esporte
        self.soccer_config = {
            'enabled': self.bot_config.getboolean('soccer', 'enabled', fallback=True),
            'entry_min_minute': int(self.bot_config.get('soccer', 'entry_min_minute', fallback='5')),
            'entry_max_minute': int(self.bot_config.get('soccer', 'entry_max_minute', fallback='15')),
            'take_profit_pct': float(self.bot_config.get('soccer', 'take_profit_pct', fallback='1.5')),
            'stop_loss_pct': float(self.bot_config.get('soccer', 'stop_loss_pct', fallback='10.0')),
            'timeout_minutes': int(self.bot_config.get('soccer', 'timeout_minutes', fallback='10')),
        }
        
        self.hockey_config = {
            'enabled': self.bot_config.getboolean('hockey', 'enabled', fallback=True),
            'entry_min_minute': int(self.bot_config.get('hockey', 'entry_min_minute', fallback='3')),
            'entry_max_minute': int(self.bot_config.get('hockey', 'entry_max_minute', fallback='5')),
            'take_profit_pct': float(self.bot_config.get('hockey', 'take_profit_pct', fallback='2.0')),
            'stop_loss_pct': float(self.bot_config.get('hockey', 'stop_loss_pct', fallback='15.0')),
            'timeout_minutes': int(self.bot_config.get('hockey', 'timeout_minutes', fallback='5')),
        }
        
        self.tennis_config = {
            'enabled': self.bot_config.getboolean('tennis', 'enabled', fallback=True),
            'favorite_max_odd': float(self.bot_config.get('tennis', 'favorite_max_odd', fallback='1.40')),
            'take_profit_pct': float(self.bot_config.get('tennis', 'take_profit_pct', fallback='3.0')),
            'stop_loss_pct': float(self.bot_config.get('tennis', 'stop_loss_pct', fallback='10.0')),
        }
        
        # API
        self.api = BetfairAPI(config_file)
        self.api.login()
        
        # Banco de dados
        self.db = BetDatabase()
        
        # Carregar apostas ativas do banco de dados
        self.active_bets: Dict[str, ActiveBet] = self.load_active_bets()
        self.bet_counter = 0
        
        # Estatísticas
        self.stats = {
            'total_bets': 0,
            'profit_bets': 0,
            'loss_bets': 0,
            'total_profit': 0.0,
            'soccer_bets': 0,
            'hockey_bets': 0,
            'tennis_bets': 0,
        }
        
        logger.info("Bot inicializado")
        logger.info(f"Stake: R$ {self.stake:.2f}")
        logger.info(f"Máximo de apostas por esporte: {self.max_bets_per_sport}")
        if len(self.active_bets) > 0:
            active_count = sum(1 for b in self.active_bets.values() if b.status == BetStatus.ACTIVE)
            logger.info(f"✓ Carregadas {active_count} apostas ativas do arquivo de persistência")
        
        # Inicializar notificador do Telegram
        try:
            self.telegram = TelegramNotifier(bot_config_file)
            if self.telegram.enabled:
                logger.info("✓ Notificações do Telegram habilitadas")
        except Exception as e:
            logger.warning(f"Erro ao inicializar Telegram: {e}")
            self.telegram = None
    
    def load_active_bets(self) -> Dict[str, ActiveBet]:
        """Carrega apostas ativas do banco de dados"""
        try:
            bets_data = self.db.get_active_bets()
            active_bets = {}
            
            for bet_data in bets_data:
                # Converter strings de data de volta para datetime
                if 'entry_time' in bet_data and isinstance(bet_data['entry_time'], str):
                    bet_data['entry_time'] = datetime.fromisoformat(bet_data['entry_time'])
                
                # Converter string de sport de volta para enum
                if 'sport' in bet_data and isinstance(bet_data['sport'], str):
                    # Extrair apenas o nome do enum (ex: "SportType.SOCCER" -> "SOCCER")
                    sport_name = bet_data['sport'].split('.')[-1] if '.' in bet_data['sport'] else bet_data['sport']
                    bet_data['sport'] = SportType[sport_name]
                
                # Converter string de status de volta para enum
                if 'status' in bet_data and isinstance(bet_data['status'], str):
                    status_name = bet_data['status'].split('.')[-1] if '.' in bet_data['status'] else bet_data['status']
                    bet_data['status'] = BetStatus[status_name]
                
                active_bets[bet_data['bet_id']] = ActiveBet(**bet_data)
            
            logger.info(f"Carregadas {len(active_bets)} apostas ativas do banco de dados")
            return active_bets
        except Exception as e:
            logger.error(f"Erro ao carregar apostas do banco de dados: {e}")
            return {}
    
    def save_active_bets(self):
        """Salva apostas ativas no banco de dados"""
        # Método mantido por compatibilidade, mas agora as apostas são salvas
        # individualmente quando criadas/atualizadas
        pass
    
    def get_sport_id(self, sport: SportType) -> str:
        """Retorna o ID do esporte na Betfair"""
        sport_ids = {
            SportType.SOCCER: "1",
            SportType.ICE_HOCKEY: "2",
            SportType.TENNIS: "2",
        }
        return sport_ids.get(sport, "1")
    
    def find_live_soccer_matches(self) -> List[Dict]:
        """Encontra partidas de futebol ao vivo com placar 0-0"""
        try:
            filter_dict = {
                'eventTypeIds': ['1'],  # Soccer
                'marketTypeCodes': ['OVER_UNDER_45'],
                'inPlay': True,
            }
            
            markets = self.api.list_market_catalogue(
                filter_dict=filter_dict,
                market_projection=['MARKET_DESCRIPTION', 'RUNNER_DESCRIPTION', 'EVENT'],
                max_results=100
            )
            
            valid_matches = []
            for market in markets:
                event = market.get('event', {})
                event_name = event.get('name', '')
                
                # Verificar se é Over/Under 4.5
                market_name = market.get('marketName', '')
                if '4.5' not in market_name.upper():
                    continue
                
                market_id = market.get('marketId')
                if market_id:
                    # Verificar status do mercado ANTES de adicionar
                    # (vamos verificar no market book depois, mas já filtra alguns)
                    
                    # Obter runners do catalogue
                    runners = market.get('runners', [])
                    
                    # Encontrar runner Under 4.5 no catalogue
                    under_runner_catalogue = None
                    for runner in runners:
                        runner_name = runner.get('runnerName', '').upper()
                        if 'UNDER' in runner_name and '4.5' in runner_name:
                            under_runner_catalogue = runner
                            break
                    
                    if under_runner_catalogue:
                        # Tentar obter ID do runner - pode estar em selectionId ou id
                        runner_id = under_runner_catalogue.get('selectionId') or \
                                   under_runner_catalogue.get('id') or \
                                   under_runner_catalogue.get('runnerId')
                        
                        # Converter para int se for string
                        if runner_id and isinstance(runner_id, str):
                            try:
                                runner_id = int(runner_id)
                            except (ValueError, TypeError):
                                logger.warning(f"Mercado {market_id}: Runner ID inválido: {runner_id}")
                                continue
                        
                        if not runner_id:
                            logger.warning(f"Mercado {market_id}: Runner sem ID válido")
                            continue
                        
                        valid_matches.append({
                            'market_id': market_id,
                            'event_id': event.get('id'),
                            'event_name': event_name,
                            'market': market,
                            'under_runner_id': runner_id,
                            'under_runner_name': under_runner_catalogue.get('runnerName', '')
                        })
            
            return valid_matches
        except Exception as e:
            logger.error(f"Erro ao buscar partidas de futebol: {e}")
            return []
    
    def find_live_hockey_matches(self) -> List[Dict]:
        """Encontra partidas de hóquei ao vivo"""
        try:
            filter_dict = {
                'eventTypeIds': ['2'],  # Ice Hockey
                'marketTypeCodes': ['TOTAL_GOALS'],
                'inPlay': True,
            }
            
            markets = self.api.list_market_catalogue(
                filter_dict=filter_dict,
                market_projection=['MARKET_DESCRIPTION', 'RUNNER_DESCRIPTION', 'EVENT'],
                max_results=100
            )
            
            valid_matches = []
            for market in markets:
                event = market.get('event', {})
                market_name = market.get('marketName', '')
                
                # Procurar por mercados de período
                if '1ST PERIOD' in market_name.upper() or 'PERIOD' in market_name.upper():
                    market_id = market.get('marketId')
                    if market_id:
                        valid_matches.append({
                            'market_id': market_id,
                            'event_id': event.get('id'),
                            'event_name': event.get('name', ''),
                            'market': market
                        })
            
            return valid_matches
        except Exception as e:
            logger.error(f"Erro ao buscar partidas de hóquei: {e}")
            return []
    
    def find_live_tennis_matches(self) -> List[Dict]:
        """Encontra partidas de tênis ao vivo"""
        try:
            filter_dict = {
                'eventTypeIds': ['2'],  # Tennis
                'marketTypeCodes': ['MATCH_ODDS'],
                'inPlay': True,
            }
            
            markets = self.api.list_market_catalogue(
                filter_dict=filter_dict,
                market_projection=['MARKET_DESCRIPTION', 'RUNNER_DESCRIPTION', 'EVENT'],
                max_results=100
            )
            
            valid_matches = []
            for market in markets:
                event = market.get('event', {})
                runners = market.get('runners', [])
                
                # Encontrar o favorito (menor odd)
                if len(runners) >= 2:
                    # Obter odds atuais
                    market_id = market.get('marketId')
                    if market_id:
                        market_book = self.api.list_market_book(
                            market_ids=[market_id],
                            price_projection={'priceData': ['EX_BEST_OFFERS']}
                        )
                        
                        if market_book:
                            runners_data = market_book[0].get('runners', [])
                            if runners_data:
                                # Encontrar menor odd (favorito)
                                favorite = min(runners_data, 
                                             key=lambda r: r.get('ex', {}).get('availableToBack', [{}])[0].get('price', 999))
                                favorite_odd = favorite.get('ex', {}).get('availableToBack', [{}])[0].get('price', 999)
                                
                                if favorite_odd < self.tennis_config['favorite_max_odd']:
                                    valid_matches.append({
                                        'market_id': market_id,
                                        'event_id': event.get('id'),
                                        'event_name': event.get('name', ''),
                                        'favorite_runner': favorite,
                                        'favorite_odd': favorite_odd,
                                        'market': market
                                    })
            
            return valid_matches
        except Exception as e:
            logger.error(f"Erro ao buscar partidas de tênis: {e}")
            return []
    
    def get_match_time(self, market_id: str) -> Optional[int]:
        """Obtém o tempo de jogo em minutos (aproximado) baseado no tempo decorrido desde o início do mercado"""
        try:
            # Buscar informações do mercado para obter o horário de início
            filter_dict = {
                'marketIds': [market_id]
            }
            
            markets = self.api.list_market_catalogue(
                filter_dict=filter_dict,
                market_projection=['MARKET_START_TIME', 'EVENT'],
                max_results=1
            )
            
            if not markets or len(markets) == 0:
                logger.debug(f"Mercado {market_id}: Não encontrado no catálogo")
                return None
            
            market = markets[0]
            market_start_time_str = market.get('marketStartTime')
            
            if not market_start_time_str:
                logger.debug(f"Mercado {market_id}: Sem horário de início")
                return None
            
            # Converter para datetime (formato ISO 8601 da Betfair: "2024-01-20T15:30:00.000Z")
            try:
                # Remover milissegundos e Z se presente, adicionar timezone se necessário
                time_str = market_start_time_str.replace('Z', '+00:00')
                if '.' in time_str:
                    # Remover milissegundos
                    time_str = time_str.split('.')[0] + time_str.split('.')[1].split('+')[0] + ('+' + time_str.split('+')[1] if '+' in time_str else '')
                
                # Tentar parse ISO format
                try:
                    market_start_time = datetime.fromisoformat(time_str)
                except ValueError:
                    # Fallback: tentar parse manual
                    # Formato esperado: "2024-01-20T15:30:00+00:00" ou "2024-01-20T15:30:00"
                    if 'T' in time_str:
                        date_part, time_part = time_str.split('T')
                        time_part = time_part.split('+')[0].split('-')[0]  # Remover timezone
                        year, month, day = date_part.split('-')
                        hour, minute, second = time_part.split(':')
                        market_start_time = datetime(
                            int(year), int(month), int(day),
                            int(hour), int(minute), int(float(second)),
                            tzinfo=timezone.utc
                        )
                    else:
                        raise ValueError(f"Formato de data não reconhecido: {time_str}")
                
                # Obter tempo atual (com timezone se o market_start_time tiver)
                if market_start_time.tzinfo:
                    now = datetime.now(market_start_time.tzinfo)
                else:
                    now = datetime.now()
                
                # Calcular tempo decorrido em minutos
                elapsed = (now - market_start_time).total_seconds() / 60
                
                # Retornar apenas se o jogo já começou (tempo positivo)
                if elapsed > 0:
                    return int(elapsed)
                else:
                    logger.debug(f"Mercado {market_id}: Jogo ainda não começou (tempo: {elapsed:.1f} min)")
                    return None
                    
            except Exception as e:
                logger.debug(f"Erro ao calcular tempo do jogo {market_id}: {e}")
                return None
                
        except Exception as e:
            logger.debug(f"Erro ao obter tempo de jogo para {market_id}: {e}")
            return None
    
    def get_match_score(self, market_id: str) -> Optional[Dict[str, int]]:
        """Tenta obter o placar do jogo (retorna None se não conseguir)"""
        try:
            # A Betfair não fornece placar diretamente na API básica
            # Isso seria necessário via Stream API ou API de resultados
            # Por enquanto, retornamos None (será tratado como "desconhecido")
            return None
        except:
            return None
    
    def check_soccer_entry_conditions(self, market_id: str, under_runner_id: int = None) -> Optional[Dict]:
        """Verifica condições de entrada para futebol"""
        try:
            market_book = self.api.list_market_book(
                market_ids=[market_id],
                price_projection={'priceData': ['EX_BEST_OFFERS']}
            )
            
            if not market_book:
                logger.debug(f"Mercado {market_id}: Sem dados de mercado")
                return None
            
            market = market_book[0]
            
            # Verificar se mercado está aberto
            market_status = market.get('status')
            if market_status != 'OPEN':
                logger.debug(f"Mercado {market_id}: Status {market_status} (não está aberto - precisa ser OPEN)")
                return None
            
            runners = market.get('runners', [])
            
            if not runners:
                logger.debug(f"Mercado {market_id}: Sem runners")
                return None
            
            # Encontrar runner "Under 4.5" pelo ID ou pelo nome
            under_runner = None
            
            if under_runner_id:
                # Procurar pelo ID primeiro (mais confiável)
                # O ID pode estar em 'id' ou 'selectionId' no market book
                for runner in runners:
                    runner_id = runner.get('id') or runner.get('selectionId')
                    # Comparar como int para garantir match correto
                    try:
                        if int(runner_id) == int(under_runner_id):
                            under_runner = runner
                            logger.debug(f"Mercado {market_id}: Runner encontrado por ID: {under_runner_id}")
                            break
                    except (ValueError, TypeError):
                        continue
            
            if not under_runner:
                # Procurar pelo nome (fallback) - tentar diferentes variações
                for runner in runners:
                    runner_name = runner.get('runnerName', '').upper()
                    # Tentar diferentes formatos
                    if ('UNDER' in runner_name and '4.5' in runner_name) or \
                       ('UNDER' in runner_name and '4' in runner_name and '5' in runner_name):
                        under_runner = runner
                        logger.debug(f"Mercado {market_id}: Runner encontrado por nome: {runner_name}")
                        break
            
            if not under_runner:
                # Log para debug - tentar obter mais informações
                runner_info = []
                for r in runners:
                    r_id = r.get('id') or r.get('selectionId')
                    r_name = r.get('runnerName', 'N/A')
                    runner_info.append(f"ID:{r_id} Name:{r_name}")
                logger.debug(f"Mercado {market_id}: Não encontrou runner Under 4.5. Runners: {', '.join(runner_info)}, Procurando ID: {under_runner_id}")
                return None
            
            # Obter odd atual - MUDADO PARA BACK (a favor de Under 4.5)
            available_to_back = under_runner.get('ex', {}).get('availableToBack', [])
            if not available_to_back or len(available_to_back) == 0:
                logger.debug(f"Mercado {market_id}: Sem odds disponíveis para BACK (availableToBack vazio)")
                return None
            
            current_price = available_to_back[0].get('price', 0)
            available_size = available_to_back[0].get('size', 0)
            
            if current_price == 0 or current_price < 1.01:
                logger.debug(f"Mercado {market_id}: Preço inválido: {current_price}")
                return None
            
            # Verificar liquidez suficiente
            if available_size < self.stake:
                logger.info(f"⚠️ Mercado {market_id}: Liquidez insuficiente: {available_size:.2f} < {self.stake:.2f}")
                return None
            
            # Verificar se já temos aposta ativa neste mercado
            for bet in self.active_bets.values():
                if bet.market_id == market_id and bet.status == BetStatus.ACTIVE:
                    logger.debug(f"Mercado {market_id}: Já tem aposta ativa")
                    return None
            
            # Verificar limite de apostas
            soccer_bets_count = sum(1 for b in self.active_bets.values() 
                                  if b.sport == SportType.SOCCER and b.status == BetStatus.ACTIVE)
            if soccer_bets_count >= self.max_bets_per_sport:
                logger.info(f"⚠️ Limite de apostas de futebol atingido: {soccer_bets_count}/{self.max_bets_per_sport}")
                return None
            
            # Verificar saldo disponível antes de fazer aposta BACK
            # BACK: precisa apenas do stake (não precisa calcular liability)
            balance = self.get_account_balance()
            if balance:
                if balance['available'] < self.stake:
                    logger.warning(f"⚠️ Mercado {market_id}: Saldo insuficiente. Disponível: R$ {balance['available']:.2f}, Necessário: R$ {self.stake:.2f}")
                    return None
            else:
                logger.warning(f"⚠️ Mercado {market_id}: Não foi possível verificar saldo")
                return None
            
            # ✅ VERIFICAR TEMPO DE JOGO (entry_min_minute e entry_max_minute)
            match_time = self.get_match_time(market_id)
            if match_time is None:
                logger.debug(f"Mercado {market_id}: Não foi possível obter tempo de jogo - pulando verificação de tempo")
                # Se não conseguir obter o tempo, podemos continuar (mas não é ideal)
                # Em produção, você pode querer retornar None aqui para ser mais conservador
            else:
                min_minute = self.soccer_config['entry_min_minute']
                max_minute = self.soccer_config['entry_max_minute']
                
                if match_time < min_minute:
                    logger.info(f"⏱️ Mercado {market_id}: Jogo muito cedo ({match_time} min < {min_minute} min) - aguardando janela de entrada")
                    return None
                
                if match_time > max_minute:
                    logger.info(f"⏱️ Mercado {market_id}: Jogo muito avançado ({match_time} min > {max_minute} min) - janela de entrada passou")
                    return None
                
                logger.info(f"⏱️ Mercado {market_id}: Tempo de jogo OK ({match_time} min) - dentro da janela [{min_minute}-{max_minute} min]")
            
            # ✅ VERIFICAR PLACAR (idealmente 0-0 ou baixo)
            # Nota: A Betfair não fornece placar diretamente na API básica
            # Se você tiver acesso à Stream API, pode adicionar essa verificação aqui
            # Por enquanto, vamos confiar apenas na verificação de tempo
            match_score = self.get_match_score(market_id)
            if match_score:
                home_score = match_score.get('home', 0)
                away_score = match_score.get('away', 0)
                total_goals = home_score + away_score
                
                # Se o placar já tem muitos gols, não apostar
                if total_goals >= 2:
                    logger.info(f"⚽ Mercado {market_id}: Placar {home_score}-{away_score} - muitos gols já marcados, pulando")
                    return None
                logger.info(f"⚽ Mercado {market_id}: Placar {home_score}-{away_score} - OK para apostar")
            
            # Obter selection_id - pode estar em 'id' ou 'selectionId'
            selection_id = under_runner.get('id') or under_runner.get('selectionId')
            if not selection_id:
                logger.warning(f"Mercado {market_id}: Runner sem ID válido")
                return None
            
            # Condições atendidas! Retornar dados para aposta
            time_info = f" (Tempo: {match_time} min)" if match_time is not None else ""
            logger.info(f"✓ Condições de entrada atendidas para mercado {market_id}: Price {current_price}, Selection ID: {selection_id}{time_info}")
            return {
                'runner': under_runner,
                'price': current_price,
                'selection_id': selection_id,
                'match_time': match_time,
            }
        except Exception as e:
            logger.error(f"Erro ao verificar condições de futebol para {market_id}: {e}", exc_info=True)
            return None
    
    def place_lay_bet(self, market_id: str, selection_id: str, price: float, 
                     stake: float) -> Optional[str]:
        """Faz uma aposta LAY"""
        try:
            # Validar parâmetros
            if not market_id or not selection_id or price <= 1.0 or stake <= 0:
                logger.warning(f"Parâmetros inválidos para aposta LAY: market_id={market_id}, selection_id={selection_id}, price={price}, stake={stake}")
                return None
            
            # Calcular responsabilidade
            liability = stake * (price - 1)
            
            # Verificar saldo antes de fazer aposta
            balance = self.get_account_balance()
            if balance:
                if balance['available'] < liability:
                    logger.warning(f"Saldo insuficiente para aposta LAY. Disponível: R$ {balance['available']:.2f}, Necessário: R$ {liability:.2f}")
                    return None
            else:
                logger.warning("Não foi possível verificar saldo, mas continuando com a aposta LAY...")
            
            # Construir instrução - para Over/Under, handicap deve ser 0.0
            instruction = {
                'instructionType': 'PLACE',
                'handicap': 0.0,  # Obrigatório mesmo para Over/Under (deve ser 0.0)
                'side': 'LAY',
                'orderType': 'LIMIT',
                'limitOrder': {
                    'size': float(round(stake, 2)),  # Garantir que seja float
                    'price': float(round(price, 2)),  # Garantir que seja float
                    'persistenceType': 'LAPSE'  # Cancela se não for correspondida
                },
                'selectionId': int(selection_id)
            }
            
            instructions = [instruction]
            
            result = self.api.place_orders(
                market_id=str(market_id),  # Garantir que seja string
                instructions=instructions,
                customer_ref=f"bot_lay_{int(time.time())}"
            )
            
            if result and 'instructionReports' in result:
                report = result['instructionReports'][0]
                status = report.get('status')
                
                if status == 'SUCCESS':
                    bet_id = report.get('betId')
                    logger.info(f"✅✅✅ APOSTA LAY COLOCADA COM SUCESSO! Bet ID: {bet_id}, Price: {price:.2f}, Stake: {stake:.2f}")
                    return bet_id
                else:
                    error_code = report.get('errorCode', 'UNKNOWN')
                    error_message = report.get('sizeMatched', '')
                    instruction_error = report.get('instruction', {}).get('errorCode', '')
                    logger.error(f"❌ Falha ao colocar aposta LAY: Status={status}, ErrorCode={error_code}, InstructionError={instruction_error}, Message={error_message}")
                    if error_code == 'INSUFFICIENT_FUNDS':
                        balance = self.get_account_balance()
                        if balance:
                            logger.error(f"   Saldo disponível: R$ {balance['available']:.2f}, Necessário: R$ {liability:.2f}")
                    return None
            
            logger.warning(f"Resposta inválida ao colocar aposta LAY: {result}")
            return None
        except Exception as e:
            logger.error(f"Erro ao fazer aposta LAY: {e}", exc_info=True)
            return None
    
    def place_back_bet(self, market_id: str, selection_id: str, price: float, 
                      stake: float) -> Optional[str]:
        """Faz uma aposta BACK"""
        try:
            # Validar parâmetros básicos
            if not market_id:
                logger.error("place_back_bet: market_id é obrigatório")
                return None
            
            if not selection_id:
                logger.error("place_back_bet: selection_id é obrigatório")
                return None
            
            # Tentar converter selection_id para int
            try:
                selection_id_int = int(selection_id)
            except (ValueError, TypeError):
                logger.error(f"place_back_bet: selection_id inválido: {selection_id} (tipo: {type(selection_id)})")
                return None
            
            if price <= 1.0 or price > 1000:
                logger.error(f"place_back_bet: price inválido: {price}")
                return None
            
            if stake <= 0 or stake > 10000:
                logger.error(f"place_back_bet: stake inválido: {stake}")
                return None
            
            # Validar que price e stake são números válidos
            price_rounded = round(float(price), 2)
            stake_rounded = round(float(stake), 2)
            
            if price_rounded <= 1.0:
                logger.error(f"place_back_bet: price após arredondamento inválido: {price_rounded}")
                return None
            
            # Verificar saldo antes de fazer aposta BACK
            balance = self.get_account_balance()
            if balance:
                if balance['available'] < stake_rounded:
                    logger.warning(f"Saldo insuficiente para aposta BACK. Disponível: R$ {balance['available']:.2f}, Necessário: R$ {stake_rounded:.2f}")
                    return None
            else:
                logger.warning("Não foi possível verificar saldo, mas continuando com a aposta...")
            
            logger.debug(f"place_back_bet: market_id={market_id}, selection_id={selection_id_int}, price={price_rounded}, stake={stake_rounded}")
            
            # VALIDAÇÃO FINAL: Verificar se o mercado ainda está aberto e válido
            market_book_check = self.api.list_market_book(
                market_ids=[market_id],
                price_projection={'priceData': ['EX_BEST_OFFERS']}
            )
            
            if not market_book_check:
                logger.warning(f"place_back_bet: Não foi possível obter dados do mercado {market_id} antes da aposta")
                return None
            
            market_check = market_book_check[0]
            market_status = market_check.get('status')
            
            if market_status != 'OPEN':
                logger.warning(f"place_back_bet: Mercado {market_id} não está aberto (status: {market_status}) - abortando aposta")
                return None
            
            # Verificar se o runner ainda existe e tem liquidez
            runners_check = market_check.get('runners', [])
            runner_found = False
            current_price_valid = price_rounded
            
            for r in runners_check:
                r_id = r.get('id') or r.get('selectionId')
                if r_id == selection_id_int:
                    runner_found = True
                    available = r.get('ex', {}).get('availableToBack', [])
                    if not available or len(available) == 0:
                        logger.warning(f"place_back_bet: Runner {selection_id_int} sem liquidez para BACK")
                        return None
                    
                    # Usar o preço atual disponível
                    current_price_valid = round(available[0].get('price', 0), 2)
                    current_size = available[0].get('size', 0)
                    
                    if current_price_valid <= 1.0:
                        logger.warning(f"place_back_bet: Preço inválido: {current_price_valid}")
                        return None
                    
                    if current_size < stake_rounded:
                        logger.warning(f"place_back_bet: Liquidez insuficiente: {current_size} < {stake_rounded}")
                        return None
                    
                    # Se o preço mudou muito, usar o preço atual
                    if abs(current_price_valid - price_rounded) > 0.05:  # Tolerância de 5 centavos
                        logger.debug(f"place_back_bet: Preço mudou de {price_rounded} para {current_price_valid}, usando novo preço")
                        price_rounded = current_price_valid
                    break
            
            if not runner_found:
                logger.error(f"place_back_bet: Runner {selection_id_int} não encontrado no mercado {market_id}")
                logger.debug(f"Runners disponíveis: {[r.get('id') or r.get('selectionId') for r in runners_check]}")
                return None
            
            # Construir instrução - formato exato da API Betfair
            # IMPORTANTE: price deve ser um número (não string) e size também
            # Para Match Odds e alguns outros mercados, handicap NÃO deve ser enviado
            # Para mercados com handicap (Asian Handicap, etc), o handicap deve ser enviado
            
            # Para Match Odds (tênis, futebol, etc), NUNCA enviar handicap
            # Handicap só é necessário para mercados específicos como Asian Handicap
            # Vamos verificar o tipo de mercado pelo marketId ou pelo nome
            # Por segurança, para Match Odds, nunca enviar handicap
            
            # Construir instrução base - SEM handicap para Match Odds
            instruction = {
                'instructionType': 'PLACE',
                'side': 'BACK',
                'orderType': 'LIMIT',
                'limitOrder': {
                    'size': float(round(stake_rounded, 2)),  # Garantir que seja float
                    'price': float(round(price_rounded, 2)),  # Garantir que seja float
                    'persistenceType': 'LAPSE'
                },
                'selectionId': int(selection_id_int)
            }
            
            # IMPORTANTE: Para Match Odds, NÃO enviar handicap mesmo que o runner tenha um valor
            # O campo handicap só deve ser enviado para mercados específicos como:
            # - Asian Handicap
            # - Handicap markets
            # - Spread markets
            # 
            # Match Odds NÃO precisa de handicap, mesmo que o campo exista no runner
            logger.debug(f"place_back_bet: Match Odds - não enviando handicap (campo omitido)")
            
            instructions = [instruction]
            
            # Log detalhado antes de fazer a requisição
            logger.info(f"📤 Enviando aposta BACK: market_id={market_id}, selectionId={selection_id_int}, price={price_rounded}, size={stake_rounded}")
            logger.debug(f"📤 Instrução completa: {json.dumps(instruction, indent=2)}")
            
            try:
                # Garantir que market_id seja string
                result = self.api.place_orders(
                    market_id=str(market_id),
                    instructions=instructions,
                    customer_ref=f"bot_back_{int(time.time())}"
                )
                
                # Log da resposta
                logger.debug(f"📥 Resposta da API: {json.dumps(result, indent=2) if result else 'None'}")
            except Exception as api_error:
                # Verificar se é um erro da API (DSC-0018, etc)
                error_str = str(api_error)
                if 'DSC-0018' in error_str:
                    logger.error(f"❌ Erro DSC-0018 ao fazer aposta BACK: {api_error}")
                    logger.error(f"   Este erro geralmente indica parâmetros inválidos na requisição")
                    logger.error(f"   Market ID: {market_id}")
                    logger.error(f"   Selection ID: {selection_id_int} (tipo: {type(selection_id_int)})")
                    logger.error(f"   Price: {price_rounded} (tipo: {type(price_rounded)})")
                    logger.error(f"   Stake: {stake_rounded} (tipo: {type(stake_rounded)})")
                    logger.error(f"   Instrução enviada: {json.dumps(instruction, indent=2, default=str)}")
                    logger.error(f"   Handicap incluído: {'handicap' in instruction}")
                    
                    # Verificar se price está no formato correto (deve ser múltiplo de 0.01 e >= 1.01)
                    if price_rounded < 1.01:
                        logger.error(f"   ⚠️ PROBLEMA: Price muito baixo: {price_rounded}")
                    if price_rounded > 1000:
                        logger.error(f"   ⚠️ PROBLEMA: Price muito alto: {price_rounded}")
                    
                    # Verificar se size está no formato correto
                    if stake_rounded <= 0:
                        logger.error(f"   ⚠️ PROBLEMA: Stake inválido: {stake_rounded}")
                    
                    # Verificar se selectionId é válido
                    if selection_id_int <= 0:
                        logger.error(f"   ⚠️ PROBLEMA: Selection ID inválido: {selection_id_int}")
                    
                    # Tentar obter mais detalhes do mercado
                    try:
                        mb = self.api.list_market_book([market_id], price_projection={'priceData': ['EX_BEST_OFFERS']})
                        if mb:
                            market_data = mb[0]
                            logger.error(f"   Status do mercado: {market_data.get('status')}")
                            logger.error(f"   Market ID no response: {market_data.get('marketId')}")
                            logger.error(f"   Runners disponíveis: {[{'id': r.get('id'), 'handicap': r.get('handicap')} for r in market_data.get('runners', [])]}")
                            
                            # Verificar se o runner existe
                            target_runner = None
                            for r in market_data.get('runners', []):
                                if (r.get('id') or r.get('selectionId')) == selection_id_int:
                                    target_runner = r
                                    break
                            
                            if target_runner:
                                logger.error(f"   Runner encontrado: ID={target_runner.get('id')}, Handicap={target_runner.get('handicap')}")
                            else:
                                logger.error(f"   ⚠️ Runner {selection_id_int} NÃO encontrado no mercado!")
                    except Exception as debug_error:
                        logger.error(f"   Erro ao obter detalhes do mercado: {debug_error}")
                else:
                    logger.error(f"❌ Exceção ao fazer aposta BACK: {api_error}", exc_info=True)
                return None
            
            logger.debug(f"📥 Resposta da API: {result}")
            
            # Verificar se a resposta contém erro
            if result and isinstance(result, dict):
                if 'error' in result:
                    error_code = result.get('error', {}).get('code', 'UNKNOWN')
                    error_message = result.get('error', {}).get('message', '')
                    logger.error(f"❌ Erro na resposta da API: Code={error_code}, Message={error_message}")
                    return None
            
            if result and 'instructionReports' in result:
                report = result['instructionReports'][0]
                status = report.get('status')
                
                if status == 'SUCCESS':
                    bet_id = report.get('betId')
                    logger.info(f"✅✅✅ APOSTA BACK COLOCADA COM SUCESSO! Bet ID: {bet_id}, Price: {price_rounded}, Stake: {stake_rounded}")
                    return bet_id
                else:
                    error_code = report.get('errorCode', 'UNKNOWN')
                    error_message = report.get('sizeMatched', '')
                    instruction_error = report.get('instruction', {}).get('errorCode', '')
                    logger.error(f"❌ Falha ao colocar aposta BACK: Status={status}, ErrorCode={error_code}, InstructionError={instruction_error}, Message={error_message}")
                    logger.error(f"   Detalhes do report: {report}")
                    return None
            
            logger.warning(f"Resposta inválida ao colocar aposta BACK: {result}")
            return None
        except Exception as e:
            # Verificar se o erro contém informações sobre DSC-0018
            error_str = str(e)
            if 'DSC-0018' in error_str or 'code' in error_str:
                logger.error(f"❌ Erro DSC-0018 ao fazer aposta BACK: {e}")
                logger.error(f"   Parâmetros usados: market_id={market_id}, selection_id={selection_id}, price={price}, stake={stake}")
                logger.error(f"   selection_id_int={selection_id_int if 'selection_id_int' in locals() else 'N/A'}")
                logger.error(f"   Este erro geralmente indica que um parâmetro obrigatório está faltando ou inválido.")
                logger.error(f"   Verifique: selectionId (deve ser int), price (deve ser float > 1.0), size (deve ser float > 0)")
                logger.error(f"   Para mercados sem handicap (Match Odds, Over/Under simples), o campo 'handicap' não deve ser enviado.")
            else:
                logger.error(f"Erro ao fazer aposta BACK: {e}", exc_info=True)
            return None
    
    def cancel_bet(self, market_id: str, bet_id: str) -> bool:
        """Cancela uma aposta (Cash Out)"""
        try:
            result = self.api.cancel_orders(
                market_id=market_id,
                bet_ids=[bet_id],
                customer_ref=f"bot_cancel_{int(time.time())}"
            )
            
            if result and 'instructionReports' in result:
                report = result['instructionReports'][0]
                if report.get('status') == 'SUCCESS':
                    logger.info(f"Aposta cancelada (Cash Out): Bet ID {bet_id}")
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Erro ao cancelar aposta: {e}")
            return False
    
    def check_and_close_bet(self, bet: ActiveBet) -> bool:
        """Verifica se uma aposta deve ser fechada e fecha se necessário"""
        try:
            market_book = self.api.list_market_book(
                market_ids=[bet.market_id],
                price_projection={'priceData': ['EX_BEST_OFFERS']}
            )
            
            if not market_book:
                return False
            
            runners = market_book[0].get('runners', [])
            current_runner = next((r for r in runners if r.get('id') == bet.selection_id), None)
            
            if not current_runner:
                return False
            
            # Obter preço atual
            if bet.side == 'LAY':
                available_to_lay = current_runner.get('ex', {}).get('availableToLay', [])
                if available_to_lay:
                    current_price = available_to_lay[0].get('price', bet.entry_price)
                else:
                    current_price = bet.entry_price
            else:  # BACK
                available_to_back = current_runner.get('ex', {}).get('availableToBack', [])
                if available_to_back:
                    current_price = available_to_back[0].get('price', bet.entry_price)
                else:
                    current_price = bet.entry_price
            
            bet.current_price = current_price
            
            # Calcular P&L
            if bet.side == 'LAY':
                # LAY: lucro quando preço sobe, perda quando preço cai
                price_change_pct = ((bet.entry_price - current_price) / bet.entry_price) * 100
                if current_price > bet.entry_price:
                    # Preço subiu = lucro
                    profit_pct = ((current_price - bet.entry_price) / bet.entry_price) * 100
                else:
                    # Preço caiu = perda
                    profit_pct = -((bet.entry_price - current_price) / bet.entry_price) * 100
            else:  # BACK
                # BACK: lucro quando preço cai, perda quando preço sobe
                price_change_pct = ((current_price - bet.entry_price) / bet.entry_price) * 100
                if current_price < bet.entry_price:
                    # Preço caiu = lucro
                    profit_pct = ((bet.entry_price - current_price) / bet.entry_price) * 100
                else:
                    # Preço subiu = perda
                    profit_pct = -((current_price - bet.entry_price) / bet.entry_price) * 100
            
            bet.profit_loss = profit_pct
            
            # Verificar Take Profit
            if profit_pct >= bet.take_profit_pct:
                if self.cancel_bet(bet.market_id, bet.bet_id):
                    bet.status = BetStatus.CLOSED_PROFIT
                    bet.close_reason = f"Take Profit: {profit_pct:.2f}%"
                    self.stats['profit_bets'] += 1
                    self.stats['total_profit'] += (bet.stake * profit_pct / 100)
                    
                    # Atualizar no banco de dados
                    self.db.close_bet(
                        bet.bet_id,
                        'CLOSED_PROFIT',
                        profit_pct,
                        bet.close_reason,
                        current_price
                    )
                    
                    logger.info(f"✓ Take Profit: {bet.sport.value} - {profit_pct:.2f}%")
                    return True
            
            # Verificar Stop Loss
            if profit_pct <= -bet.stop_loss_pct:
                if self.cancel_bet(bet.market_id, bet.bet_id):
                    bet.status = BetStatus.CLOSED_LOSS
                    bet.close_reason = f"Stop Loss: {profit_pct:.2f}%"
                    self.stats['loss_bets'] += 1
                    self.stats['total_profit'] += (bet.stake * profit_pct / 100)
                    
                    # Atualizar no banco de dados
                    self.db.close_bet(
                        bet.bet_id,
                        'CLOSED_LOSS',
                        profit_pct,
                        bet.close_reason,
                        current_price
                    )
                    
                    logger.warning(f"✗ Stop Loss: {bet.sport.value} - {profit_pct:.2f}%")
                    return True
            
            # Verificar Timeout (apenas para futebol e hóquei)
            if bet.sport in [SportType.SOCCER, SportType.ICE_HOCKEY]:
                timeout_minutes = self.soccer_config['timeout_minutes'] if bet.sport == SportType.SOCCER else self.hockey_config['timeout_minutes']
                elapsed = (datetime.now() - bet.entry_time).total_seconds() / 60
                if elapsed >= timeout_minutes and profit_pct > 0:
                    if self.cancel_bet(bet.market_id, bet.bet_id):
                        bet.status = BetStatus.CLOSED_PROFIT
                        bet.close_reason = f"Timeout: {profit_pct:.2f}%"
                        self.stats['profit_bets'] += 1
                        self.stats['total_profit'] += (bet.stake * profit_pct / 100)
                        
                        # Atualizar no banco de dados
                        self.db.close_bet(
                            bet.bet_id,
                            'CLOSED_PROFIT',
                            profit_pct,
                            bet.close_reason,
                            current_price
                        )
                        
                        logger.info(f"✓ Timeout Profit: {bet.sport.value} - {profit_pct:.2f}%")
                        return True
            
            return False
        except Exception as e:
            logger.error(f"Erro ao verificar aposta {bet.bet_id}: {e}")
            return False
    
    def process_soccer_strategy(self):
        """Processa estratégia de futebol"""
        if not self.soccer_config['enabled']:
            logger.debug("Estratégia de futebol desabilitada")
            return
        
        logger.info("🔍 Buscando partidas de futebol ao vivo...")
        matches = self.find_live_soccer_matches()
        logger.info(f"📊 Encontradas {len(matches)} partidas de futebol ao vivo")
        
        if len(matches) == 0:
            logger.debug("Nenhuma partida de futebol encontrada no momento")
        
        matches_checked = 0
        matches_with_conditions = 0
        
        # Verificar saldo antes de processar
        balance = self.get_account_balance()
        if balance:
            logger.info(f"💰 Saldo disponível: R$ {balance['available']:.2f} | Stake necessário: R$ {self.stake:.2f}")
            if balance['available'] < self.stake:
                logger.warning(f"⚠️ Saldo insuficiente! Disponível: R$ {balance['available']:.2f}, Necessário: R$ {self.stake:.2f}")
        
        # Verificar limite de apostas
        soccer_bets_count = sum(1 for b in self.active_bets.values() 
                              if b.sport == SportType.SOCCER and b.status == BetStatus.ACTIVE)
        logger.info(f"📈 Apostas ativas de futebol: {soccer_bets_count}/{self.max_bets_per_sport}")
        
        for match in matches[:20]:  # Limitar a 20 para não sobrecarregar
            market_id = match['market_id']
            under_runner_id = match.get('under_runner_id')
            event_name = match.get('event_name', 'N/A')
            matches_checked += 1
            
            logger.debug(f"Verificando mercado {market_id}: {event_name}")
            entry_conditions = self.check_soccer_entry_conditions(market_id, under_runner_id)
            
            if entry_conditions:
                matches_with_conditions += 1
                logger.info(f"✅ Condições atendidas para {event_name} - Price: {entry_conditions['price']:.2f}")
                # Fazer aposta BACK (a favor de Under 4.5 Goals)
                bet_id = self.place_back_bet(
                    market_id=market_id,
                    selection_id=entry_conditions['selection_id'],
                    price=entry_conditions['price'],
                    stake=self.stake
                )
                
                if bet_id:
                    # BACK: não tem liability, apenas stake
                    entry_time = datetime.now()
                    bet = ActiveBet(
                        bet_id=bet_id,
                        market_id=market_id,
                        event_id=match['event_id'],
                        sport=SportType.SOCCER,
                        strategy="Back Under 4.5",
                        side="BACK",
                        selection_id=entry_conditions['selection_id'],
                        entry_price=entry_conditions['price'],
                        entry_time=entry_time,
                        stake=self.stake,
                        liability=0.0,  # BACK não tem liability
                        take_profit_pct=self.soccer_config['take_profit_pct'],
                        stop_loss_pct=self.soccer_config['stop_loss_pct'],
                    )
                    
                    self.active_bets[bet_id] = bet
                    self.stats['total_bets'] += 1
                    self.stats['soccer_bets'] += 1
                    
                    # Salvar no banco de dados
                    self.db.insert_bet({
                        'bet_id': bet_id,
                        'market_id': market_id,
                        'event_id': match['event_id'],
                        'event_name': match.get('event_name', ''),
                        'sport': SportType.SOCCER.name,
                        'strategy': "Back Under 4.5",
                        'side': "BACK",
                        'selection_id': entry_conditions['selection_id'],
                        'entry_price': entry_conditions['price'],
                        'entry_time': entry_time.isoformat(),
                        'stake': self.stake,
                        'liability': 0.0,
                        'take_profit_pct': self.soccer_config['take_profit_pct'],
                        'stop_loss_pct': self.soccer_config['stop_loss_pct'],
                        'status': 'ACTIVE',
                    })
                    
                    logger.info(f"✓✓✓ NOVA APOSTA FUTEBOL (BACK Under 4.5): {match['event_name']} - Price {entry_conditions['price']:.2f} - Stake R$ {self.stake:.2f}")
                    logger.info(f"   → Você GANHA se o jogo tiver MENOS de 4.5 gols (0, 1, 2, 3 ou 4 gols)")
                    
                    # Enviar notificação do Telegram
                    if self.telegram and self.telegram.enabled:
                        try:
                            balance = self.get_account_balance()
                            bet_info = {
                                'bet_id': bet_id,
                                'event_name': match.get('event_name', ''),
                                'sport': SportType.SOCCER.name,
                                'strategy': "Back Under 4.5",
                                'side': "BACK",
                                'entry_price': entry_conditions['price'],
                                'stake': self.stake,
                                'liability': 0.0,
                            }
                            self.telegram.notify_new_bet(bet_info, balance)
                        except Exception as e:
                            logger.warning(f"Erro ao enviar notificação do Telegram: {e}")
                else:
                    logger.warning(f"✗ Falha ao colocar aposta BACK para {match['event_name']}")
        
        if matches_checked > 0:
            logger.info(f"📊 Futebol: {matches_checked} mercados verificados, {matches_with_conditions} com condições atendidas")
        else:
            logger.debug("Nenhum mercado de futebol foi verificado nesta iteração")
    
    def check_hockey_entry_conditions(self, market_id: str) -> Optional[Dict]:
        """Verifica condições de entrada para hóquei"""
        try:
            market_book = self.api.list_market_book(
                market_ids=[market_id],
                price_projection={'priceData': ['EX_BEST_OFFERS']}
            )
            
            if not market_book:
                return None
            
            market = market_book[0]
            runners = market.get('runners', [])
            
            # Encontrar runner "Under" (1.5 ou 2.5)
            under_runner = None
            for runner in runners:
                runner_name = runner.get('runnerName', '').upper()
                if 'UNDER' in runner_name and ('1.5' in runner_name or '2.5' in runner_name):
                    under_runner = runner
                    break
            
            if not under_runner:
                return None
            
            # Obter odd atual
            available_to_lay = under_runner.get('ex', {}).get('availableToLay', [])
            if not available_to_lay:
                return None
            
            current_price = available_to_lay[0].get('price', 0)
            if current_price == 0:
                return None
            
            # Verificar se já temos aposta ativa neste mercado
            for bet in self.active_bets.values():
                if bet.market_id == market_id and bet.status == BetStatus.ACTIVE:
                    return None
            
            # Verificar limite de apostas
            hockey_bets_count = sum(1 for b in self.active_bets.values() 
                                   if b.sport == SportType.ICE_HOCKEY and b.status == BetStatus.ACTIVE)
            if hockey_bets_count >= self.max_bets_per_sport:
                return None
            
            return {
                'runner': under_runner,
                'price': current_price,
                'selection_id': under_runner.get('id'),
            }
        except Exception as e:
            logger.error(f"Erro ao verificar condições de hóquei: {e}")
            return None
    
    def process_hockey_strategy(self):
        """Processa estratégia de hóquei"""
        if not self.hockey_config['enabled']:
            return
        
        matches = self.find_live_hockey_matches()
        logger.info(f"Encontradas {len(matches)} partidas de hóquei ao vivo")
        
        for match in matches:
            market_id = match['market_id']
            entry_conditions = self.check_hockey_entry_conditions(market_id)
            
            if entry_conditions:
                # Fazer aposta LAY
                bet_id = self.place_lay_bet(
                    market_id=market_id,
                    selection_id=entry_conditions['selection_id'],
                    price=entry_conditions['price'],
                    stake=self.stake
                )
                
                if bet_id:
                    liability = self.stake * (entry_conditions['price'] - 1)
                    entry_time = datetime.now()
                    bet = ActiveBet(
                        bet_id=bet_id,
                        market_id=market_id,
                        event_id=match['event_id'],
                        sport=SportType.ICE_HOCKEY,
                        strategy="Lay Under Period",
                        side="LAY",
                        selection_id=entry_conditions['selection_id'],
                        entry_price=entry_conditions['price'],
                        entry_time=entry_time,
                        stake=self.stake,
                        liability=liability,
                        take_profit_pct=self.hockey_config['take_profit_pct'],
                        stop_loss_pct=self.hockey_config['stop_loss_pct'],
                    )
                    
                    self.active_bets[bet_id] = bet
                    self.stats['total_bets'] += 1
                    self.stats['hockey_bets'] += 1
                    
                    # Salvar no banco de dados
                    self.db.insert_bet({
                        'bet_id': bet_id,
                        'market_id': market_id,
                        'event_id': match['event_id'],
                        'event_name': match.get('event_name', ''),
                        'sport': SportType.ICE_HOCKEY.name,
                        'strategy': "Lay Under Period",
                        'side': "LAY",
                        'selection_id': entry_conditions['selection_id'],
                        'entry_price': entry_conditions['price'],
                        'entry_time': entry_time.isoformat(),
                        'stake': self.stake,
                        'liability': liability,
                        'take_profit_pct': self.hockey_config['take_profit_pct'],
                        'stop_loss_pct': self.hockey_config['stop_loss_pct'],
                        'status': 'ACTIVE',
                    })
                    
                    logger.info(f"✓ Nova aposta Hóquei: {match['event_name']} - Price {entry_conditions['price']}")
                    
                    # Enviar notificação do Telegram
                    if self.telegram and self.telegram.enabled:
                        try:
                            balance = self.get_account_balance()
                            bet_info = {
                                'bet_id': bet_id,
                                'event_name': match.get('event_name', ''),
                                'sport': SportType.ICE_HOCKEY.name,
                                'strategy': "Lay Under Period",
                                'side': "LAY",
                                'entry_price': entry_conditions['price'],
                                'stake': self.stake,
                                'liability': liability,
                            }
                            self.telegram.notify_new_bet(bet_info, balance)
                        except Exception as e:
                            logger.warning(f"Erro ao enviar notificação do Telegram: {e}")
    
    def process_tennis_strategy(self):
        """Processa estratégia de tênis"""
        if not self.tennis_config['enabled']:
            return
        
        matches = self.find_live_tennis_matches()
        logger.info(f"Encontradas {len(matches)} partidas de tênis ao vivo")
        
        for match in matches:
            try:
                market_id = match['market_id']
                favorite = match.get('favorite_runner')
                favorite_odd = match.get('favorite_odd')
                
                if not favorite or not favorite_odd:
                    continue
                
                # Verificar se já temos aposta ativa
                for bet in self.active_bets.values():
                    if bet.market_id == market_id and bet.status == BetStatus.ACTIVE:
                        continue
                
                # Verificar limite
                tennis_bets_count = sum(1 for b in self.active_bets.values() 
                                      if b.sport == SportType.TENNIS and b.status == BetStatus.ACTIVE)
                if tennis_bets_count >= self.max_bets_per_sport:
                    continue
                
                # Verificar se o mercado está aberto e obter odd atual
                market_book = self.api.list_market_book(
                    market_ids=[market_id],
                    price_projection={'priceData': ['EX_BEST_OFFERS']}
                )
                
                if not market_book:
                    continue
                
                market = market_book[0]
                if market.get('status') != 'OPEN':
                    logger.debug(f"Mercado de tênis não está aberto: {market.get('status')}")
                    continue
                
                # Verificar se ainda há odds disponíveis
                runners = market.get('runners', [])
                
                # Obter ID do favorito - pode estar em diferentes campos
                favorite_id = favorite.get('id') or favorite.get('selectionId') or favorite.get('runnerId')
                
                if not favorite_id:
                    logger.warning(f"Mercado {market_id}: Favorito sem ID válido: {favorite}")
                    continue
                
                # Procurar runner no market book pelo ID
                current_runner = None
                for r in runners:
                    runner_id = r.get('id') or r.get('selectionId') or r.get('runnerId')
                    if runner_id == favorite_id:
                        current_runner = r
                        break
                
                if not current_runner:
                    logger.debug(f"Mercado {market_id}: Runner do favorito não encontrado no market book. Favorite ID: {favorite_id}")
                    continue
                
                available_to_back = current_runner.get('ex', {}).get('availableToBack', [])
                if not available_to_back or len(available_to_back) == 0:
                    logger.debug(f"Mercado {market_id}: Sem odds disponíveis para BACK no favorito")
                    continue
                
                current_price = available_to_back[0].get('price', 0)
                available_size = available_to_back[0].get('size', 0)
                
                if current_price == 0 or current_price < 1.01:
                    logger.debug(f"Mercado {market_id}: Preço inválido: {current_price}")
                    continue
                
                if current_price > self.tennis_config['favorite_max_odd']:
                    logger.debug(f"Mercado {market_id}: Odd muito alta: {current_price} > {self.tennis_config['favorite_max_odd']}")
                    continue
                
                # Verificar liquidez suficiente
                if available_size < self.stake:
                    logger.debug(f"Mercado {market_id}: Liquidez insuficiente: {available_size} < {self.stake}")
                    continue
                
                # Validar selection_id antes de fazer aposta
                # O selectionId deve vir do runner atual no market book
                selection_id = current_runner.get('id')
                if not selection_id:
                    # Tentar outros campos
                    selection_id = current_runner.get('selectionId') or current_runner.get('runnerId')
                
                if not selection_id:
                    logger.error(f"Mercado {market_id}: Não foi possível obter selection_id válido do runner atual")
                    logger.debug(f"Runner atual: {current_runner}")
                    continue
                
                try:
                    # Tentar converter para int para validar
                    selection_id_int = int(selection_id)
                    if selection_id_int <= 0:
                        raise ValueError("selection_id deve ser positivo")
                except (ValueError, TypeError) as e:
                    logger.error(f"Mercado {market_id}: selection_id inválido para conversão: {selection_id} - {e}")
                    continue
                
                # Verificar novamente se o mercado ainda está aberto (pode ter mudado)
                if market.get('status') != 'OPEN':
                    logger.debug(f"Mercado {market_id}: Status mudou para {market.get('status')} antes da aposta")
                    continue
                
                # Verificar novamente se há liquidez (pode ter mudado)
                available_to_back_check = current_runner.get('ex', {}).get('availableToBack', [])
                if not available_to_back_check or len(available_to_back_check) == 0:
                    logger.debug(f"Mercado {market_id}: Liquidez desapareceu antes da aposta")
                    continue
                
                current_price_check = available_to_back_check[0].get('price', 0)
                if current_price_check != current_price:
                    logger.debug(f"Mercado {market_id}: Preço mudou de {current_price} para {current_price_check}")
                    current_price = current_price_check
                
                logger.info(f"✓ Tentando aposta BACK em tênis: Market {market_id}, Selection {selection_id_int}, Price {current_price:.2f}, Size {available_size:.2f}")
                
                # Fazer aposta BACK no favorito
                bet_id = self.place_back_bet(
                    market_id=market_id,
                    selection_id=str(selection_id_int),
                    price=current_price,
                    stake=self.stake
                )
                
                if bet_id:
                    entry_time = datetime.now()
                    bet = ActiveBet(
                        bet_id=bet_id,
                        market_id=market_id,
                        event_id=match['event_id'],
                        sport=SportType.TENNIS,
                        strategy="Back Favorite",
                        side="BACK",
                        selection_id=favorite.get('id'),
                        entry_price=current_price,
                        entry_time=entry_time,
                        stake=self.stake,
                        liability=0,  # BACK não tem responsabilidade
                        take_profit_pct=self.tennis_config['take_profit_pct'],
                        stop_loss_pct=self.tennis_config['stop_loss_pct'],
                    )
                    
                    self.active_bets[bet_id] = bet
                    self.stats['total_bets'] += 1
                    self.stats['tennis_bets'] += 1
                    
                    # Salvar no banco de dados
                    self.db.insert_bet({
                        'bet_id': bet_id,
                        'market_id': market_id,
                        'event_id': match['event_id'],
                        'event_name': match.get('event_name', ''),
                        'sport': SportType.TENNIS.name,
                        'strategy': "Back Favorite",
                        'side': "BACK",
                        'selection_id': favorite.get('id'),
                        'entry_price': current_price,
                        'entry_time': entry_time.isoformat(),
                        'stake': self.stake,
                        'liability': 0,
                        'take_profit_pct': self.tennis_config['take_profit_pct'],
                        'stop_loss_pct': self.tennis_config['stop_loss_pct'],
                        'status': 'ACTIVE',
                    })
                    
                    logger.info(f"✓ Nova aposta Tênis: {match['event_name']} - Favorite {current_price}")
                    
                    # Enviar notificação do Telegram
                    if self.telegram and self.telegram.enabled:
                        try:
                            balance = self.get_account_balance()
                            bet_info = {
                                'bet_id': bet_id,
                                'event_name': match.get('event_name', ''),
                                'sport': SportType.TENNIS.name,
                                'strategy': "Back Favorite",
                                'side': "BACK",
                                'entry_price': current_price,
                                'stake': self.stake,
                                'liability': 0.0,
                            }
                            self.telegram.notify_new_bet(bet_info, balance)
                        except Exception as e:
                            logger.warning(f"Erro ao enviar notificação do Telegram: {e}")
            except Exception as e:
                logger.error(f"Erro ao processar partida de tênis {match.get('event_name', 'N/A')}: {e}")
                continue
    
    def monitor_active_bets(self):
        """Monitora e gerencia apostas ativas"""
        bets_to_remove = []
        
        for bet_id, bet in self.active_bets.items():
            if bet.status == BetStatus.ACTIVE:
                closed = self.check_and_close_bet(bet)
                if closed:
                    bets_to_remove.append(bet_id)
        
        # Remover apostas fechadas (opcional - manter histórico)
        # for bet_id in bets_to_remove:
        #     del self.active_bets[bet_id]
    
    def get_account_balance(self):
        """Obtém o saldo da conta Betfair"""
        try:
            funds = self.api.get_account_funds()
            logger.debug(f"Resposta get_account_funds: {funds}")
            
            if funds:
                available = funds.get('availableToBetBalance', 0)
                total = funds.get('totalBalance', 0)
                exposure = funds.get('exposure', 0)
                
                balance_info = {
                    'available': float(available) if available else 0.0,
                    'total': float(total) if total else 0.0,
                    'exposure': float(exposure) if exposure else 0.0
                }
                logger.debug(f"Saldo extraído: {balance_info}")
                return balance_info
            else:
                logger.warning("get_account_funds retornou None ou vazio")
        except Exception as e:
            logger.error(f"Erro ao obter saldo da conta: {e}", exc_info=True)
        return None
    
    def print_stats(self):
        """Imprime estatísticas do bot"""
        active_count = sum(1 for b in self.active_bets.values() if b.status == BetStatus.ACTIVE)
        
        # Obter saldo da conta
        logger.debug("Buscando saldo da conta...")
        balance = self.get_account_balance()
        logger.debug(f"Resultado get_account_balance: {balance}")
        
        logger.info("=" * 60)
        logger.info("ESTATÍSTICAS DO BOT")
        logger.info("=" * 60)
        logger.info(f"Total de apostas: {self.stats['total_bets']}")
        logger.info(f"Apostas ativas: {active_count}")
        logger.info(f"Apostas com lucro: {self.stats['profit_bets']}")
        logger.info(f"Apostas com perda: {self.stats['loss_bets']}")
        logger.info(f"Lucro total: R$ {self.stats['total_profit']:.2f}")
        logger.info(f"Futebol: {self.stats['soccer_bets']} | Hóquei: {self.stats['hockey_bets']} | Tênis: {self.stats['tennis_bets']}")
        
        if balance:
            logger.info(f"💰 Saldo disponível: R$ {balance['available']:.2f}")
            logger.info(f"💰 Saldo total: R$ {balance['total']:.2f}")
            if balance['exposure'] > 0:
                logger.info(f"💰 Exposição: R$ {balance['exposure']:.2f}")
            
            # Salvar saldo no banco de dados
            self.db.save_balance(
                balance['available'],
                balance['total'],
                balance.get('exposure', 0)
            )
        else:
            logger.warning("⚠️ Não foi possível obter saldo da conta")
        
        logger.info("=" * 60)
    
    def run(self):
        """Loop principal do bot"""
        logger.info("=" * 60)
        logger.info("🤖 Bot iniciado - Procurando oportunidades...")
        logger.info("=" * 60)
        
        while True:
            try:
                cycle_start = datetime.now()
                logger.info(f"\n🔄 Ciclo #{self.bet_counter + 1} - {cycle_start.strftime('%H:%M:%S')}")
                
                # Verificar login
                if not self.api.session_token:
                    logger.warning("⚠️ Token não encontrado, fazendo login...")
                    if not self.api.login():
                        logger.error("❌ Falha no login. Aguardando antes de tentar novamente...")
                        time.sleep(60)  # Aguardar 1 minuto antes de tentar novamente
                        continue
                    else:
                        logger.info("✅ Login realizado com sucesso")
                
                # Monitorar apostas ativas
                active_count = sum(1 for b in self.active_bets.values() if b.status == BetStatus.ACTIVE)
                if active_count > 0:
                    logger.info(f"📊 Monitorando {active_count} aposta(s) ativa(s)...")
                self.monitor_active_bets()
                
                # Processar estratégias
                if self.soccer_config['enabled']:
                    self.process_soccer_strategy()
                else:
                    logger.debug("Estratégia de futebol desabilitada no config")
                
                # Hóquei desabilitado
                # if self.hockey_config['enabled']:
                #     self.process_hockey_strategy()
                
                # Tênis desabilitado
                # if self.tennis_config['enabled']:
                #     self.process_tennis_strategy()
                
                # Estatísticas a cada 10 ciclos
                if self.bet_counter % 10 == 0:
                    self.print_stats()
                    # Atualizar estatísticas diárias no banco
                    self.db.update_daily_stats()
                
                self.bet_counter += 1
                
                # Aguardar antes do próximo ciclo
                time.sleep(self.check_interval)
                
            except KeyboardInterrupt:
                logger.info("Bot interrompido pelo usuário")
                break
            except Exception as e:
                error_str = str(e)
                # Se for erro de sessão, tentar fazer novo login
                if 'INVALID_SESSION' in error_str or 'Token' in error_str:
                    logger.warning("Erro de sessão detectado, tentando fazer novo login...")
                    try:
                        if self.api.login():
                            logger.info("✓ Novo login realizado com sucesso")
                        else:
                            logger.error("Falha ao fazer novo login")
                    except Exception as login_error:
                        logger.error(f"Erro ao tentar fazer novo login: {login_error}")
                
                logger.error(f"Erro no loop principal: {e}", exc_info=True)
                time.sleep(self.check_interval)


if __name__ == '__main__':
    bot = BetfairTradingBot()
    bot.run()

